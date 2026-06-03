"""F-02-002 Reflection Pause test suite.

AC-01: POST /v1/pause with valid duration → 200 with all required fields
AC-02: POST with invalid duration → 422
AC-03: DELETE within 30-min window → 204, pause cancelled
AC-04: DELETE after 30-min window → 409 {"error": "pause_irrevocable"}
AC-05: GET /v1/dashboard with active pause → reduced view (no amounts), pause fields present
AC-06: DELETE another user's pause → 403
AC-07: Unauthenticated POST /v1/pause → 401
AC-08: pause_start audit on activation; pause_end audit on cancellation (no spending data)
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from tests.conftest import make_id_token
from protegopay.db.models import PauseRecord, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, rsa_private_pem, sub: str = "pause-user-001") -> str:
    resp = client.post("/v1/auth/session", json={"id_token": make_id_token(rsa_private_pem, sub=sub)})
    assert resp.status_code == 200, resp.text
    return resp.json()["user_id"]


def _activate(client, duration: str = "24h"):
    return client.post("/v1/pause", json={"duration": duration})


def _cancel(client, pause_id: str):
    return client.delete(f"/v1/pause/{pause_id}")


# ---------------------------------------------------------------------------
# AC-01: POST /v1/pause → 200 with required fields
# ---------------------------------------------------------------------------

def test_activate_pause_returns_200_with_all_fields(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = _activate(client, "24h")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "pause_id" in body
    assert body["duration"] == "24h"
    assert body["status"] == "active"

    starts = datetime.fromisoformat(body["starts_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    revocable = datetime.fromisoformat(body["revocable_until"])

    # expires ~24h after starts
    assert 23 * 3600 < (expires - starts).total_seconds() < 25 * 3600
    # revocable_until = starts + 30 min
    assert 25 * 60 < (revocable - starts).total_seconds() < 35 * 60


def test_activate_1h_pause(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = _activate(client, "1h")
    assert resp.status_code == 200
    body = resp.json()
    starts = datetime.fromisoformat(body["starts_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert 3500 < (expires - starts).total_seconds() < 3700


def test_activate_7d_pause(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = _activate(client, "7d")
    assert resp.status_code == 200
    body = resp.json()
    starts = datetime.fromisoformat(body["starts_at"])
    expires = datetime.fromisoformat(body["expires_at"])
    assert 6 * 24 * 3600 < (expires - starts).total_seconds() < 8 * 24 * 3600


# ---------------------------------------------------------------------------
# AC-02: Invalid duration → 422
# ---------------------------------------------------------------------------

def test_invalid_duration_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    for bad in ("3h", "2d", "1w", "monthly", ""):
        resp = client.post("/v1/pause", json={"duration": bad})
        assert resp.status_code == 422, f"Expected 422 for duration={bad!r}"


# ---------------------------------------------------------------------------
# AC-03: DELETE within revocation window → 204
# ---------------------------------------------------------------------------

def test_cancel_within_window_returns_204(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)

    act_resp = _activate(client, "24h")
    assert act_resp.status_code == 200
    pause_id = act_resp.json()["pause_id"]

    del_resp = _cancel(client, pause_id)
    assert del_resp.status_code == 204

    # Verify status updated in DB
    pause = db_session.query(PauseRecord).filter(PauseRecord.id == pause_id).first()
    assert pause.status == "cancelled"


# ---------------------------------------------------------------------------
# AC-04: DELETE after revocation window → 409 pause_irrevocable
# ---------------------------------------------------------------------------

def test_cancel_after_window_returns_409(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)

    act_resp = _activate(client, "24h")
    pause_id = act_resp.json()["pause_id"]

    # Backdate revocable_until to make it irrevocable
    pause = db_session.query(PauseRecord).filter(PauseRecord.id == pause_id).first()
    pause.revocable_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    del_resp = _cancel(client, pause_id)
    assert del_resp.status_code == 409
    assert del_resp.json()["detail"]["error"] == "pause_irrevocable"

    # Pause must still be active
    db_session.refresh(pause)
    assert pause.status == "active"


# ---------------------------------------------------------------------------
# AC-05: Dashboard during active pause → reduced view
# ---------------------------------------------------------------------------

def test_dashboard_during_pause_returns_reduced_view(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    _activate(client, "1h")

    resp = client.get("/v1/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["pause_active"] is True
    assert "pause_expires_at" in body
    assert body["message"] == "You have an active reflection pause."

    # Spending amounts must be absent (None or missing)
    assert body.get("total_deposit_eurocents") is None
    assert body.get("session_count") is None


def test_dashboard_without_pause_returns_full_view(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = client.get("/v1/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pause_active"] is False
    assert body["total_deposit_eurocents"] is not None
    assert body["session_count"] is not None


def test_dashboard_after_cancelled_pause_returns_full_view(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    act_resp = _activate(client, "1h")
    pause_id = act_resp.json()["pause_id"]

    _cancel(client, pause_id)

    resp = client.get("/v1/dashboard")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pause_active"] is False
    assert body["total_deposit_eurocents"] is not None


# ---------------------------------------------------------------------------
# AC-06: DELETE another user's pause → 403
# ---------------------------------------------------------------------------

def test_cancel_other_users_pause_returns_403(client, rsa_private_pem, db_session):
    now = datetime.now(timezone.utc)
    user_b = User(id=str(uuid.uuid4()), external_id_hmac="hmac-pause-userb-unique")
    db_session.add(user_b)
    db_session.commit()

    pause_b = PauseRecord(
        user_id=user_b.id, duration="24h", status="active",
        starts_at=now, expires_at=now + timedelta(hours=24),
        revocable_until=now + timedelta(minutes=30),
    )
    db_session.add(pause_b)
    db_session.commit()

    _login(client, rsa_private_pem, sub="user-a-pause")
    resp = _cancel(client, pause_b.id)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AC-07: Unauthenticated POST → 401
# ---------------------------------------------------------------------------

def test_activate_unauthenticated_returns_401(client):
    resp = _activate(client)
    assert resp.status_code == 401


def test_cancel_unauthenticated_returns_401(client):
    resp = client.delete("/v1/pause/some-id")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-08: pause_start on activation, pause_end on cancellation — no spending data
# ---------------------------------------------------------------------------

def test_pause_start_audit_emitted_no_spending(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    with patch("protegopay.api.v1.pause.audit") as mock_audit:
        resp = _activate(client, "1h")

    assert resp.status_code == 200
    start_calls = [c for c in mock_audit.call_args_list if c.args[0] == "pause_start"]
    assert len(start_calls) >= 1
    for c in start_calls:
        all_str = str(c.args) + str(c.kwargs)
        assert "eurocent" not in all_str.lower()
        assert "amount" not in all_str.lower()


def test_pause_end_audit_emitted_on_cancel(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    act_resp = _activate(client, "1h")
    pause_id = act_resp.json()["pause_id"]

    with patch("protegopay.api.v1.pause.audit") as mock_audit:
        del_resp = _cancel(client, pause_id)

    assert del_resp.status_code == 204
    end_calls = [c for c in mock_audit.call_args_list if c.args[0] == "pause_end"]
    assert len(end_calls) >= 1
