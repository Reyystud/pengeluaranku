"""CSV reading and cell parsing for imports (PRD 7.2.3). Pure functions, no I/O, no logging."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal

REQUIRED_COLUMNS = ("date", "description", "amount", "type")
OPTIONAL_COLUMNS = ("payment_method", "merchant", "category", "notes")
KNOWN_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


class CsvFileError(ValueError):
    """The whole file is unusable. ``code`` becomes the problem code; ``status`` the HTTP status."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class CellError(ValueError):
    """One cell is invalid. Messages never contain the cell value (it may be PII)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CsvTable:
    delimiter: str
    columns: list[str]  # normalized header names that are known
    unknown_columns: list[str]
    rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)  # (row_number, cells)


def decode(raw: bytes) -> str:
    """UTF-8, BOM tolerated (FR-02.10)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvFileError(422, "INVALID_ENCODING", "The file must be UTF-8 encoded.") from exc


def detect_delimiter(header_line: str) -> str:
    return ";" if header_line.count(";") > header_line.count(",") else ","


def read_table(text: str, *, max_rows: int) -> CsvTable:
    """Split into header + non-empty rows. ``row_number`` is the line number (header = 1)."""
    lines = text.splitlines()
    header_line = next((ln for ln in lines if ln.strip()), "")
    if not header_line:
        raise CsvFileError(422, "EMPTY_FILE", "The file has no header row.")
    delimiter = detect_delimiter(header_line)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"')
    table = CsvTable(delimiter=delimiter, columns=[], unknown_columns=[])
    header: list[str] | None = None
    previous_line = 0
    try:
        for record in reader:
            start = previous_line + 1
            previous_line = reader.line_num
            if not any(cell.strip() for cell in record):
                continue  # blank lines are skipped silently
            if header is None:
                header = [cell.strip().lower() for cell in record]
                continue
            if len(table.rows) >= max_rows:
                raise CsvFileError(
                    422, "TOO_MANY_ROWS", f"The file has more than {max_rows} data rows."
                )
            cells: dict[str, str] = {}
            for name, value in zip(header, record, strict=False):
                cells.setdefault(name, value)
            table.rows.append((start, cells))
    except csv.Error as exc:
        raise CsvFileError(422, "INVALID_CSV", "The file is not valid CSV.") from exc
    assert header is not None
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise CsvFileError(
            422, "MISSING_COLUMNS", f"Missing required column(s): {', '.join(missing)}."
        )
    table.columns = [c for c in dict.fromkeys(header) if c in KNOWN_COLUMNS]
    table.unknown_columns = [c for c in dict.fromkeys(header) if c and c not in KNOWN_COLUMNS]
    return table


_DATE_FORMATS = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "ymd", False),
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{1,2}):(\d{2})(?::(\d{2}))?$"), "ymd", True),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})$"), "dmy", False),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{1,2}):(\d{2})$"), "dmy", True),
)
_INVALID_DATE = "Use YYYY-MM-DD, YYYY-MM-DD HH:MM[:SS], DD/MM/YYYY or DD/MM/YYYY HH:MM."


def parse_date(value: str) -> dt.date | dt.datetime:
    """A date (no time) or a naive datetime (the caller applies the user's timezone)."""
    text = re.sub(r"\s+", " ", value.strip())
    for pattern, order, timed in _DATE_FORMATS:
        match = pattern.match(text)
        if not match:
            continue
        g = match.groups()
        year, month, day = (
            (int(g[0]), int(g[1]), int(g[2]))
            if order == "ymd"
            else (
                int(g[2]),
                int(g[1]),
                int(g[0]),
            )
        )
        try:
            if not timed:
                return dt.date(year, month, day)
            second = int(g[5]) if len(g) > 5 and g[5] else 0
            return dt.datetime(year, month, day, int(g[3]), int(g[4]), second)
        except ValueError:
            break
    raise CellError("INVALID_DATE", _INVALID_DATE)


_PREFIX = re.compile(r"^(?:rp\.?|idr)", re.IGNORECASE)
_PLAIN = re.compile(r"^\d+(?:\.\d{1,2})?$")
_THOUSANDS = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def parse_amount(value: str) -> Decimal:
    """``25000``, ``25000.50``, ``Rp 25.000``, ``1.500.000``; a leading ``-`` is rejected."""
    text = value.strip()
    if text.startswith("-"):
        raise CellError("INVALID_AMOUNT", "Amounts must be positive; use type=expense instead.")
    text = _PREFIX.sub("", text.strip()).replace(" ", "").replace(" ", "")
    if _PLAIN.match(text):
        amount = Decimal(text)
    elif _THOUSANDS.match(text):
        amount = Decimal(text.replace(".", ""))
    else:
        raise CellError("INVALID_AMOUNT", "Amount must be digits with at most 2 decimals.")
    if amount <= 0:
        raise CellError("INVALID_AMOUNT", "Amount must be greater than 0.")
    return amount


_TYPES = {
    "income": "income",
    "expense": "expense",
    "transfer": "transfer",
    "in": "income",
    "credit": "income",
    "out": "expense",
    "debit": "expense",
}


def parse_type(value: str) -> str:
    try:
        return _TYPES[value.strip().lower()]
    except KeyError:
        raise CellError("INVALID_TYPE", "Type must be income, expense or transfer.") from None
