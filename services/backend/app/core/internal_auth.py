"""Authentication of internal callers (PRD 17.1): Google OIDC token, audience + service account.

Cloud Scheduler and Pub/Sub push send an ID token for the service account configured on the job or
subscription, with the worker's URL as audience. With no audience configured (local, CI) the
check is skipped; the demo worker refuses to start without one (``Settings``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request

from app.core.errors import ProblemError

TokenVerifier = Callable[[str, str], dict[str, Any]]


def google_token_verifier(token: str, audience: str) -> dict[str, Any]:
    """Verify signature, expiry and audience against Google's public keys."""
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2 import id_token

    claims: dict[str, Any] = id_token.verify_oauth2_token(token, GoogleRequest(), audience)
    return claims


def require_internal_caller(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.internal_oidc_audience:
        return
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ProblemError(401, "UNAUTHENTICATED", "Unauthenticated", "Missing bearer token.")
    verifier: TokenVerifier = request.app.state.token_verifier
    try:
        claims = verifier(token.strip(), settings.internal_oidc_audience)
    except Exception as exc:  # bad signature, expired, wrong audience: say nothing more
        raise ProblemError(
            401, "UNAUTHENTICATED", "Unauthenticated", "Invalid bearer token."
        ) from exc
    if (
        not claims.get("email_verified")
        or claims.get("email") not in settings.allowed_service_accounts
    ):
        raise ProblemError(403, "FORBIDDEN", "Forbidden", "This caller is not allowed.")
