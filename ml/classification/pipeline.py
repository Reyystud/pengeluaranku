"""Sklearn pieces of the classifier: feature transformer and candidate models (PRD 9.1, 11.2.1)."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import sparse
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import LinearSVC

from ml.features.classifier import HOUR_BUCKETS

FloatArray = NDArray[np.float64]
PREDICT_BATCH = 50_000


def build_transformer(cfg: dict[str, Any], max_features: int | None = None) -> ColumnTransformer:
    """TF-IDF on text and merchant key, scaled log amount, one-hots (PRD 11.2.1).

    ``max_features`` lowers the vocabulary per vectorizer (used for the tree model).
    """
    t = cfg["tfidf"]
    char_max = max_features or int(t["char_max_features"])
    common = {"sublinear_tf": bool(t["sublinear_tf"]), "dtype": np.float32}
    return ColumnTransformer(
        [
            (
                "desc_char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=tuple(t["char_ngram"]),
                    min_df=int(t["char_min_df"]),
                    max_features=char_max,
                    **common,
                ),
                "text",
            ),
            (
                "desc_word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=tuple(t["word_ngram"]),
                    min_df=int(t["char_min_df"]),
                    max_features=max_features,
                    **common,
                ),
                "text",
            ),
            (
                "merchant_char",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=tuple(t["merchant_ngram"]),
                    min_df=int(t["char_min_df"]),
                    max_features=max_features,
                    **common,
                ),
                "merchant_key",
            ),
            ("amount", StandardScaler(), ["log_amount"]),
            (
                "categorical",
                OneHotEncoder(categories="auto", handle_unknown="ignore", dtype=np.float32),
                ["payment_method", "transaction_type"],
            ),
            (
                "hour",
                OneHotEncoder(
                    categories=[list(HOUR_BUCKETS)], handle_unknown="ignore", dtype=np.float32
                ),
                ["hour_bucket"],
            ),
            ("weekend", "passthrough", ["is_weekend"]),
        ],
        sparse_threshold=1.0,
    )


def make_model(name: str, cfg: dict[str, Any], seed: int) -> Any:
    p = cfg["models"][name]
    if name == "logreg":
        return LogisticRegression(
            C=float(p["C"]),
            max_iter=int(p["max_iter"]),
            class_weight="balanced",
            random_state=seed,
        )
    if name == "linear_svm":
        return LinearSVC(
            C=float(p["C"]),
            max_iter=int(p["max_iter"]),
            class_weight="balanced",
            random_state=seed,
        )
    if name == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=int(p["n_estimators"]),
            learning_rate=float(p["learning_rate"]),
            num_leaves=int(p["num_leaves"]),
            min_child_samples=int(p["min_child_samples"]),
            colsample_bytree=float(p["colsample_bytree"]),
            class_weight="balanced",
            random_state=seed,
            n_jobs=8,
            verbose=-1,
        )
    raise ValueError(f"unknown model {name!r}")


def scores(model: Any, X: sparse.csr_matrix) -> FloatArray:
    """Class scores: probabilities when the model has them, otherwise decision values."""
    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(X), dtype=np.float64)
    return np.asarray(model.decision_function(X), dtype=np.float64)


def has_probabilities(model: Any) -> bool:
    return hasattr(model, "predict_proba")


def batched_scores(model: Any, transformer: ColumnTransformer, frame: Any) -> FloatArray:
    """Transform and score ``frame`` in batches to bound memory."""
    parts = []
    for start in range(0, len(frame), PREDICT_BATCH):
        X = transformer.transform(frame.iloc[start : start + PREDICT_BATCH]).tocsr()
        parts.append(scores(model, X))
    return np.vstack(parts)
