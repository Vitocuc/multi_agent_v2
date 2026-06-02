"""Test fixtures for F-01-001 SSO integration tests.

Runs in two modes selected by the DOCKER_TEST env var:

  DOCKER_TEST unset (default):
    - SQLite in-memory + fakeredis  — no external services needed, fast CI

  DOCKER_TEST=1:
    - Real PostgreSQL (DATABASE_URL) + real Redis (REDIS_URL)
    - Intended for use via `docker compose run --rm test`
    - Tables are created and torn down once per session; each test flushes
      its own Redis DB and truncates User rows via autouse fixture

Key fixtures:
  rsa_private_key / rsa_private_pem / jwks_payload — test RSA key pair
  make_id_token (helper)     — sign a valid/invalid OIDC ID token
  test_settings              — Settings instance wired for tests
  db_engine                  — SQLAlchemy engine (SQLite or PostgreSQL)
  db_session                 — per-test DB session (rolls back if possible)
  redis_client               — fakeredis or real Redis (flushed per test)
  client                     — FastAPI TestClient with all deps overridden
"""
import base64
import os
import time
from typing import Generator

import fakeredis
import httpx
import pytest
import redis as real_redis_lib
import respx
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from protegopay.api.deps import get_redis
from protegopay.core.config import Settings, get_settings
from protegopay.db.models import Base, User
from protegopay.db.session import get_db
from protegopay.main import app
from protegopay.services.oidc import invalidate_jwks_cache

# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------

_DOCKER = os.environ.get("DOCKER_TEST", "").lower() in ("1", "true")
_DB_URL = os.environ.get("DATABASE_URL", "")
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/1")

TEST_AUDIENCE = "protegopay-pilot"
TEST_ISSUER = "https://test-idp.example.com"
TEST_JWKS_URI = "https://test-idp.example.com/.well-known/jwks.json"
TEST_SESSION_SECRET = os.environ.get("SESSION_SECRET", "test-session-secret-32bytes-long!!")
TEST_HMAC_KEY = os.environ.get("EXTERNAL_ID_HMAC_KEY", "test-hmac-key-32bytes-long-filler")
TEST_KID = "test-key-1"


# ---------------------------------------------------------------------------
# RSA key pair (session-scoped — generated once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def rsa_private_key():
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )


@pytest.fixture(scope="session")
def rsa_private_pem(rsa_private_key) -> str:
    return rsa_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


@pytest.fixture(scope="session")
def jwks_payload(rsa_private_key) -> dict:
    """Build a JWKS document from the test RSA public key."""
    pub = rsa_private_key.public_key().public_numbers()

    def _b64url(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    return {
        "keys": [{
            "kty": "RSA",
            "kid": TEST_KID,
            "use": "sig",
            "alg": "RS256",
            "n": _b64url(pub.n, 256),
            "e": _b64url(pub.e, 3),
        }]
    }


# ---------------------------------------------------------------------------
# Token helper (module-level so tests can import it directly)
# ---------------------------------------------------------------------------

def make_id_token(
    rsa_private_pem: str,
    sub: str = "external-user-123",
    aud: str = TEST_AUDIENCE,
    iss: str = TEST_ISSUER,
    exp_delta: int = 300,
    kid: str = TEST_KID,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "aud": aud, "iss": iss, "iat": now, "exp": now + exp_delta},
        rsa_private_pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        oidc_jwks_uri=TEST_JWKS_URI,
        oidc_audience=TEST_AUDIENCE,
        oidc_issuer=TEST_ISSUER,
        session_secret=TEST_SESSION_SECRET,
        session_expiry_seconds=900,
        external_id_hmac_key=TEST_HMAC_KEY,
        redis_url=_REDIS_URL if _DOCKER else "redis://localhost:6379/99",
        database_url=_DB_URL if _DOCKER else "sqlite:///:memory:",
        environment="test",
    )


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_engine(test_settings):
    if _DOCKER:
        engine = create_engine(_DB_URL)
    else:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    Base.metadata.create_all(bind=engine)
    yield engine
    if _DOCKER:
        Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture(autouse=True)
def _clean_db(db_engine):
    """Truncate all data rows between tests (required for real Postgres; harmless for SQLite)."""
    yield
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM deposit_limits"))
        conn.execute(text("DELETE FROM spending_events"))
        conn.execute(text("DELETE FROM users"))
        conn.commit()


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

@pytest.fixture
def redis_client():
    if _DOCKER:
        client = real_redis_lib.from_url(_REDIS_URL, decode_responses=True)
        client.flushdb()
        yield client
        client.flushdb()
    else:
        yield fakeredis.FakeRedis(decode_responses=True)


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def client(test_settings, db_session, redis_client, jwks_payload):
    """TestClient with all external dependencies replaced by test doubles.

    - JWKS fetch is always mocked via respx (avoids network calls in both modes)
    - DB and Redis use real or fake services depending on DOCKER_TEST
    """
    invalidate_jwks_cache()

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_db] = lambda: (yield db_session)
    app.dependency_overrides[get_redis] = lambda: redis_client

    with respx.mock(assert_all_called=False) as mock:
        mock.get(TEST_JWKS_URI).mock(return_value=httpx.Response(200, json=jwks_payload))
        with TestClient(app, base_url="https://testserver", raise_server_exceptions=True) as tc:
            yield tc

    app.dependency_overrides.clear()
    invalidate_jwks_cache()
