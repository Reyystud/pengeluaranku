"""CSV import: stage and preview, then commit atomically (FR-02.06 .. FR-02.14)."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.csvparse import (
    CellError,
    CsvFileError,
    CsvTable,
    decode,
    parse_amount,
    parse_date,
    parse_type,
    read_table,
)
from app.core.cursor import Cursor, decode_cursor, encode_cursor
from app.core.errors import ProblemError, not_found, validation_problem
from app.core.metrics import CATEGORIZATION_DECISIONS, CSV_IMPORTS
from app.core.text import clean_text, mask_long_numbers
from app.events.outbox import enqueue
from app.models import CategoryPrediction, Transaction, TransactionImport, User
from app.models.base import utcnow
from app.repositories import TransactionImportRepository, TransactionRepository
from app.schemas.imports import (
    CommitRequest,
    CommitResult,
    ImportPreview,
    ImportSummary,
    ImportWarning,
    RowError,
    RowPrediction,
    RowValues,
    StagedRow,
)
from app.schemas.transactions import normalize_payment_method
from app.services.categorization import CategorizeInput, Categorizer
from app.services.transactions import TransactionService
from ml.preprocessing import resolve_merchant
from ml.taxonomy import UNCATEGORIZED

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
STAGING_TTL = dt.timedelta(hours=24)
PAGE_SIZE = 500
DUPLICATE_WINDOW = dt.timedelta(minutes=10)
VALUE_PREVIEW_CHARS = 50


def template_csv(today: dt.date) -> str:
    """Header plus 3 example rows dated in the last days, so the template imports as is."""
    d1, d2, d3 = (today - dt.timedelta(days=n) for n in (3, 2, 1))
    return (
        "date,description,amount,type,payment_method,merchant,category,notes\n"
        f"{d1},Kopi Kenangan,25000,expense,e-wallet,Kopi Kenangan,,\n"
        f"{d2},Monthly Allowance,1500000,income,bank,,,\n"
        f"{d3} 18:30,Grab Transport,18.000,expense,e-wallet,Grab,transportation,Pulang kantor\n"
    )


_SAFE_NAME = re.compile(r"[^\w.\- ()]+")


def safe_filename(name: str | None) -> str:
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _SAFE_NAME.sub("_", clean_text(base))[:255].strip()
    return cleaned or "upload.csv"


def _preview_value(raw: str) -> str:
    return mask_long_numbers(clean_text(raw))[:VALUE_PREVIEW_CHARS]


class ImportService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        user: User,
        request_id: str | None = None,
        categorizer: Categorizer | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.user = user
        self.request_id = request_id
        self.tx = TransactionService(session, settings, user, request_id, categorizer)
        self._inputs: dict[int, CategorizeInput] = {}
        self.repo = TransactionImportRepository(session)
        self.transactions = TransactionRepository(session)

    # -- preview ------------------------------------------------------------------------------
    def preview(self, raw: bytes, filename: str | None) -> ImportPreview:
        if len(raw) > MAX_FILE_BYTES:
            raise file_too_large()
        try:
            table = read_table(decode(raw), max_rows=MAX_ROWS)
        except CsvFileError as exc:
            CSV_IMPORTS.labels("preview", "rejected").inc()
            raise _file_problem(exc) from exc
        sha = hashlib.sha256(raw).hexdigest()

        staged: list[StagedRow] = []
        self._inputs = {}
        for number, cells in table.rows:
            staged.append(self._stage_row(number, cells))
        self._mark_duplicates(staged)
        self._categorize(staged)

        warnings = self._warnings(table, sha)
        now = utcnow()
        imp = TransactionImport(
            id=uuid.uuid4(),
            status="previewed",
            file_sha256=sha,
            original_filename=safe_filename(filename),
            row_count=len(staged),
            valid_count=sum(r.status == "valid" for r in staged),
            invalid_count=sum(r.status == "invalid" for r in staged),
            duplicate_count=sum(r.status == "duplicate" for r in staged),
            staged_rows={
                "rows": [r.model_dump(mode="json") for r in staged],
                "warnings": [w.model_dump(mode="json") for w in warnings],
            },
            expires_at=now + STAGING_TTL,
            created_at=now,
        )
        self.repo.add(self.user.id, imp)
        CSV_IMPORTS.labels("preview", "ok").inc()
        return self._preview_of(imp, after=0)

    def _warnings(self, table: CsvTable, sha: str) -> list[ImportWarning]:
        out: list[ImportWarning] = []
        if table.unknown_columns:
            out.append(
                ImportWarning(
                    code="UNKNOWN_COLUMNS",
                    message="Unknown columns are ignored.",
                    columns=table.unknown_columns[:20],
                )
            )
        if self.repo.committed_with_sha(self.user.id, sha) is not None:
            out.append(
                ImportWarning(
                    code="FILE_ALREADY_IMPORTED",
                    message="A file with identical content was already imported.",
                )
            )
        return out

    def _stage_row(self, number: int, cells: dict[str, str]) -> StagedRow:
        errors: list[RowError] = []

        def field(column: str) -> str:
            return cells.get(column, "")

        def capture(column: str, fn: Any, *args: Any) -> Any:
            try:
                return fn(*args)
            except CellError as exc:
                code, message = exc.code, exc.message
            except ProblemError as exc:
                first = (exc.errors or [{}])[0]
                code = first.get("code", "INVALID_VALUE")
                message = first.get("message", "Invalid value.")
            errors.append(
                RowError(
                    row_number=number,
                    column=column,
                    code=code,
                    message=message,
                    value=_preview_value(field(column)) or None,
                )
            )
            return None

        def required(column: str) -> bool:
            if field(column).strip():
                return True
            errors.append(
                RowError(
                    row_number=number,
                    column=column,
                    code="MISSING_FIELD",
                    message=f"{column} is required.",
                )
            )
            return False

        tx_type = capture("type", parse_type, field("type")) if required("type") else None
        amount = None
        if required("amount"):
            amount = capture("amount", parse_amount, field("amount"))
            if amount is not None:
                amount = capture("amount", self._checked_amount, amount)
        description = (
            capture("description", self._clean, "description", field("description"), 200, True)
            if required("description")
            else None
        )
        merchant_in = capture("merchant", self._clean, "merchant", field("merchant"), 100, False)
        notes = capture("notes", self._clean, "notes", field("notes"), 500, False)
        when: tuple[dt.datetime, bool] | None = None
        if required("date"):
            parsed = capture("date", parse_date, field("date"))
            if parsed is not None:
                when = capture("date", self.tx.resolve_when, parsed)
        method = "other"
        if field("payment_method").strip():
            method = capture("payment_method", _payment_method, field("payment_method")) or "other"
        category = None
        if field("category").strip() and tx_type is not None:
            category = capture("category", self._category, field("category"), tx_type)

        if errors or None in (tx_type, amount, description, when):
            return StagedRow(row_number=number, status="invalid", errors=errors)
        assert tx_type and amount is not None and description and when
        occurred_at, has_time = when
        merchant, merchant_key = resolve_merchant(merchant_in, description)

        if category is not None:
            slug, status = category.slug, "user_set"
        else:  # categorized in one batch after the whole file is staged (see _categorize)
            slug, status = UNCATEGORIZED, "needs_review"
            self._inputs[number] = CategorizeInput(
                transaction_type=tx_type,
                description=description,
                merchant=merchant,
                merchant_key=merchant_key,
                amount=amount,
                payment_method=method,
                occurred_at=occurred_at,
                has_time=has_time,
            )
        local = occurred_at.astimezone(self.tx.tz)
        values = RowValues(
            transaction_type=tx_type,
            amount=f"{amount:.2f}",
            description=description,
            merchant=merchant,
            merchant_key=merchant_key,
            transaction_date=local.isoformat(),
            has_time=has_time,
            payment_method=method,
            category=slug,
            category_status=status,
            notes=notes,
        )
        return StagedRow(row_number=number, status="valid", values=values)

    def _categorize(self, rows: list[StagedRow]) -> None:
        """Rules first, then one batch call to the ML service (PRD 6.3). Never fails the preview."""
        targets = [r for r in rows if r.values is not None and r.row_number in self._inputs]
        if not targets:
            return
        results = self.tx.categorizer.categorize_many(
            self.user, [self._inputs[r.row_number] for r in targets], self.request_id
        )
        for row, result in zip(targets, results, strict=True):
            assert row.values is not None
            row.values.category = result.category.slug
            row.values.category_status = result.status
            row.prediction = RowPrediction(
                category=result.category.slug,
                predicted_category=result.predicted.slug if result.predicted else None,
                decision=result.decision,
                source=result.source,
                confidence=result.confidence,
                alternatives=list(result.alternatives),
                model_version=result.model_version,
                feature_version=result.feature_version,
                latency_ms=result.latency_ms,
                ml_error=result.ml_error,
                rule_id=result.rule_id,
            )

    def _mark_duplicates(self, rows: list[StagedRow]) -> None:
        """FR-02.14: against existing transactions (one query) and earlier rows of the file."""
        tz = self.tx.tz
        timed = [(r, _instant(r)) for r in rows if r.values is not None]
        if not timed:
            return
        keys = {_key(r) for r, _ in timed}
        lo = min(i for _, i in timed) - dt.timedelta(days=1)
        hi = max(i for _, i in timed) + dt.timedelta(days=2)
        existing: dict[tuple[str, Decimal, str], list[Any]] = {}
        for c in self.transactions.duplicate_candidates(self.user.id, keys, lo, hi):
            existing.setdefault((c.transaction_type, c.amount, c.merchant_key), []).append(c)
        earlier: dict[tuple[str, Decimal, str], list[tuple[StagedRow, dt.datetime]]] = {}
        for row, when in timed:
            assert row.values is not None
            key = _key(row)
            has_time = row.values.has_time
            local_day = when.astimezone(tz).date()
            match = next(
                (
                    c
                    for c in existing.get(key, [])
                    if _close(has_time, when, c.has_time, c.transaction_date, tz, local_day)
                ),
                None,
            )
            if match is not None:
                row.status, row.duplicate_of = "duplicate", match.id
            else:
                first = next(
                    (
                        e
                        for e, e_when in earlier.get(key, [])
                        if _close(
                            has_time,
                            when,
                            e.values.has_time if e.values else False,
                            e_when,
                            tz,
                            local_day,
                        )
                    ),
                    None,
                )
                if first is not None:
                    row.status, row.duplicate_of_row = "duplicate", first.row_number
            earlier.setdefault(key, []).append((row, when))

    def _clean(self, name: str, value: str, maximum: int, is_required: bool) -> str | None:
        return self.tx.clean_field(name, value, maximum=maximum, required=is_required)

    def _checked_amount(self, amount: Any) -> Any:
        self.tx.check_amount(amount)
        return amount

    def _category(self, ref: str, transaction_type: str) -> Any:
        return self.tx.resolve_category(_category_ref(ref, self.tx), transaction_type)

    # -- read ---------------------------------------------------------------------------------
    def get(self, import_id: uuid.UUID, cursor: str | None, limit: int) -> ImportPreview:
        imp = self.repo.get(self.user.id, import_id)
        if imp is None:
            raise not_found()
        after = 0
        if cursor:
            secret = self.settings.cursor_signing_key.get_secret_value()
            after = int(decode_cursor(cursor, self.user.id, secret, "import").key)
        return self._preview_of(imp, after=after, limit=limit)

    def _preview_of(
        self, imp: TransactionImport, *, after: int, limit: int = PAGE_SIZE
    ) -> ImportPreview:
        data = imp.staged_rows or {}
        rows = [StagedRow.model_validate(r) for r in data.get("rows", [])]
        page = [r for r in rows if r.row_number > after][: limit + 1]
        more = len(page) > limit
        page = page[:limit]
        next_cursor = None
        if more and page:
            secret = self.settings.cursor_signing_key.get_secret_value()
            next_cursor = encode_cursor(
                Cursor("import", str(page[-1].row_number), imp.id), self.user.id, secret
            )
        return ImportPreview(
            import_id=imp.id,
            status=imp.status,
            filename=imp.original_filename,
            summary=ImportSummary(
                row_count=imp.row_count,
                valid=imp.valid_count,
                invalid=imp.invalid_count,
                duplicate=imp.duplicate_count,
            ),
            rows=page,
            next_cursor=next_cursor,
            warnings=[ImportWarning.model_validate(w) for w in data.get("warnings", [])],
            expires_at=imp.expires_at,
        )

    # -- commit -------------------------------------------------------------------------------
    def commit(self, import_id: uuid.UUID, body: CommitRequest) -> CommitResult:
        imp = self.repo.get_for_update(self.user.id, import_id)
        if imp is None:
            raise not_found()
        if imp.status != "previewed" or imp.expires_at <= utcnow():
            raise ProblemError(
                409,
                "IMPORT_NOT_COMMITTABLE",
                "Import cannot be committed",
                "The import was already committed, discarded or has expired. Upload it again.",
            )
        if body.mode == "strict" and imp.invalid_count:
            raise ProblemError(
                422,
                "IMPORT_HAS_INVALID_ROWS",
                "Import has invalid rows",
                "Fix the invalid rows, or commit with mode=skip_invalid.",
            )
        rows = [StagedRow.model_validate(r) for r in (imp.staged_rows or {}).get("rows", [])]
        by_number = {r.row_number: r for r in rows}
        overrides = self._overrides(body, by_number)

        pending: list[tuple[StagedRow, Transaction]] = []
        skipped_duplicates = 0
        for row in rows:
            if row.status == "invalid" or row.values is None:
                continue
            if row.status == "duplicate" and body.skip_duplicates:
                skipped_duplicates += 1
                continue
            pending.append((row, self._build(row, overrides.get(row.row_number), imp.id)))

        self.transactions.add_many(self.user.id, [t for _, t in pending])
        self._record_predictions(pending)
        for row, tx in pending:
            if row.status == "duplicate":  # inserted on request: keep the flag (FR-02.14)
                duplicate = self.tx.find_duplicate_of(tx)
                tx.possible_duplicate_of = duplicate.id if duplicate else None
            self.tx.emit("transaction.created", tx)
        committed = len(pending)
        imp.status = "committed"
        imp.committed_count = committed
        imp.commit_mode = body.mode
        imp.committed_at = utcnow()
        imp.staged_rows = {}  # PRD 12: cleared after commit, counts are kept
        CSV_IMPORTS.labels("commit", "ok").inc()
        self.session.flush()
        self.tx.after_write()
        enqueue(
            self.session,
            "import.committed",
            user_id=self.user.id,
            aggregate_id=imp.id,
            request_id=self.request_id,
            data={"import_id": str(imp.id), "committed_count": committed},
        )
        return CommitResult(
            committed_count=committed,
            skipped_invalid=imp.invalid_count if body.mode == "skip_invalid" else 0,
            skipped_duplicates=skipped_duplicates,
        )

    def _record_predictions(self, pending: list[tuple[StagedRow, Transaction]]) -> None:
        """FR-03.03: one ``category_predictions`` row per categorized row, even if overridden."""
        rows: list[CategoryPrediction] = []
        applied: dict[uuid.UUID, int] = {}
        for row, tx in pending:
            p = row.prediction
            if p is None:
                continue
            top = self.tx.by_slug.get(p.predicted_category or p.category)
            confidence = None if p.confidence is None else Decimal(f"{p.confidence:.4f}")
            rows.append(
                CategoryPrediction(
                    transaction_id=tx.id,
                    source={"rule": "user_rule", "model": "model"}.get(p.source, "fallback"),
                    predicted_category_id=(top or self.tx.by_slug[p.category]).id,
                    confidence=confidence,
                    decision=p.decision,
                    alternatives=list(p.alternatives),
                    model_version=p.model_version,
                    feature_version=p.feature_version,
                    latency_ms=None if p.latency_ms is None else round(p.latency_ms),
                    ml_error=p.ml_error,
                    request_id=self.request_id or uuid.uuid4().hex,
                )
            )
            CATEGORIZATION_DECISIONS.labels(
                p.decision, {"rule": "user_rule", "model": "model"}.get(p.source, "fallback")
            ).inc()
            if p.rule_id:
                applied[p.rule_id] = applied.get(p.rule_id, 0) + 1
        self.tx.predictions.add_many(self.user.id, rows)
        for rule_id, times in applied.items():
            self.tx.rules.mark_applied(self.user.id, [rule_id], times)

    def _overrides(self, body: CommitRequest, rows: dict[int, StagedRow]) -> dict[int, Any]:
        out: dict[int, Any] = {}
        for key, ref in body.category_overrides.items():
            field = f"category_overrides.{key}"
            row = rows.get(int(key)) if key.isdigit() else None
            if row is None or row.values is None:
                raise validation_problem(field, "UNKNOWN_ROW", "No importable row has this number.")
            try:
                out[row.row_number] = self.tx.resolve_category(ref, row.values.transaction_type)
            except ProblemError as exc:
                code = (exc.errors or [{}])[0].get("code", "UNKNOWN_CATEGORY")
                raise validation_problem(field, code, "Category cannot be used here.") from exc
        return out

    def _build(self, row: StagedRow, override: Any, import_id: uuid.UUID) -> Transaction:
        v = row.values
        assert v is not None
        category = override or self.tx.by_slug[v.category]
        return Transaction(
            transaction_type=v.transaction_type,
            amount=Decimal(v.amount),
            description=v.description,
            merchant=v.merchant,
            merchant_key=v.merchant_key,
            transaction_date=dt.datetime.fromisoformat(v.transaction_date).astimezone(dt.UTC),
            has_time=v.has_time,
            payment_method=v.payment_method,
            category_id=category.id,
            category_status="user_set" if override else v.category_status,
            notes=v.notes,
            source="csv",
            import_id=import_id,
        )

    # -- discard ------------------------------------------------------------------------------
    def discard(self, import_id: uuid.UUID) -> None:
        imp = self.repo.get_for_update(self.user.id, import_id)
        if imp is None:
            raise not_found()
        if imp.status == "committed":
            raise ProblemError(
                409,
                "IMPORT_NOT_COMMITTABLE",
                "Import cannot be discarded",
                "A committed import is part of your history and cannot be discarded.",
            )
        self.session.delete(imp)
        self.session.flush()


def _payment_method(value: str) -> str:
    try:
        return normalize_payment_method(value)
    except ValueError as exc:
        raise CellError("INVALID_PAYMENT_METHOD", "Unknown payment method.") from exc


def _category_ref(ref: str, tx: TransactionService) -> str:
    """Accept a slug or a display name, case-insensitively (7.2.3)."""
    text = ref.strip().lower()
    for category in tx.by_slug.values():
        if category.name.lower() == text:
            return category.slug
    return text


def _instant(row: StagedRow) -> dt.datetime:
    assert row.values is not None
    return dt.datetime.fromisoformat(row.values.transaction_date).astimezone(dt.UTC)


def _key(row: StagedRow) -> tuple[str, Decimal, str]:
    v = row.values
    assert v is not None
    return (v.transaction_type, Decimal(v.amount), v.merchant_key)


def _close(
    has_time: bool,
    when: dt.datetime,
    other_has_time: bool,
    other_when: dt.datetime,
    tz: Any,
    local_day: dt.date,
) -> bool:
    """FR-02.12 time rule: both timed means within 10 minutes, else the same local date."""
    if has_time and other_has_time:
        return abs(when - other_when) <= DUPLICATE_WINDOW
    return other_when.astimezone(tz).date() == local_day


def file_too_large() -> ProblemError:
    return ProblemError(413, "FILE_TOO_LARGE", "File too large", "The file must be at most 5 MB.")


def _file_problem(exc: CsvFileError) -> ProblemError:
    return ProblemError(exc.status, exc.code, "Invalid file", exc.message)
