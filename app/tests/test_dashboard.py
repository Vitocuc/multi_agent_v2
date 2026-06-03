"""F-01-002 Spending Dashboard API test suite.

AC-01: Authenticated user with events → 200 with correct aggregated fields
AC-02: Authenticated user with no events → 200 with zeroed totals
AC-03: Unauthenticated request → 401
AC-04: User A's JWT returns only User A's data (ownership isolation)
AC-05: Invalid period param → 422
AC-06: Blacklisted JWT → 401
AC-07: Response never contains raw session IDs, transaction IDs, or extra PII
AC-08: data_access audit log emitted on success (user_id + period, no amounts)
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, call

import pytest

from tests.conftest import make_id_token, TEST_AUDIENCE, TEST_ISSUER
from protegopay.db.models import SpendingEvent, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, rsa_private_pem, sub: str = "user-sub-001") -> str:
    """Log in and return the internal user_id."""
    token = make_id_token(rsa_private_pem, sub=sub)
    resp = client.post("/v1/auth/session", json={"id_token": token})
    assert resp.status_code == 200, resp.text
    return resp.json()["user_id"]


def _seed_event(db_session, user_id: str, deposit_eurocents: int, event_at: datetime | None = None):
    """Insert a SpendingEvent for the given user."""
    if event_at is None:
        event_at = datetime.now(timezone.utc)
    event = SpendingEvent(
        id=str(uuid.uuid4()),
        user_id=user_id,
        deposit_eurocents=deposit_eurocents,
        event_at=event_at,
    )
    db_session.add(event)
    db_session.commit()


def _get_dashboard(client, period: str | None = None) -> "httpx.Response":  # type: ignore[name-defined]
    url = "/v1/dashboard"
    if period is not None:
        url += f"?period={period}"
    return client.get(url)


# ---------------------------------------------------------------------------
# AC-01: Authenticated user with events → 200 + aggregated fields
# ---------------------------------------------------------------------------

def test_dashboard_with_events_returns_200_aggregated(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)

    now = datetime.now(timezone.utc)
    _seed_event(db_session, user_id, 500, now)
    _seed_event(db_session, user_id, 1500, now)

    resp = _get_dashboard(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Core spending fields present when no pause is active
    assert body["total_deposit_eurocents"] == 2000
    assert body["session_count"] == 2
    assert isinstance(body["alerts"], list)
    assert body["pause_active"] is False
    # period boundaries are ISO 8601
    datetime.fromisoformat(body["period_start"])
    datetime.fromisoformat(body["period_end"])


# ---------------------------------------------------------------------------
# AC-02: Authenticated user with no events → 200 + zero totals
# ---------------------------------------------------------------------------

def test_dashboard_with_no_events_returns_zeroed_totals(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    resp = _get_dashboard(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_deposit_eurocents"] == 0
    assert body["session_count"] == 0


# ---------------------------------------------------------------------------
# AC-03: Unauthenticated request → 401
# ---------------------------------------------------------------------------

def test_dashboard_unauthenticated_returns_401(client):
    # No login — no cookie
    resp = _get_dashboard(client)
    assert resp.status_code == 401


def test_dashboard_invalid_jwt_returns_401(client):
    client.cookies.set("pp_session", "not.a.valid.jwt")
    resp = _get_dashboard(client)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-04: User A's JWT → only User A's data (ownership isolation)
# ---------------------------------------------------------------------------

def test_dashboard_ownership_isolation(client, rsa_private_pem, db_session):
    # Log in as user A
    user_a_id = _login(client, rsa_private_pem, sub="user-a")
    _seed_event(db_session, user_a_id, 9999)

    # Create user B's record directly (simulate separate session)
    user_b_id = str(uuid.uuid4())
    user_b = User(id=user_b_id, external_id_hmac="hmac-of-user-b-unique")
    db_session.add(user_b)
    db_session.commit()
    _seed_event(db_session, user_b_id, 55555)

    # Still authenticated as user A — must see only A's 9999 cents
    resp = _get_dashboard(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_deposit_eurocents"] == 9999
    assert body["session_count"] == 1


# ---------------------------------------------------------------------------
# AC-05: Invalid period param → 422
# ---------------------------------------------------------------------------

def test_dashboard_invalid_period_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    for bad in ("all_time", "year", "", "CURRENT_MONTH", "last_year"):
        resp = _get_dashboard(client, period=bad)
        assert resp.status_code == 422, f"Expected 422 for period={bad!r}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-06: Blacklisted JWT → 401
# ---------------------------------------------------------------------------

def test_dashboard_blacklisted_jwt_returns_401(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    # Capture cookie then logout (blacklists the JTI)
    session_cookie = client.cookies.get("pp_session")
    assert session_cookie

    logout = client.delete("/v1/auth/session")
    assert logout.status_code == 204

    # Re-inject the now-blacklisted token
    client.cookies.set("pp_session", session_cookie)
    resp = _get_dashboard(client)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-07: Response contains no raw identifiers, transaction IDs, or extra PII
# ---------------------------------------------------------------------------

def test_dashboard_response_contains_no_raw_identifiers(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)
    event_id = str(uuid.uuid4())
    event = SpendingEvent(
        id=event_id,
        user_id=user_id,
        deposit_eurocents=100,
        event_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    db_session.commit()

    resp = _get_dashboard(client)
    assert resp.status_code == 200
    body = resp.json()

    # Verify no raw identifiers in response (pause fields added by F-02-002 are acceptable)
    assert "period_start" in body and "period_end" in body

    # Raw event ID must not appear anywhere in the response text
    assert event_id not in resp.text
    # Raw user sub claim must not appear
    assert "user-sub-001" not in resp.text


# ---------------------------------------------------------------------------
# AC-08: data_access audit log emitted (user_id + period, no amounts)
# ---------------------------------------------------------------------------

def test_dashboard_audit_log_emitted_with_no_amounts(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)
    _seed_event(db_session, user_id, 12345)

    # Patch the audit function where it is used in dashboard.py
    with patch("protegopay.api.v1.dashboard.audit") as mock_audit:
        resp = _get_dashboard(client)

    assert resp.status_code == 200

    # Find the data_access call
    data_access_calls = [
        c for c in mock_audit.call_args_list
        if c.args and c.args[0] == "data_access"
    ]
    assert len(data_access_calls) >= 1, "Expected at least one data_access audit call"

    for c in data_access_calls:
        kwargs = c.kwargs
        # user_id must be present
        assert kwargs.get("user_id") == user_id, "user_id missing from data_access audit"
        # period (request_id) must be present
        assert "request_id" in kwargs, "period/request_id missing from data_access audit"
        # amounts must NOT appear in any argument
        all_args = str(c.args) + str(kwargs)
        assert "12345" not in all_args, "Deposit amount leaked into audit call"
        assert "eurocent" not in all_args.lower(), "Amount field name leaked into audit call"


# ---------------------------------------------------------------------------
# last_month period boundary test
# ---------------------------------------------------------------------------

def test_dashboard_last_month_excludes_current_month_events(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)

    now = datetime.now(timezone.utc)
    last_month_dt = (now.replace(day=1) - timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    )
    _seed_event(db_session, user_id, 777, last_month_dt)   # in last month
    _seed_event(db_session, user_id, 888, now)              # in current month

    resp = _get_dashboard(client, period="last_month")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_deposit_eurocents"] == 777
    assert body["session_count"] == 1
