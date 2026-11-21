"""Latency benchmark (PRD 16.1 step 7): fixed replay of 1,000 requests, CPU, 2 threads.

One request = feature extraction + transform + scoring + calibration for one transaction, the same
work the ML service does for ``/classify`` without HTTP. The replay is the golden set cycled, so it
does not depend on any dataset. The numbers are this machine's, not an SLO measurement.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from threadpoolctl import threadpool_limits

from ml.classification.behavioural import features_for, load_golden
from ml.classification.pipeline import scores


def latency_benchmark(artifacts: dict[str, Any], knobs: dict[str, Any]) -> dict[str, Any]:
    golden = load_golden()
    n = int(knobs["requests"])
    replay = [golden[i % len(golden)] for i in range(n + int(knobs["warmup_requests"]))]
    transformer, model, calibrator = (artifacts[k] for k in ("transformer", "model", "calibrator"))
    times: list[float] = []
    with threadpool_limits(limits=int(knobs["threads"])):
        for i, case in enumerate(replay):
            start = time.perf_counter()
            frame = features_for([case])
            calibrator.predict_proba(scores(model, transformer.transform(frame).tocsr()))
            elapsed = (time.perf_counter() - start) * 1000.0
            if i >= int(knobs["warmup_requests"]):
                times.append(elapsed)
    p95 = float(np.percentile(times, 95))
    return {
        "requests": len(times),
        "threads": int(knobs["threads"]),
        "p50_ms": float(np.percentile(times, 50)),
        "p95_ms": p95,
        "p99_ms": float(np.percentile(times, 99)),
        "slo_p95_ms": float(knobs["p95_slo_ms"]),
        "within_slo": p95 <= float(knobs["p95_slo_ms"]),
    }
