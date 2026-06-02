"""F-01-003 Voluntary Deposit Limit Setup test suite.

AC-01: PUT /v1/limits/daily → 200 with persisted limit record (all 4 fields)
AC-02: PUT with existing limit → upsert updates it, 200
AC-03: amount_eurocents ≤ 0 → 422 {"error": "amount must be a positive integer"}
AC-04: amount_eurocents > 10_000_000 → 422
AC-05: Invalid period value → 422
AC-06: GET /v1/limits → 200 with array of all active limits
AC-07: DELETE /v1/limits/daily → 204 + limit absent from GET
AC-08: Unauthenticated request → 401 for all three endpoints
AC-09: User A's JWT → limit stored under A's UUID; user B cannot read/modify
AC-10: limit_change audit log emitted on create, update, delete — no amount
"""
import uuid
from datetime import datetime
from unittest.mock import patch, call

import pytest

from tests.conftest import make_id_token
from protegopay.db.models import DepositLimit, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, rsa_private_pem, sub: str = "limit-user-001") -> str:
    resp = client.post("/v1/auth/session", json={"id_token": make_id_token(rsa_private_pem, sub=sub)})
    assert resp.status_code == 200, resp.text
    return resp.json()["user_id"]


def _put(client, period: str, amount: int):
    return client.put(f"/v1/limits/{period}", json={"amount_eurocents": amount})


def _get(client):
    return client.get("/v1/limits")


def _delete(client, period: str):
    return client.delete(f"/v1/limits/{period}")


# ---------------------------------------------------------------------------
# AC-01: PUT → 200 with all four fields in response
# ---------------------------------------------------------------------------

def test_put_limit_returns_200_with_all_fields(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    resp = _put(client, "daily", 5000)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["period"] == "daily"
    assert body["amount_eurocents"] == 5000
    # Both timestamps present and valid ISO 8601
    datetime.fromisoformat(body["created_at"])
    datetime.fromisoformat(body["updated_at"])
    # Exactly the four permitted fields
    assert set(body.keys()) == {"period", "amount_eurocents", "created_at", "updated_at"}


# ---------------------------------------------------------------------------
# AC-02: PUT with existing limit → upsert, 200 with updated amount
# ---------------------------------------------------------------------------

def test_put_limit_upserts_existing(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    resp1 = _put(client, "weekly", 1000)
    assert resp1.status_code == 200
    created_at_1 = resp1.json()["created_at"]

    resp2 = _put(client, "weekly", 2500)
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["amount_eurocents"] == 2500
    assert body["period"] == "weekly"
    # created_at must stay the same; updated_at may differ (same-second is acceptable)
    assert body["created_at"] == created_at_1

    # Only one record should exist
    get_resp = _get(client)
    weekly_limits = [l for l in get_resp.json() if l["period"] == "weekly"]
    assert len(weekly_limits) == 1


# ---------------------------------------------------------------------------
# AC-03: amount ≤ 0 → 422 with correct error message
# ---------------------------------------------------------------------------

def test_put_zero_amount_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    for bad_amount in (0, -1, -9999):
        resp = _put(client, "daily", bad_amount)
        assert resp.status_code == 422, f"Expected 422 for amount={bad_amount}"
        body = resp.json()
        assert body.get("detail", {}).get("error") == "amount must be a positive integer", (
            f"Wrong error body for amount={bad_amount}: {body}"
        )


# ---------------------------------------------------------------------------
# AC-04: amount > 10_000_000 → 422
# ---------------------------------------------------------------------------

def test_put_amount_exceeds_max_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    resp = _put(client, "monthly", 10_000_001)
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body


# ---------------------------------------------------------------------------
# AC-05: Invalid period value → 422
# ---------------------------------------------------------------------------

def test_put_invalid_period_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    for bad_period in ("quarterly", "yearly", "hour", "DAILY", ""):
        if bad_period == "":
            continue  # empty string hits a different route, skip
        resp = _put(client, bad_period, 1000)
        assert resp.status_code == 422, f"Expected 422 for period={bad_period!r}"


def test_delete_invalid_period_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = _delete(client, "quarterly")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# AC-06: GET /v1/limits → 200 with array of all active limits
# ---------------------------------------------------------------------------

def test_get_limits_returns_all_active(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    _put(client, "daily", 1000)
    _put(client, "weekly", 5000)
    _put(client, "monthly", 20000)

    resp = _get(client)
    assert resp.status_code == 200
    limits = resp.json()
    assert isinstance(limits, list)
    assert len(limits) == 3

    periods = {lim["period"] for lim in limits}
    assert periods == {"daily", "weekly", "monthly"}


def test_get_limits_empty_returns_empty_array(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = _get(client)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# AC-07: DELETE → 204, limit absent from subsequent GET
# ---------------------------------------------------------------------------

def test_delete_limit_returns_204_and_removes(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    _put(client, "daily", 3000)
    _put(client, "weekly", 7000)

    del_resp = _delete(client, "daily")
    assert del_resp.status_code == 204

    get_resp = _get(client)
    assert get_resp.status_code == 200
    periods = [lim["period"] for lim in get_resp.json()]
    assert "daily" not in periods
    assert "weekly" in periods


def test_delete_nonexistent_limit_returns_404(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = _delete(client, "monthly")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# AC-08: Unauthenticated requests → 401 on all endpoints
# ---------------------------------------------------------------------------

def test_unauthenticated_put_returns_401(client):
    resp = _put(client, "daily", 1000)
    assert resp.status_code == 401


def test_unauthenticated_get_returns_401(client):
    resp = _get(client)
    assert resp.status_code == 401


def test_unauthenticated_delete_returns_401(client):
    resp = _delete(client, "daily")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-09: User A's JWT → stored under A's UUID; user B cannot read/modify
# ---------------------------------------------------------------------------

def test_limits_ownership_isolation(client, rsa_private_pem, db_session):
    # Log in as user A, set a limit
    user_a_id = _login(client, rsa_private_pem, sub="user-a-limits")
    resp = _put(client, "daily", 9999)
    assert resp.status_code == 200

    # Verify stored under user A's UUID
    stored = db_session.query(DepositLimit).filter(DepositLimit.user_id == user_a_id).all()
    assert len(stored) == 1
    assert stored[0].amount_eurocents == 9999

    # Create user B record directly; seed a limit under B
    user_b_id = str(uuid.uuid4())
    user_b = User(id=user_b_id, external_id_hmac="hmac-user-b-limits-unique")
    db_session.add(user_b)
    from protegopay.db.models import DepositLimit as DL
    b_limit = DL(user_id=user_b_id, period="daily", amount_eurocents=55555,
                 created_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                 updated_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
    db_session.add(b_limit)
    db_session.commit()

    # Still authenticated as user A — GET must return only A's limits
    get_resp = _get(client)
    assert get_resp.status_code == 200
    amounts = [lim["amount_eurocents"] for lim in get_resp.json()]
    assert 9999 in amounts
    assert 55555 not in amounts


# ---------------------------------------------------------------------------
# AC-10: limit_change audit log on create, update, delete — no amount
# ---------------------------------------------------------------------------

def test_audit_emitted_on_create_no_amount(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    with patch("protegopay.api.v1.limits.audit") as mock_audit:
        resp = _put(client, "daily", 1234)

    assert resp.status_code == 200
    limit_change_calls = [c for c in mock_audit.call_args_list if c.args[0] == "limit_change"]
    assert len(limit_change_calls) >= 1
    for c in limit_change_calls:
        all_str = str(c.args) + str(c.kwargs)
        assert "1234" not in all_str, "Amount leaked into audit log"
        assert "amount" not in all_str.lower(), "Amount key leaked into audit log"


def test_audit_emitted_on_update_no_amount(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    _put(client, "weekly", 500)

    with patch("protegopay.api.v1.limits.audit") as mock_audit:
        resp = _put(client, "weekly", 750)

    assert resp.status_code == 200
    limit_change_calls = [c for c in mock_audit.call_args_list if c.args[0] == "limit_change"]
    assert len(limit_change_calls) >= 1
    for c in limit_change_calls:
        all_str = str(c.args) + str(c.kwargs)
        assert "750" not in all_str, "Amount leaked into audit log on update"


def test_audit_emitted_on_delete_no_amount(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    _put(client, "monthly", 8000)

    with patch("protegopay.api.v1.limits.audit") as mock_audit:
        resp = _delete(client, "monthly")

    assert resp.status_code == 204
    limit_change_calls = [c for c in mock_audit.call_args_list if c.args[0] == "limit_change"]
    assert len(limit_change_calls) >= 1
    for c in limit_change_calls:
        all_str = str(c.args) + str(c.kwargs)
        assert "8000" not in all_str, "Amount leaked into audit log on delete"
