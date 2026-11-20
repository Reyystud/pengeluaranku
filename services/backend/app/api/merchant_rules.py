"""Merchant rules management (PRD 7.15, 13.2). Rules are created by category changes (FR-03.08)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import not_found, validation_problem
from app.models import Category, MerchantRule
from app.models.base import utcnow
from app.repositories import CategoryRepository, MerchantRuleRepository
from app.schemas.transactions import (
    CategoryRef,
    MerchantRuleList,
    MerchantRuleOut,
    MerchantRuleUpdate,
)
from ml.taxonomy import UNCATEGORIZED

router = APIRouter(prefix="/merchant-rules", tags=["merchant-rules"])


def _out(rule: MerchantRule, categories: dict[uuid.UUID, Category]) -> MerchantRuleOut:
    category = categories[rule.category_id]
    return MerchantRuleOut(
        id=rule.id,
        merchant_key=rule.merchant_key,
        merchant_display=rule.merchant_display,
        category=CategoryRef(id=category.id, slug=category.slug, name=category.name),
        times_applied=rule.times_applied,
        last_applied_at=rule.last_applied_at,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("", response_model=MerchantRuleList)
def list_rules(session: SessionDep, user: CurrentUser) -> MerchantRuleList:
    categories = {c.id: c for c in CategoryRepository(session).list()}
    rules = MerchantRuleRepository(session).list_all(user.id)
    return MerchantRuleList(items=[_out(r, categories) for r in rules])


@router.patch("/{rule_id}", response_model=MerchantRuleOut)
def update_rule(
    rule_id: uuid.UUID, body: MerchantRuleUpdate, session: SessionDep, user: CurrentUser
) -> MerchantRuleOut:
    repo = MerchantRuleRepository(session)
    rule = repo.get(user.id, rule_id)
    if rule is None:
        raise not_found()
    categories = CategoryRepository(session).list()
    by_id = {c.id: c for c in categories}
    ref = body.category.strip().lower()
    target = next((c for c in categories if c.slug == ref or str(c.id) == ref), None)
    if target is None or target.slug == UNCATEGORIZED:
        raise validation_problem("category", "UNKNOWN_CATEGORY", "Choose a real category.")
    rule.category_id = target.id  # past transactions stay as they are (FR-15.02)
    rule.updated_at = utcnow()
    session.flush()
    return _out(rule, by_id)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Response:
    if not MerchantRuleRepository(session).delete(user.id, rule_id):
        raise not_found()
    return Response(status_code=204)
