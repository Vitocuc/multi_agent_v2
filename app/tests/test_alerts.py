"""F-02-001 Spending Alert Notifications test suite.

AC-01: Spending crosses 80% of daily limit → limit_80pct alert created
AC-02: GET /v1/dashboard includes alerts array with 100% limit alert
AC-03: PATCH /v1/alerts/{id}/acknowledge → acknowledged: true, absent from unacked list
AC-04: Acknowledge alert_id belonging to another user → 403
AC-05: POST /v1/alert-thresholds → 200, threshold persisted
AC-06: Spending crosses custom threshold → custom_threshold alert created
AC-07: alert_config_change audit log emitted on threshold create/update/delete — no amount
AC-08: User A's alerts never appear in user B's dashboard or alert list
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from tests.conftest import make_id_token
from protegopay.db.models import (
    AlertRecord, AlertThreshold, DepositLimit, SpendingEvent, User
)
from protegopay.services.alert_evaluator import evaluate_all_alerts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, rsa_private_pem, sub: str = "alert-user-001") -> str:
    resp = client.post("/v1/auth/session", json={"id_token": make_id_token(rsa_private_pem, sub=sub)})
    assert resp.status_code == 200, resp.text
    return resp.json()["user_id"]


def _seed_limit(db_session, user_id: str, period: str, amount: int):
    now = datetime.now(timezone.utc)
    limit = DepositLimit(
        user_id=user_id, period=period, amount_eurocents=amount,
        created_at=now, updated_at=now,
    )
    db_session.add(limit)
    db_session.commit()


def _seed_spending(db_session, user_id: str, amount: int, event_at: datetime | None = None):
    ev = SpendingEvent(
        user_id=user_id,
        deposit_eurocents=amount,
        event_at=event_at or datetime.now(timezone.utc),
    )
    db_session.add(ev)
    db_session.commit()


# ---------------------------------------------------------------------------
# AC-01: Spending at 80% of daily limit → limit_80pct alert created
# ---------------------------------------------------------------------------

def test_evaluator_creates_80pct_alert(db_session):
    """Evaluator creates limit_80pct alert when spending reaches 80% of daily limit."""
    user_id = str(uuid.uuid4())
    user = User(id=user_id, external_id_hmac="hmac-alert-ac01-unique")
    db_session.add(user)
    db_session.commit()

    _seed_limit(db_session, user_id, "daily", 5000)
    # 4001 / 5000 = 80.02% → crosses 80% threshold
    _seed_spending(db_session, user_id, 4001)

    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    alerts = db_session.query(AlertRecord).filter(AlertRecord.user_id == user_id).all()
    types = {a.alert_type for a in alerts}
    assert "limit_80pct" in types
    assert "limit_100pct" not in types

    alert = next(a for a in alerts if a.alert_type == "limit_80pct")
    assert alert.period == "daily"
    assert alert.acknowledged is False


def test_evaluator_creates_100pct_alert(db_session):
    """Evaluator creates limit_100pct alert when spending meets or exceeds daily limit."""
    user_id = str(uuid.uuid4())
    user = User(id=user_id, external_id_hmac="hmac-alert-ac01b-unique")
    db_session.add(user)
    db_session.commit()

    _seed_limit(db_session, user_id, "daily", 5000)
    _seed_spending(db_session, user_id, 5001)

    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    types = {a.alert_type for a in db_session.query(AlertRecord).filter(AlertRecord.user_id == user_id).all()}
    assert "limit_100pct" in types


def test_evaluator_no_alert_below_80pct(db_session):
    """No alert created when spending is below 80% of daily limit."""
    user_id = str(uuid.uuid4())
    user = User(id=user_id, external_id_hmac="hmac-alert-ac01c-unique")
    db_session.add(user)
    db_session.commit()

    _seed_limit(db_session, user_id, "daily", 5000)
    _seed_spending(db_session, user_id, 3999)  # 79.98% — below threshold

    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    count = db_session.query(AlertRecord).filter(AlertRecord.user_id == user_id).count()
    assert count == 0


def test_evaluator_deduplication_no_duplicate_alerts(db_session):
    """Calling evaluate_all_alerts twice does not create duplicate alerts."""
    user_id = str(uuid.uuid4())
    user = User(id=user_id, external_id_hmac="hmac-alert-dedup-unique")
    db_session.add(user)
    db_session.commit()

    _seed_limit(db_session, user_id, "daily", 5000)
    _seed_spending(db_session, user_id, 4500)

    evaluate_all_alerts(user_id, db_session)
    db_session.commit()
    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    count = db_session.query(AlertRecord).filter(
        AlertRecord.user_id == user_id, AlertRecord.alert_type == "limit_80pct"
    ).count()
    assert count == 1


# ---------------------------------------------------------------------------
# AC-02: Dashboard response includes alerts array with 100% limit alert
# ---------------------------------------------------------------------------

def test_dashboard_includes_alerts(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)

    _seed_limit(db_session, user_id, "daily", 5000)
    _seed_spending(db_session, user_id, 5001)
    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    resp = client.get("/v1/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "alerts" in body
    assert isinstance(body["alerts"], list)

    alert_types = {a["alert_type"] for a in body["alerts"]}
    assert "limit_100pct" in alert_types

    # Each alert has required fields
    for a in body["alerts"]:
        assert set(a.keys()) >= {"id", "alert_type", "period", "acknowledged"}


def test_dashboard_alerts_empty_when_none(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = client.get("/v1/dashboard")
    assert resp.status_code == 200
    assert resp.json()["alerts"] == []


# ---------------------------------------------------------------------------
# AC-03: PATCH /v1/alerts/{id}/acknowledge → acknowledged, absent from list
# ---------------------------------------------------------------------------

def test_acknowledge_alert(client, rsa_private_pem, db_session):
    user_id = _login(client, rsa_private_pem)

    _seed_limit(db_session, user_id, "daily", 5000)
    _seed_spending(db_session, user_id, 4500)
    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    alerts = client.get("/v1/alerts").json()
    assert len(alerts) == 1
    alert_id = alerts[0]["id"]

    patch_resp = client.patch(f"/v1/alerts/{alert_id}/acknowledge")
    assert patch_resp.status_code == 200
    assert patch_resp.json()["acknowledged"] is True

    # Should no longer appear in unacknowledged list
    remaining = client.get("/v1/alerts").json()
    assert all(a["id"] != alert_id for a in remaining)

    # Dashboard should also not include it
    dash = client.get("/v1/dashboard").json()
    assert all(a["id"] != alert_id for a in dash["alerts"])


# ---------------------------------------------------------------------------
# AC-04: Acknowledging another user's alert → 403
# ---------------------------------------------------------------------------

def test_acknowledge_other_users_alert_returns_403(client, rsa_private_pem, db_session):
    # Create user B's alert directly in DB
    user_b_id = str(uuid.uuid4())
    user_b = User(id=user_b_id, external_id_hmac="hmac-alert-userb-unique")
    db_session.add(user_b)
    db_session.commit()

    alert_b = AlertRecord(
        user_id=user_b_id, period="daily", alert_type="limit_80pct",
        acknowledged=False, created_at=datetime.now(timezone.utc),
    )
    db_session.add(alert_b)
    db_session.commit()

    # Log in as user A
    _login(client, rsa_private_pem, sub="user-a-alert-isolation")

    resp = client.patch(f"/v1/alerts/{alert_b.id}/acknowledge")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AC-05: POST /v1/alert-thresholds → 200, threshold persisted
# ---------------------------------------------------------------------------

def test_create_threshold_returns_200(client, rsa_private_pem, db_session):
    _login(client, rsa_private_pem)

    resp = client.post("/v1/alert-thresholds", json={"amount_eurocents": 3000, "period": "weekly"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "weekly"
    assert "id" in body
    assert "created_at" in body


def test_create_threshold_invalid_amount_returns_422(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    resp = client.post("/v1/alert-thresholds", json={"amount_eurocents": 0, "period": "daily"})
    assert resp.status_code == 422


def test_create_threshold_unauthenticated_returns_401(client):
    resp = client.post("/v1/alert-thresholds", json={"amount_eurocents": 1000, "period": "daily"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-06: Custom threshold crossed → custom_threshold alert created
# ---------------------------------------------------------------------------

def test_evaluator_creates_custom_threshold_alert(db_session):
    user_id = str(uuid.uuid4())
    user = User(id=user_id, external_id_hmac="hmac-alert-ac06-unique")
    db_session.add(user)
    db_session.commit()

    # Custom threshold at 3000 eurocents for daily
    threshold = AlertThreshold(
        user_id=user_id, period="daily", amount_eurocents=3000,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(threshold)
    db_session.commit()

    _seed_spending(db_session, user_id, 3000)  # exactly at threshold

    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    alert = db_session.query(AlertRecord).filter(
        AlertRecord.user_id == user_id,
        AlertRecord.alert_type == "custom_threshold",
    ).first()
    assert alert is not None
    assert alert.period == "daily"
    assert alert.acknowledged is False


def test_no_custom_threshold_alert_below_threshold(db_session):
    user_id = str(uuid.uuid4())
    user = User(id=user_id, external_id_hmac="hmac-alert-ac06b-unique")
    db_session.add(user)
    db_session.commit()

    threshold = AlertThreshold(
        user_id=user_id, period="daily", amount_eurocents=3000,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(threshold)
    db_session.commit()

    _seed_spending(db_session, user_id, 2999)

    evaluate_all_alerts(user_id, db_session)
    db_session.commit()

    count = db_session.query(AlertRecord).filter(AlertRecord.user_id == user_id).count()
    assert count == 0


# ---------------------------------------------------------------------------
# AC-07: alert_config_change audit emitted on threshold create/delete — no amount
# ---------------------------------------------------------------------------

def test_audit_on_threshold_create_no_amount(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    with patch("protegopay.api.v1.alerts.audit") as mock_audit:
        resp = client.post("/v1/alert-thresholds", json={"amount_eurocents": 5555, "period": "monthly"})

    assert resp.status_code == 200
    config_calls = [c for c in mock_audit.call_args_list if c.args[0] == "alert_config_change"]
    assert len(config_calls) >= 1
    for c in config_calls:
        all_str = str(c.args) + str(c.kwargs)
        assert "5555" not in all_str, "Amount leaked into audit log"
        assert "amount" not in all_str.lower(), "Amount key leaked into audit log"


def test_audit_on_threshold_delete_no_amount(client, rsa_private_pem, db_session):
    _login(client, rsa_private_pem)
    create_resp = client.post("/v1/alert-thresholds", json={"amount_eurocents": 7777, "period": "weekly"})
    threshold_id = create_resp.json()["id"]

    with patch("protegopay.api.v1.alerts.audit") as mock_audit:
        del_resp = client.delete(f"/v1/alert-thresholds/{threshold_id}")

    assert del_resp.status_code == 204
    config_calls = [c for c in mock_audit.call_args_list if c.args[0] == "alert_config_change"]
    assert len(config_calls) >= 1
    for c in config_calls:
        all_str = str(c.args) + str(c.kwargs)
        assert "7777" not in all_str, "Amount leaked into audit log on delete"


# ---------------------------------------------------------------------------
# AC-08: User A's alerts never appear in user B's dashboard or alert list
# ---------------------------------------------------------------------------

def test_alert_ownership_isolation(client, rsa_private_pem, db_session):
    # Log in as user A, create alert
    user_a_id = _login(client, rsa_private_pem, sub="user-a-alerts")
    _seed_limit(db_session, user_a_id, "daily", 5000)
    _seed_spending(db_session, user_a_id, 4500)
    evaluate_all_alerts(user_a_id, db_session)
    db_session.commit()

    # Confirm user A sees their alert
    a_alerts = client.get("/v1/alerts").json()
    assert len(a_alerts) >= 1

    # Create user B with their own alert
    user_b_id = str(uuid.uuid4())
    user_b = User(id=user_b_id, external_id_hmac="hmac-alert-isolation-b-unique")
    db_session.add(user_b)
    db_session.commit()
    b_alert = AlertRecord(
        user_id=user_b_id, period="daily", alert_type="limit_80pct",
        acknowledged=False, created_at=datetime.now(timezone.utc),
    )
    db_session.add(b_alert)
    db_session.commit()

    # Still logged in as user A — must never see user B's alert
    a_alert_ids = {a["id"] for a in client.get("/v1/alerts").json()}
    assert b_alert.id not in a_alert_ids

    dash_alert_ids = {a["id"] for a in client.get("/v1/dashboard").json()["alerts"]}
    assert b_alert.id not in dash_alert_ids
