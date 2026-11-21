"""``python -m app.smoke``: post-deploy smoke test against a running backend (PRD 19.5).

Steps: ``/healthz``, log in as the demo user (registering it first if it does not exist yet, so
the first deploy needs no manual seeding), create one transaction, delete it. The transaction
is removed even if a later step fails. Output names steps and status codes only: never tokens,
passwords or transaction contents (PRD 17.3). Exit code 0 means all steps passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import uuid

import httpx

DESCRIPTION = "smoke test"  # never matches a real merchant; the row is deleted straight away


class SmokeFailure(Exception):
    """A step failed; the message names the step and the status code only."""


def _check(step: str, response: httpx.Response, expected: int) -> httpx.Response:
    if response.status_code != expected:
        raise SmokeFailure(f"{step}: expected {expected}, got {response.status_code}")
    print(f"ok  {step} ({response.status_code})")
    return response


def run(
    base_url: str,
    email: str,
    password: str,
    transport: httpx.BaseTransport | None = None,
    today: dt.date | None = None,
) -> None:
    """Raise ``SmokeFailure`` on the first failed step."""
    day = (today or dt.date.today()).isoformat()
    try:
        with httpx.Client(base_url=base_url, timeout=30, transport=transport) as client:
            _check("healthz", client.get("/healthz"), 200)
            credentials = {"email": email, "password": password}
            login = client.post("/api/v1/auth/login", json=credentials)
            if login.status_code == 401:
                _check(
                    "register demo user",
                    client.post(
                        "/api/v1/auth/register", json={**credentials, "display_name": "Demo"}
                    ),
                    201,
                )
                login = client.post("/api/v1/auth/login", json=credentials)
            _check("login", login, 200)
            client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
            created = _check(
                "create transaction",
                client.post(
                    "/api/v1/transactions",
                    json={
                        "transaction_type": "expense",
                        "amount": "1000.00",
                        "description": DESCRIPTION,
                        "transaction_date": day,
                    },
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                ),
                201,
            )
            transaction_id = created.json()["id"]
            try:
                fetched = client.get(f"/api/v1/transactions/{transaction_id}")
                _check("read transaction", fetched, 200)
            finally:
                _check(
                    "delete transaction",
                    client.delete(f"/api/v1/transactions/{transaction_id}"),
                    204,
                )
    except httpx.HTTPError as exc:
        raise SmokeFailure(f"request failed: {type(exc).__name__}") from exc
    except (KeyError, ValueError) as exc:
        raise SmokeFailure("unexpected response body") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.smoke")
    parser.add_argument("--base-url", default=os.environ.get("SMOKE_BASE_URL"))
    parser.add_argument("--email", default=os.environ.get("DEMO_USER_EMAIL", "demo@example.com"))
    args = parser.parse_args(argv)
    password = os.environ.get("DEMO_USER_PASSWORD")
    if not args.base_url or not password:
        print("SMOKE_BASE_URL (or --base-url) and DEMO_USER_PASSWORD are required", file=sys.stderr)
        return 2
    try:
        run(args.base_url, args.email, password)
    except SmokeFailure as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
