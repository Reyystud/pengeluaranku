"""Behavior segment of one user (PRD 7.13, FR-13): features, assignment, traits.

The features come from ``ml.clustering.features.raw_features``, the same function the training
script uses, so batch and online features cannot differ (PRD 11.1). The model is the artifact
``config/clusterer_model.yaml`` (centroids, deciles, names chosen by a person).
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from sqlalchemy.orm import Session

from app.core.periods import PeriodBounds
from app.models import User
from app.repositories.forecasts import ForecastRepository
from app.repositories.segments import SegmentRepository
from app.schemas.segments import SegmentInfo, SegmentOut, TraitOut
from app.services.analytics import AnalyticsService
from app.services.recurring import RecurringService
from ml.clustering.config import load_clustering_config
from ml.clustering.features import EXPENSE_CATEGORIES, RAW_COLUMNS, raw_features
from ml.clustering.model import Clusterer, traits
from ml.config import config_dir
from ml.taxonomy import get_category

MODEL_FILE = "clusterer_model.yaml"
LABELS = {
    "avg_tx_amount": "average purchase",
    "monthly_expense": "monthly spending",
    "tx_per_day": "number of purchases per day",
    "weekend_spend_ratio": "share of spending on weekends",
    "recurring_ratio": "share of spending on recurring payments",
    "small_tx_ratio": "share of small purchases",
    "income_regularity": "income irregularity",
    "savings_rate": "share of income you save",
}


@lru_cache(maxsize=1)
def load_clusterer() -> Clusterer | None:
    path = config_dir() / MODEL_FILE
    if not path.exists():
        return None
    return Clusterer.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def trait_label(feature: str) -> str:
    if feature.startswith("category_share_"):
        slug = feature.removeprefix("category_share_")
        return f"share of spending on {get_category(slug).display_name}"
    return LABELS[feature]


class SegmentService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.session = session
        self.user = user
        self.cfg = load_clustering_config()
        self.repo = SegmentRepository(session)
        self.now = now or dt.datetime.now(dt.UTC)
        self.tz = ZoneInfo(user.timezone)
        self.analytics = AnalyticsService(session, user, self.now)

    # -- window --------------------------------------------------------------------------------
    def complete_periods(self) -> list[PeriodBounds]:
        """Up to ``cfg.periods`` complete periods, oldest first, that began on or after the day
        of the user's first transaction (so the user was there for the whole period)."""
        first = ForecastRepository(self.session).first_local_date(self.user.id, self.user.timezone)
        if first is None:
            return []
        out: list[PeriodBounds] = []
        day = self.analytics.period_of(self.analytics.today).start - dt.timedelta(days=1)
        while len(out) < self.cfg.periods:
            period = self.analytics.period_of(day)
            if period.start < first:
                break
            out.append(period)
            day = period.start - dt.timedelta(days=1)
        return out[::-1]

    # -- assignment ----------------------------------------------------------------------------
    def compute(self) -> bool:
        """Assign and store the segment; False when the user has too little history."""
        model = load_clusterer()
        periods = self.complete_periods()
        if model is None or len(periods) < self.cfg.min_periods:
            return False
        RecurringService(self.session, self.user, self.now).detect()  # links split recurring spend
        lo = dt.datetime.combine(periods[0].start, dt.time.min, tzinfo=self.tz)
        hi = dt.datetime.combine(
            periods[-1].end + dt.timedelta(days=1), dt.time.min, tzinfo=self.tz
        )
        rec_min = RecurringService(self.session, self.user, self.now).cfg.decomposition_min
        rows = self.repo.window_rows(self.user.id, lo, hi, rec_min)
        frame = pd.DataFrame(
            [
                {
                    "occurred_at": pd.Timestamp(when.astimezone(self.tz).replace(tzinfo=None)),
                    "type": kind,
                    "amount_f": float(amount),
                    "category": slug,
                    "recurring": bool(linked),
                }
                for when, kind, amount, slug, linked in rows
            ],
            columns=["occurred_at", "type", "amount_f", "category", "recurring"],
        )
        days = (periods[-1].end - periods[0].start).days + 1
        feats = raw_features(frame, days, len(periods), self.cfg)
        if feats is None:
            return False
        raw = pd.DataFrame([feats], columns=list(RAW_COLUMNS))
        index, _ = model.assign(raw, self.cfg)
        segment = model.segments[int(index[0])]
        found = traits(feats, segment, self.cfg)
        self.repo.upsert(self.user.id, segment.id, found, model.version, self.now)
        return True

    # -- read ----------------------------------------------------------------------------------
    def current(self) -> SegmentOut:
        model = load_clusterer()
        have = len(self.complete_periods())
        base = {"complete_periods": have, "required_periods": self.cfg.min_periods}
        if model is None:
            return SegmentOut(segment=None, reason="MODEL_NOT_AVAILABLE", **base)
        row = self.repo.get(self.user.id)
        if row is None:
            if have >= self.cfg.min_periods:
                return SegmentOut(segment=None, reason="NOT_COMPUTED", **base)
            return SegmentOut(segment=None, reason="INSUFFICIENT_HISTORY", **base)
        meta = next((s for s in model.segments if s.id == row.segment_id), None)
        if meta is None:  # the artifact was replaced after this row was written
            return SegmentOut(segment=None, reason="NOT_COMPUTED", **base)
        items = [
            TraitOut(
                feature=t["feature"],
                direction=t["direction"],
                percent=int(t["percent"]),
                value=float(t["value"]),
                message=(
                    f"Your {trait_label(t['feature'])} is {t['direction']} "
                    f"than {int(t['percent'])}% of similar users"
                ),
            )
            for t in row.traits
        ]
        info = SegmentInfo(
            id=meta.id,
            name=meta.name or meta.id,
            description=meta.description,
            traits=items,
            model_version=row.model_version,
            computed_at=row.computed_at,
        )
        return SegmentOut(segment=info, reason=None, **base)


__all__ = ["SegmentService", "load_clusterer", "EXPENSE_CATEGORIES"]
