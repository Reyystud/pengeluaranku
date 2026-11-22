"""Shadow mode (PRD 16.4): mirror requests to the candidate model after the response is sent."""

from ml_service.shadow.runner import run_candidate

__all__ = ["run_candidate"]
