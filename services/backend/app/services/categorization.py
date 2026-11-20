"""Categorization: merchant rule, then ML, then fallback (PRD 6.3, 7.3).

Saving a transaction must never fail because of the ML service: every ML problem ends as
``uncategorized`` + ``needs_review`` with an ``ml_error`` code (FR-03.01, PRD 6.3 step 5).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.clients.ml import MlClient, MlPrediction, MlResult
from app.models import Category, User
from app.repositories import MerchantRuleRepository
from ml.features import FEATURE_VERSION
from ml.taxonomy import UNCATEGORIZED


@dataclass(frozen=True)
class CategorizeInput:
    transaction_type: str
    description: str
    merchant: str
    merchant_key: str
    amount: Decimal
    payment_method: str
    occurred_at: dt.datetime  # UTC instant
    has_time: bool


@dataclass(frozen=True)
class CategorizationResult:
    category: Category  # what is stored on the transaction
    status: str  # category_status
    decision: str  # auto_apply | suggest | needs_review
    source: str  # user | rule | model | fallback
    predicted: Category | None = None  # the model's/rule's top pick (may differ from `category`)
    confidence: float | None = None
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    model_version: str | None = None
    feature_version: str | None = None
    latency_ms: float | None = None
    ml_error: str | None = None
    rule_id: uuid.UUID | None = None


class Categorizer(Protocol):
    """Must never raise for ML problems."""

    def categorize(
        self, user: User, item: CategorizeInput, request_id: str | None = None
    ) -> CategorizationResult: ...

    def categorize_many(
        self, user: User, items: Sequence[CategorizeInput], request_id: str | None = None
    ) -> list[CategorizationResult]: ...


def compatible(category: Category, transaction_type: str) -> bool:
    return category.transaction_type in ("any", transaction_type)


class FallbackCategorizer:
    """No rule, no model: used when nothing else is wired (unit tests)."""

    def __init__(self, categories: dict[str, Category]) -> None:
        self._uncategorized = categories[UNCATEGORIZED]

    def categorize(
        self, user: User, item: CategorizeInput, request_id: str | None = None
    ) -> CategorizationResult:
        return self._result()

    def categorize_many(
        self, user: User, items: Sequence[CategorizeInput], request_id: str | None = None
    ) -> list[CategorizationResult]:
        return [self._result() for _ in items]

    def _result(self) -> CategorizationResult:
        return CategorizationResult(
            self._uncategorized,
            "needs_review",
            "needs_review",
            "fallback",
            predicted=self._uncategorized,
            ml_error="disabled",
        )


class MlCategorizer:
    def __init__(
        self,
        session: Session,
        client: MlClient,
        by_slug: dict[str, Category],
        by_id: dict[uuid.UUID, Category],
    ) -> None:
        self._rules = MerchantRuleRepository(session)
        self._client = client
        self._by_slug = by_slug
        self._by_id = by_id
        self._uncategorized = by_slug[UNCATEGORIZED]

    def categorize(
        self, user: User, item: CategorizeInput, request_id: str | None = None
    ) -> CategorizationResult:
        return self.categorize_many(user, [item], request_id)[0]

    def categorize_many(
        self, user: User, items: Sequence[CategorizeInput], request_id: str | None = None
    ) -> list[CategorizationResult]:
        keys = list({i.merchant_key for i in items if i.merchant_key})
        rules = self._rules.get_many_by_keys(user.id, keys)
        results: list[CategorizationResult | None] = [None] * len(items)
        pending: list[int] = []
        for index, item in enumerate(items):
            rule = rules.get(item.merchant_key) if item.merchant_key else None
            category = self._by_id.get(rule.category_id) if rule else None
            if rule and category and compatible(category, item.transaction_type):
                results[index] = CategorizationResult(
                    category, "rule", "auto_apply", "rule", predicted=category, rule_id=rule.id
                )
            else:
                pending.append(index)  # a rule for another transaction type is ignored (FR-03.10)

        if pending:
            payloads = [self._payload(user, items[i], request_id, n) for n, i in enumerate(pending)]
            if len(payloads) == 1:
                answers = [self._client.classify(payloads[0], request_id)]
            else:
                answers = self._client.classify_batch(payloads, request_id)
            for index, answer in zip(pending, answers, strict=True):
                results[index] = self._interpret(items[index], answer)
        return [r for r in results if r is not None]

    @staticmethod
    def _payload(
        user: User, item: CategorizeInput, request_id: str | None, n: int
    ) -> dict[str, Any]:
        """PRD 14.2 ``ClassifyRequest``: no user id, local hour and weekday in the user's zone."""
        local = item.occurred_at.astimezone(ZoneInfo(user.timezone))
        return {
            "request_id": f"{(request_id or 'req')[:50]}-{n}",
            "description": item.description,
            "merchant_key": item.merchant_key,
            "amount": f"{item.amount:.2f}",
            "payment_method": item.payment_method,
            "transaction_type": item.transaction_type,
            "local_hour": local.hour if item.has_time else None,
            "weekday": local.weekday(),
            "feature_version": FEATURE_VERSION,
        }

    def _fallback(self, error: str) -> CategorizationResult:
        return CategorizationResult(
            self._uncategorized,
            "needs_review",
            "needs_review",
            "fallback",
            predicted=self._uncategorized,
            ml_error=error,
        )

    def _interpret(self, item: CategorizeInput, answer: MlResult) -> CategorizationResult:
        pred = answer.prediction
        if pred is None:
            return self._fallback(answer.error or "unavailable")
        ranked = [(pred.predicted_category, pred.confidence)] + [
            (a.category, a.confidence) for a in pred.alternatives
        ]
        if any(slug not in self._by_slug for slug, _ in ranked):
            return self._fallback("bad_response")  # a label outside our taxonomy
        top = self._by_slug[pred.predicted_category]
        alternatives = [a.model_dump() for a in pred.alternatives]
        common: dict[str, Any] = {
            "alternatives": alternatives,
            "model_version": pred.model_version,
            "feature_version": pred.feature_version,
            "latency_ms": pred.latency_ms,
            "predicted": top,
            "confidence": pred.confidence,
        }
        # FR-03.10: the best-ranked of the top 3 whose category fits the transaction type.
        for rank, (slug, confidence) in enumerate(ranked):
            category = self._by_slug[slug]
            if category.slug == UNCATEGORIZED or not compatible(category, item.transaction_type):
                continue
            decision = pred.decision if rank == 0 else _decide(confidence, pred)
            return self._decided(category, decision, common | {"confidence": confidence})
        return self._decided(self._uncategorized, "needs_review", common)

    def _decided(
        self, category: Category, decision: str, common: dict[str, Any]
    ) -> CategorizationResult:
        if decision == "auto_apply":
            return CategorizationResult(category, "auto", decision, "model", **common)
        if decision == "suggest":
            return CategorizationResult(category, "suggested", decision, "model", **common)
        return CategorizationResult(
            self._uncategorized, "needs_review", "needs_review", "model", **common
        )


def _decide(confidence: float, pred: MlPrediction) -> str:
    """Re-apply the model's own thresholds to a lower-ranked alternative (PRD 7.3.4)."""
    if confidence >= pred.thresholds.t_high:
        return "auto_apply"
    if confidence >= pred.thresholds.t_low:
        return "suggest"
    return "needs_review"
