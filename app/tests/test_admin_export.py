"""F-02-003 Admin Audit Log & GDPR Data Export test suite.

AC-01: concessionaire_admin JWT → GET /v1/admin/stats returns 200 with aggregate fields
AC-02: user-scope JWT → GET /v1/admin/stats returns 403
AC-03: unauthenticated → GET /v1/admin/stats returns 401
AC-04: authenticated user → POST /v1/me/export returns 202 with export_id + "processing"
AC-05: GET /v1/me/export/{id} returns 200 with status=ready and download_url after completion
AC-06: GET /v1/me/export/{id} for another user's export → 403
AC-07: export file contains required fields and explicitly excludes spending amounts/OIDC claims
AC-08: gdpr_data_export audit emitted on POST — user_id + timestamp only
AC-09: admin_action audit emitted on GET /v1/admin/stats
"""
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tests.conftest import make_id_token, create_admin_token
from protegopay.db.models import DepositLimit, ExportJob, User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, rsa_private_pem, sub: str = "export-user-001") -> str:
    resp = client.post("/v1/auth/session", json={"id_token": make_id_token(rsa_private_pem, sub=sub)})
    assert resp.status_code == 200, resp.text
    return resp.json()["user_id"]


def _set_admin_cookie(client, test_settings):
    token, _ = create_admin_token("admin-001", test_settings)
    client.cookies.set("pp_session", token)


# ---------------------------------------------------------------------------
# AC-01: concessionaire_admin JWT → 200 with aggregate stats
# ---------------------------------------------------------------------------

def test_admin_stats_with_admin_jwt_returns_200(client, test_settings):
    _set_admin_cookie(client, test_settings)
    resp = client.get("/v1/admin/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "active_users_count" in body
    assert "limits_configured_count" in body
    assert "pauses_active_count" in body
    assert isinstance(body["active_users_count"], int)
    assert isinstance(body["limits_configured_count"], int)
    assert isinstance(body["pauses_active_count"], int)


def test_admin_stats_aggregates_correctly(client, test_settings, db_session):
    # Seed user + limit directly — avoid a user-scope login cookie interfering with admin cookie
    now = datetime.now(timezone.utc)
    user = User(id=str(uuid.uuid4()), external_id_hmac="hmac-admin-test-unique")
    db_session.add(user)
    db_session.commit()
    limit = DepositLimit(user_id=user.id, period="daily", amount_eurocents=5000, created_at=now, updated_at=now)
    db_session.add(limit)
    db_session.commit()

    _set_admin_cookie(client, test_settings)
    resp = client.get("/v1/admin/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_users_count"] >= 1
    assert body["limits_configured_count"] >= 1
    # No individual user data in response
    assert "user_id" not in body
    assert "amount" not in str(body)


# ---------------------------------------------------------------------------
# AC-02: user-scope JWT → GET /v1/admin/stats returns 403
# ---------------------------------------------------------------------------

def test_admin_stats_with_user_jwt_returns_403(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = client.get("/v1/admin/stats")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AC-03: unauthenticated → 401
# ---------------------------------------------------------------------------

def test_admin_stats_unauthenticated_returns_401(client):
    resp = client.get("/v1/admin/stats")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-04: POST /v1/me/export → 202 with export_id and status=processing
# ---------------------------------------------------------------------------

def test_post_export_returns_202(client, rsa_private_pem):
    _login(client, rsa_private_pem)
    resp = client.post("/v1/me/export")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "export_id" in body
    assert body["status"] == "processing"


def test_post_export_unauthenticated_returns_401(client):
    resp = client.post("/v1/me/export")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-05: GET /v1/me/export/{id} → 200 with status=ready and download_url
# ---------------------------------------------------------------------------

def test_get_export_status_ready_with_download_url(client, rsa_private_pem, db_session, test_settings):
    _login(client, rsa_private_pem)

    # Request export — BackgroundTasks run synchronously in TestClient
    post_resp = client.post("/v1/me/export")
    assert post_resp.status_code == 202
    export_id = post_resp.json()["export_id"]

    # TestClient runs background tasks synchronously; job should be ready immediately
    get_resp = client.get(f"/v1/me/export/{export_id}")
    assert get_resp.status_code == 200, get_resp.text
    body = get_resp.json()
    assert body["status"] == "ready"
    assert body["download_url"] is not None
    assert export_id in body["download_url"]
    assert "token=" in body["download_url"]


def test_download_export_file(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    post_resp = client.post("/v1/me/export")
    export_id = post_resp.json()["export_id"]

    status_resp = client.get(f"/v1/me/export/{export_id}")
    download_url = status_resp.json()["download_url"]

    dl_resp = client.get(download_url)
    assert dl_resp.status_code == 200, dl_resp.text
    data = dl_resp.json()
    assert "internal_user_id" in data


# ---------------------------------------------------------------------------
# AC-06: Another user's export_id → 403
# ---------------------------------------------------------------------------

def test_get_export_other_user_returns_403(client, rsa_private_pem, db_session):
    # Create a fake export job owned by user B
    user_b_id = str(uuid.uuid4())
    user_b = User(id=user_b_id, external_id_hmac="hmac-export-userb-unique")
    db_session.add(user_b)
    db_session.commit()

    job = ExportJob(user_id=user_b_id, status="processing")
    db_session.add(job)
    db_session.commit()

    # Log in as user A
    _login(client, rsa_private_pem, sub="user-a-export")
    resp = client.get(f"/v1/me/export/{job.id}")
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# AC-07: Export file content — required fields present, excluded fields absent
# ---------------------------------------------------------------------------

def test_export_file_content(client, rsa_private_pem, db_session, test_settings):
    _login(client, rsa_private_pem)

    post_resp = client.post("/v1/me/export")
    export_id = post_resp.json()["export_id"]

    status_resp = client.get(f"/v1/me/export/{export_id}")
    download_url = status_resp.json()["download_url"]
    data = client.get(download_url).json()

    # Required fields
    assert "internal_user_id" in data
    assert "limit_settings" in data
    assert "alert_thresholds" in data
    assert "pause_records" in data
    assert "audit_events" in data

    # Explicitly excluded: spending amounts — limit_settings has amount but alert_thresholds must not
    for threshold in data["alert_thresholds"]:
        assert "amount_eurocents" not in threshold, "amount_eurocents leaked into threshold export"

    # No OIDC claims
    data_str = str(data)
    assert "export-user-001" not in data_str, "OIDC sub claim leaked into export"
    assert "oidc" not in data_str.lower()


# ---------------------------------------------------------------------------
# AC-08: gdpr_data_export audit emitted on POST — no content
# ---------------------------------------------------------------------------

def test_gdpr_audit_emitted_on_export_request(client, rsa_private_pem):
    _login(client, rsa_private_pem)

    with patch("protegopay.api.v1.export.audit") as mock_audit:
        resp = client.post("/v1/me/export")

    assert resp.status_code == 202
    gdpr_calls = [c for c in mock_audit.call_args_list if c.args[0] == "gdpr_data_export"]
    assert len(gdpr_calls) >= 1

    for c in gdpr_calls:
        # Must not contain export contents
        all_str = str(c.args) + str(c.kwargs)
        assert "limit_settings" not in all_str
        assert "audit_events" not in all_str


# ---------------------------------------------------------------------------
# AC-09: admin_action audit emitted on GET /v1/admin/stats
# ---------------------------------------------------------------------------

def test_admin_action_audit_emitted(client, test_settings):
    _set_admin_cookie(client, test_settings)

    with patch("protegopay.api.v1.admin.audit") as mock_audit:
        resp = client.get("/v1/admin/stats")

    assert resp.status_code == 200
    admin_calls = [c for c in mock_audit.call_args_list if c.args[0] == "admin_action"]
    assert len(admin_calls) >= 1

    for c in admin_calls:
        assert c.args[1] == "success"
        # Must contain admin user_id — not individual user data
        assert "user_id" in c.kwargs
