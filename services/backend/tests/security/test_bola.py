"""BOLA/IDOR suite (PRD 17.1, 21.2). Routes are discovered from the OpenAPI schema, so a new
endpoint with an id in its path fails here until it is given a victim resource and a body."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.conftest import API, signup
from tests.integration.test_imports_api import preview
from tests.integration.test_transactions_api import make

pytestmark = pytest.mark.integration

YESTERDAY = (dt.date.today() - dt.timedelta(days=2)).isoformat()
IDEM = {"Idempotency-Key": "bola-key-" + "0" * 8}

# Endpoints that are public on purpose (no bearer token needed).
PUBLIC_PREFIXES = ("/health", "/ready", "/docs", "/redoc", "/openapi.json", "/api/v1/auth/")


def _victim_transaction(client: TestClient, headers: dict[str, str]) -> str:
    return str(make(client, headers, description="Victim private purchase")["id"])


def _victim_import(client: TestClient, headers: dict[str, str]) -> str:
    return str(
        preview(client, headers, f"{YESTERDAY},Victim private purchase,4242,expense,,,,")[
            "import_id"
        ]
    )


def _victim_rule(client: TestClient, headers: dict[str, str]) -> str:
    """Changing a category on a merchant with a key creates a rule (FR-03.08)."""
    tx = make(client, headers, description="Victim private purchase")
    r = client.patch(
        f"{API}/transactions/{tx['id']}", json={"category": "groceries"}, headers=headers
    )
    assert r.status_code == 200, r.text
    rules = client.get(f"{API}/merchant-rules", headers=headers).json()["items"]
    assert len(rules) == 1
    return str(rules[0]["id"])


def _victim_budget(client: TestClient, headers: dict[str, str]) -> str:
    r = client.post(
        f"{API}/budgets", json={"category": "groceries", "limit_amount": "100"}, headers=headers
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _victim_notification(client: TestClient, headers: dict[str, str]) -> str:
    """Spending past the victim's budget creates a notification (FR-05.05)."""
    make(client, headers, amount="500", category="groceries")
    items = client.get(f"{API}/notifications", headers=headers).json()["items"]
    assert items
    return str(items[0]["id"])


# Path parameter name -> how to create a resource of the victim that it can point to.
RESOURCES: dict[str, Callable[[TestClient, dict[str, str]], str]] = {
    "transaction_id": _victim_transaction,
    "import_id": _victim_import,
    "rule_id": _victim_rule,
    "budget_id": _victim_budget,
    "notification_id": _victim_notification,
}

# Minimal valid bodies, so a 404 can only come from ownership and never from validation.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/api/v1/transactions/{transaction_id}"): {"notes": "attacker was here"},
    ("POST", "/api/v1/transactions/imports/{import_id}/commit"): {"mode": "skip_invalid"},
    ("PATCH", "/api/v1/merchant-rules/{rule_id}"): {"category": "transportation"},
    ("PATCH", "/api/v1/budgets/{budget_id}"): {"limit_amount": "1.00"},
}


def discover(client: TestClient) -> list[tuple[str, str, list[str]]]:
    """(METHOD, path template, path params) for every operation that has a path parameter."""
    found = []
    for path, ops in client.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        params = [p for p in _params(path)]
        if not params:
            continue
        for method in ops:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                found.append((method.upper(), path, params))
    return found


def _params(path: str) -> list[str]:
    return [seg[1:-1] for seg in path.split("/") if seg.startswith("{") and seg.endswith("}")]


def all_operations(client: TestClient) -> list[tuple[str, str]]:
    out = []
    for path, ops in client.app.openapi()["paths"].items():  # type: ignore[attr-defined]
        for method in ops:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                out.append((method.upper(), path))
    return out


def call(
    client: TestClient, method: str, template: str, ids: dict[str, str], headers: dict[str, str]
) -> Any:
    url = template.format(**ids)
    body = BODIES.get((method, template), {} if method in {"POST", "PATCH", "PUT"} else None)
    return client.request(method, url, json=body, headers={**headers, **IDEM})


def shape(response: Any) -> tuple[int, str, str | None]:
    body = response.json() if response.content else {}
    return response.status_code, body.get("code", ""), body.get("detail")


def test_17_1_every_route_with_an_id_is_covered_by_this_suite(client: TestClient) -> None:
    ops = discover(client)
    assert ops, "no routes with path parameters were discovered"
    uncovered = {(m, p, x) for m, p, params in ops for x in params if x not in RESOURCES}
    assert (
        not uncovered
    ), f"add a victim resource factory (RESOURCES) and a body (BODIES) for: {sorted(uncovered)}"
    # Anything with an {id}-like parameter must be a known resource, never a free-form string.
    seen = {x for _, _, params in ops for x in params}
    assert {"transaction_id", "import_id", "rule_id", "budget_id", "notification_id"} <= seen


def test_every_endpoint_with_id_returns_404_for_other_user(
    client: TestClient, engine: Engine
) -> None:
    victim, intruder = signup(client), signup(client)
    ids = {name: factory(client, victim) for name, factory in RESOURCES.items()}
    missing = {name: str(uuid.uuid4()) for name in RESOURCES}
    checked = 0
    for method, template, params in discover(client):
        foreign = call(client, method, template, {p: ids[p] for p in params}, intruder)
        absent = call(client, method, template, {p: missing[p] for p in params}, intruder)
        assert foreign.status_code == 404, f"{method} {template}: {foreign.status_code}"
        # Indistinguishable from a resource that does not exist (no existence oracle).
        assert shape(foreign) == shape(absent), f"{method} {template} leaks existence"
        assert ids[params[0]] not in foreign.text
        checked += 1
    assert checked >= 11

    # Nothing the intruder tried changed the victim's data.
    tx = client.get(f"{API}/transactions/{ids['transaction_id']}", headers=victim)
    assert tx.status_code == 200 and tx.json()["version"] == 1 and tx.json()["notes"] is None
    rules = client.get(f"{API}/merchant-rules", headers=victim).json()["items"]
    assert [(r["id"], r["category"]["slug"]) for r in rules] == [(ids["rule_id"], "groceries")]
    imp = client.get(f"{API}/transactions/imports/{ids['import_id']}", headers=victim).json()
    assert imp["status"] == "previewed" and imp["summary"]["row_count"] == 1
    budget = client.get(f"{API}/budgets/{ids['budget_id']}", headers=victim).json()
    assert budget["limit_amount"] == "100.00"  # the intruder's PATCH to 1.00 did not apply
    unread = client.get(f"{API}/notifications?unread_only=true", headers=victim).json()["items"]
    assert ids["notification_id"] in {n["id"] for n in unread}  # still unread
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM transactions WHERE source = 'csv'")
            ).scalar_one()
            == 0
        )


def test_every_endpoint_with_id_still_works_for_the_owner(client: TestClient) -> None:
    """Guards the guard: the suite's requests are valid, so a 404 above means ownership."""
    owner = signup(client)
    ids = {name: factory(client, owner) for name, factory in RESOURCES.items()}
    reads = [(m, p, ps) for m, p, ps in discover(client) if m == "GET"]
    assert reads
    for method, template, params in reads:
        r = call(client, method, template, {x: ids[x] for x in params}, owner)
        assert r.status_code == 200, f"{method} {template}: {r.status_code}"


def test_17_1_ids_inside_request_bodies_are_checked_too(client: TestClient, engine: Engine) -> None:
    victim, intruder = signup(client), signup(client)
    mine = _victim_transaction(client, intruder)
    theirs = _victim_transaction(client, victim)
    for path, body in (
        ("/transactions/bulk-delete", {"ids": [mine, theirs]}),
        ("/transactions/bulk-categorize", {"ids": [mine, theirs], "category": "uncategorized"}),
    ):
        r = client.post(f"{API}{path}", json=body, headers={**intruder, **IDEM})
        assert r.status_code == 404, path
    # Atomic: the intruder's own row survived the failed bulk delete as well.
    assert client.get(f"{API}/transactions/{mine}", headers=intruder).status_code == 200
    assert client.get(f"{API}/transactions/{theirs}", headers=victim).status_code == 200
    # Category references cannot reach into another user's data either (categories are global,
    # a foreign transaction id as a category is just an unknown category).
    r = client.post(
        f"{API}/transactions",
        json={
            "transaction_type": "expense",
            "amount": "1000",
            "description": "x",
            "transaction_date": YESTERDAY,
            "category": theirs,
        },
        headers={**intruder, **IDEM},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "UNKNOWN_CATEGORY"


def test_17_1_lists_counts_and_searches_never_include_other_users_rows(client: TestClient) -> None:
    victim, intruder = signup(client), signup(client)
    secret = _victim_transaction(client, victim)
    _victim_import(client, victim)
    for query in (
        "",
        "?q=Victim",
        "?q=private",
        "?sort=amount",
        "?min_amount=1&max_amount=999999999",
        "?possible_duplicate=true",
        "?category_status=needs_review",
        f"?date_from={dt.date.today() - dt.timedelta(days=30)}",
    ):
        page = client.get(f"{API}/transactions{query}", headers=intruder)
        assert page.status_code == 200 and page.json()["items"] == [], query
        assert secret not in page.text
        assert client.get(f"{API}/transactions/count{query}", headers=intruder).json() == {
            "count": 0
        }


def test_17_1_a_cursor_from_another_user_is_rejected(client: TestClient) -> None:
    victim, intruder = signup(client), signup(client)
    for i in range(3):
        make(client, victim, description=f"Victim {i}", amount=str(1000 + i))
    page = client.get(f"{API}/transactions?limit=1", headers=victim).json()
    assert page["next_cursor"]
    r = client.get(f"{API}/transactions?cursor={page['next_cursor']}", headers=intruder)
    assert r.status_code == 400 and r.json()["code"] == "INVALID_CURSOR"
    imp = _victim_import(client, victim)
    rows = [f"{YESTERDAY},Item {i},{i + 1},expense,,,," for i in range(600)]
    big = preview(client, victim, *rows)
    assert big["next_cursor"]
    r = client.get(
        f"{API}/transactions/imports/{big['import_id']}",
        params={"cursor": big["next_cursor"]},
        headers=intruder,
    )
    assert r.status_code == 404  # the import is not theirs, whatever the cursor says
    del imp


def test_17_1_every_protected_endpoint_requires_authentication(client: TestClient) -> None:
    ops = all_operations(client)
    protected = [(m, p) for m, p in ops if not p.startswith(PUBLIC_PREFIXES)]
    assert len(protected) >= 15
    for method, template in protected:
        url = template.format(**{x: str(uuid.uuid4()) for x in _params(template)})
        r = client.request(
            method, url, json={} if method in {"POST", "PATCH", "PUT"} else None, headers=IDEM
        )
        assert r.status_code == 401, f"{method} {template} is reachable without a token"
        bad = client.request(
            method,
            url,
            json={} if method in {"POST", "PATCH", "PUT"} else None,
            headers={**IDEM, "Authorization": "Bearer not.a.token"},
        )
        assert bad.status_code == 401, f"{method} {template} accepts a garbage token"


def test_17_1_a_deleted_users_token_stops_working(client: TestClient) -> None:
    """Tokens outlive the account for up to 15 minutes; they must not resolve to a user."""
    from tests.integration.test_auth_api import PASSWORD  # noqa: PLC0415

    email = f"gone-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        f"{API}/auth/register", json={"email": email, "password": PASSWORD, "display_name": "G"}
    )
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    tx = _victim_transaction(client, headers)
    gone = client.request(
        "DELETE",
        f"{API}/users/me",
        json={"password": PASSWORD, "confirm": "DELETE"},
        headers=headers,
    )
    assert gone.status_code in (200, 204), gone.text
    assert client.get(f"{API}/transactions/{tx}", headers=headers).status_code == 401
    assert client.get(f"{API}/transactions", headers=headers).status_code == 401
