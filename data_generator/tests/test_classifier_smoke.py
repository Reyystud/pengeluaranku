"""End-to-end smoke test: generated data -> features -> transformer -> LR -> calibration."""

import numpy as np
import pandas as pd

from ml.classification.calibration import IsotonicOvR
from ml.classification.config import load_train_config
from ml.classification.metrics import summarize
from ml.classification.pipeline import build_transformer, make_model, scores
from ml.classification.train import LABEL_ID, LABELS, select_winner
from ml.features.classifier import build_feature_frame


def test_classifier_pipeline_runs_on_generated_data(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    cfg = load_train_config()
    feats = build_feature_frame(tx)
    y = tx["true_category"].map(LABEL_ID).to_numpy(dtype=np.int64)
    cut = int(len(tx) * 0.7)
    transformer = build_transformer(cfg, max_features=2000)
    X_train = transformer.fit_transform(feats.iloc[:cut]).tocsr()
    model = make_model("logreg", cfg, 42)
    model.fit(X_train, y[:cut])
    raw = np.zeros((len(tx) - cut, len(LABELS)))
    raw[:, model.classes_] = scores(model, transformer.transform(feats.iloc[cut:]).tocsr())
    proba = IsotonicOvR().fit(raw, y[cut:]).predict_proba(raw)
    result = summarize(proba, y[cut:], LABELS, 15)
    assert result["accuracy"] > 0.5
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert isinstance(feats, pd.DataFrame)


def _fake(val_f1: float) -> dict[str, dict[str, float]]:
    return {"validation": {"macro_f1": val_f1}}


def test_fr_03_decision_rule_requires_two_point_gain() -> None:
    cfg = load_train_config()
    close = {"logreg": _fake(0.90), "linear_svm": _fake(0.919), "lightgbm": _fake(0.85)}
    assert select_winner(close, cfg)["winner"] == "logreg"  # +1.9 points is not enough
    clear = {"logreg": _fake(0.90), "linear_svm": _fake(0.921), "lightgbm": _fake(0.93)}
    assert select_winner(clear, cfg)["winner"] == "lightgbm"  # best among those that pass
