"""``python -m ml_service`` starts uvicorn. Native threads are pinned before numpy is imported."""

import os

for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_var, "1")  # one worker per vCPU; avoid oversubscription (PRD 14.1)

import uvicorn  # noqa: E402

from ml_service.config import Settings  # noqa: E402
from ml_service.main import create_app  # noqa: E402


def run() -> None:
    settings = Settings()
    logging_level = settings.log_level.upper()
    uvicorn.run(
        create_app(settings),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8080")),
        log_level=logging_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    run()
