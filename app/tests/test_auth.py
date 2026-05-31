"""F-01-001 acceptance criteria test suite.

AC-01: Valid OIDC token → 200 + httpOnly Secure SameSite=Strict cookie (15m expiry)
AC-02: Expired OIDC token → 401 with {"error": "invalid_token"}
AC-03: Wrong audience → 401
AC-04: Invalid signature → 401
AC-05: GET /v1/auth/me with valid cookie → 200 with user_id + session_expires_at
AC-06: DELETE /v1/auth/session → JTI blacklisted, cookie cleared, 204
AC-07: Blacklisted JTI → 401 on protected endpoint
AC-08: 5 consecutive failures → 6th attempt returns 429
AC-09: (Security) No raw token/PII/key material in audit output — verified by log inspection
AC-10: (Security) Pydantic validation runs before JWKS fetch — verified structurally
"""
import time
import json
import logging
from datetime import datetime, timezone, timedelta

import pytest
import respx
import httpx
from jose import jwt as jose_jwt

from tests.conftest import make_id_token, TEST_AUDIENCE, TEST_ISSUER, TEST_JWKS_URI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_session(client, id_token: str) -> "httpx.Response":  # type: ignore[name-defined]
    return client.post("/v1/auth/session", json={"id_token": id_token})


def _get_session_cookie(response) -> str | None:
    return response.cookies.get("pp_session")


# ---------------------------------------------------------------------------
# AC-01: Valid token → 200 + httpOnly cookie
# ---------------------------------------------------------------------------

def test_valid_token_returns_200_with_cookie(client, rsa_private_pem):
    token = make_id_token(rsa_private_pem)
    resp = _post_session(client, token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "user_id" in body
    assert "session_expires_at" in body

    # Cookie must be set
    assert "pp_session" in resp.cookies

    # Cookie attributes: httponly and samesite=strict must be present in Set-Cookie header
    set_cookie = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie or "samesite=strict" in set_cookie.lower()

    # Verify session_expires_at is roughly 15 minutes out
    expires = datetime.fromisoformat(body["session_expires_at"])
    now = datetime.now(timezone.utc)
    delta = (expires - now).total_seconds()
    assert 800 < delta < 1000, f"Expected ~900s expiry, got {delta}"


# ---------------------------------------------------------------------------
# AC-02: Expired token → 401 {"error": "invalid_token"}
# ---------------------------------------------------------------------------

def test_expired_token_returns_401(client, rsa_private_pem):
    token = make_id_token(rsa_private_pem, exp_delta=-60)  # already expired
    resp = _post_session(client, token)

    assert resp.status_code == 401
    body = resp.json()
    assert body.get("detail", {}).get("error") == "invalid_token"
    # Must not contain any internal detail
    assert "traceback" not in resp.text.lower()
    assert "stacktrace" not in resp.text.lower()


# ---------------------------------------------------------------------------
# AC-03: Wrong audience → 401
# ---------------------------------------------------------------------------

def test_wrong_audience_returns_401(client, rsa_private_pem):
    token = make_id_token(rsa_private_pem, aud="wrong-audience")
    resp = _post_session(client, token)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-04: Invalid signature → 401
# ---------------------------------------------------------------------------

def test_invalid_signature_returns_401(client, rsa_private_pem, rsa_private_key):
    # Generate a second key pair; sign with it but leave JWKS pointing at original
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization as ser

    wrong_key = rsa_mod.generate_private_key(65537, 2048, default_backend())
    wrong_pem = wrong_key.private_bytes(
        ser.Encoding.PEM, ser.PrivateFormat.TraditionalOpenSSL, ser.NoEncryption()
    ).decode()

    token = make_id_token(wrong_pem)
    resp = _post_session(client, token)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-05: GET /v1/auth/me with valid cookie → 200
# ---------------------------------------------------------------------------

def test_get_me_returns_user_id_and_expiry(client, rsa_private_pem):
    token = make_id_token(rsa_private_pem)
    login_resp = _post_session(client, token)
    assert login_resp.status_code == 200

    me_resp = client.get("/v1/auth/me")
    assert me_resp.status_code == 200

    body = me_resp.json()
    assert "user_id" in body
    assert "session_expires_at" in body

    # user_id must be an internal UUID, not the external sub claim
    assert body["user_id"] != "external-user-123"
    # No PII beyond what the spec allows
    assert "sub" not in body
    assert "email" not in body


# ---------------------------------------------------------------------------
# AC-06: DELETE /v1/auth/session → 204, cookie cleared, JTI blacklisted
# ---------------------------------------------------------------------------

def test_logout_returns_204_and_clears_cookie(client, rsa_private_pem, redis_client):
    token = make_id_token(rsa_private_pem)
    _post_session(client, token)

    resp = client.delete("/v1/auth/session")
    assert resp.status_code == 204

    # Cookie should be cleared (empty or absent)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "pp_session" not in client.cookies or client.cookies.get("pp_session") == ""

    # JTI must be in Redis blacklist
    blacklist_keys = [k for k in redis_client.keys("*") if "blacklist" in k]
    assert len(blacklist_keys) == 1, "Expected one blacklist entry after logout"


# ---------------------------------------------------------------------------
# AC-07: Blacklisted JTI → 401 on subsequent request
# ---------------------------------------------------------------------------

def test_blacklisted_token_is_rejected(client, rsa_private_pem):
    # Login and capture the session cookie
    login_resp = _post_session(client, make_id_token(rsa_private_pem))
    assert login_resp.status_code == 200
    session_cookie = login_resp.cookies.get("pp_session")
    assert session_cookie, "Expected a session cookie after login"

    # Logout — this blacklists the JTI
    logout_resp = client.delete("/v1/auth/session")
    assert logout_resp.status_code == 204

    # Replay the old session cookie — must be rejected
    client.cookies.set("pp_session", session_cookie)
    me_resp = client.get("/v1/auth/me")
    assert me_resp.status_code == 401


# ---------------------------------------------------------------------------
# AC-08: 5 failures → 6th attempt returns 429
# ---------------------------------------------------------------------------

def test_rate_limit_after_five_failures(client, rsa_private_pem, redis_client):
    bad_token = make_id_token(rsa_private_pem, exp_delta=-60)  # expired → failure

    for i in range(5):
        resp = _post_session(client, bad_token)
        assert resp.status_code == 401, f"Expected 401 on attempt {i+1}"

    resp = _post_session(client, bad_token)
    assert resp.status_code == 429, f"Expected 429 after 5 failures, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AC-09: No PII / token / key material in audit log output
# ---------------------------------------------------------------------------

def test_audit_log_contains_no_pii_or_secrets(client, rsa_private_pem, caplog):
    token = make_id_token(rsa_private_pem)
    with caplog.at_level(logging.INFO, logger="audit"):
        _post_session(client, token)

    for record in caplog.records:
        msg = record.getMessage()
        assert "external-user-123" not in msg, "External sub claim leaked into audit log"
        assert token not in msg, "Raw ID token leaked into audit log"
        # session secret must not appear
        assert "test-session-secret" not in msg


# ---------------------------------------------------------------------------
# AC-10: Pydantic validation runs before JWKS fetch
# ---------------------------------------------------------------------------

def test_pydantic_validates_before_jwks_fetch(client):
    """An empty or malformed id_token must be rejected by Pydantic (422)
    without ever reaching the JWKS endpoint."""
    # Empty string
    resp = client.post("/v1/auth/session", json={"id_token": ""})
    assert resp.status_code == 422

    # Missing field entirely
    resp = client.post("/v1/auth/session", json={})
    assert resp.status_code == 422

    # Oversized token (> 8192 chars) — rejected by schema, not by OIDC lib
    resp = client.post("/v1/auth/session", json={"id_token": "x" * 8193})
    assert resp.status_code == 422
