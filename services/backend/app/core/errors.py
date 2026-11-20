"""RFC 9457 problem+json errors (PRD 13.1.2)."""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

_CODED_MESSAGE = re.compile(r"^(?:Value error, )?([A-Z][A-Z_]{3,}): (.*)$", re.S)
PROBLEM_BASE = "https://smart-expense.dev/problems/"
PROBLEM_CONTENT_TYPE = "application/problem+json"

_STATUS_CODES = {
    400: ("BAD_REQUEST", "Bad request"),
    401: ("UNAUTHENTICATED", "Authentication required"),
    403: ("FORBIDDEN", "Forbidden"),
    404: ("NOT_FOUND", "Resource not found"),
    405: ("METHOD_NOT_ALLOWED", "Method not allowed"),
    409: ("CONFLICT", "Conflict"),
    413: ("PAYLOAD_TOO_LARGE", "Payload too large"),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Unsupported media type"),
    422: ("VALIDATION_ERROR", "Validation failed"),
    429: ("RATE_LIMITED", "Too many requests"),
    500: ("INTERNAL_ERROR", "Internal server error"),
    503: ("SERVICE_UNAVAILABLE", "Service unavailable"),
}


class ProblemError(Exception):
    """Raise from any route or service to produce a problem+json response."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        errors: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors
        self.headers = headers or {}


def validation_problem(field: str, code: str, message: str) -> ProblemError:
    """422 with one field error. Never put the offending value in ``message`` (may be PII)."""
    return ProblemError(
        422,
        "VALIDATION_ERROR",
        "Validation failed",
        "One or more fields are invalid.",
        errors=[{"field": field, "code": code, "message": message}],
    )


def not_found(detail: str = "The requested resource was not found.") -> ProblemError:
    """Cross-user access must look exactly like this (PRD 0.3 rule 6)."""
    return ProblemError(404, "NOT_FOUND", "Resource not found", detail)


def problem_response(
    status: int,
    code: str,
    title: str,
    request_id: str | None,
    detail: str | None = None,
    errors: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + code.lower().replace("_", "-"),
        "title": title,
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    body["request_id"] = request_id
    if errors:
        body["errors"] = errors
    response = JSONResponse(body, status_code=status, media_type=PROBLEM_CONTENT_TYPE)
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _field_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    """Field, code and message only. The offending input value is never echoed (it may be PII)."""
    errors = []
    for item in exc.errors():
        loc = [str(p) for p in item.get("loc", ()) if p not in ("body", "query", "path", "header")]
        kind = str(item.get("type", ""))
        code = "FIELD_REQUIRED" if kind == "missing" else "INVALID_VALUE"
        message = str(item.get("msg", ""))
        # Validators raise ``ValueError("INVALID_AMOUNT: Amount must be ...")`` to set a field code.
        coded = _CODED_MESSAGE.match(message)
        if coded and kind == "value_error":
            code, message = coded.group(1), coded.group(2)
        errors.append({"field": ".".join(loc), "code": code, "message": message})
    return errors


def internal_error_response(request_id: str | None) -> JSONResponse:
    return problem_response(
        500,
        "INTERNAL_ERROR",
        "Internal server error",
        request_id,
        detail="An unexpected error occurred. Quote the request_id when reporting it.",
    )


def install_error_handlers(app: FastAPI) -> None:
    log = structlog.get_logger("errors")

    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            exc.status,
            exc.code,
            exc.title,
            _request_id(request),
            exc.detail,
            exc.errors,
            exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return problem_response(
            422,
            "VALIDATION_ERROR",
            "Validation failed",
            _request_id(request),
            "One or more fields are invalid.",
            _field_errors(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, title = _STATUS_CODES.get(exc.status_code, ("HTTP_ERROR", "HTTP error"))
        return problem_response(
            exc.status_code, code, title, _request_id(request), headers=dict(exc.headers or {})
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Stack trace stays server-side (PRD 17.3); the response carries only the request_id.
        log.error("unhandled_exception", route=request.url.path.split("?")[0], exc_info=exc)
        return internal_error_response(_request_id(request))
