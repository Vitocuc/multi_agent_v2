"""OIDC ID token validation against the concessionaire's JWKS endpoint.

Validates signature, expiry, audience, and issuer.
Never stores or logs the raw token or its claims beyond the sub claim.
"""
import hashlib
import hmac
from typing import Optional

import httpx
from jose import jwt, JWTError, ExpiredSignatureError

from ..core.config import Settings
from ..core.logging_setup import get_logger

_log = get_logger(__name__)

# Simple in-process JWKS cache to avoid fetching on every request.
# In production, a TTL cache (e.g. cachetools.TTLCache) should be used.
_jwks_cache: Optional[dict] = None


def _fetch_jwks(jwks_uri: str) -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        resp = httpx.get(jwks_uri, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
    return _jwks_cache


def invalidate_jwks_cache() -> None:
    """Clear the JWKS cache — used in tests and on key rotation."""
    global _jwks_cache
    _jwks_cache = None


class OIDCValidationError(Exception):
    """Raised when the OIDC ID token is invalid for any reason."""
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def validate_id_token(id_token: str, settings: Settings) -> str:
    """Validate an OIDC ID token and return the external sub claim.

    Raises OIDCValidationError with a safe reason_code on any failure.
    The raw token is never logged.
    """
    # Step 1: parse header to find the signing key (kid)
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError:
        raise OIDCValidationError("malformed_token")

    kid = header.get("kid")

    # Step 2: fetch JWKS and find matching key
    try:
        jwks = _fetch_jwks(settings.oidc_jwks_uri)
    except Exception:
        raise OIDCValidationError("jwks_fetch_failed")

    key = None
    for k in jwks.get("keys", []):
        if kid is None or k.get("kid") == kid:
            key = k
            break

    if key is None:
        raise OIDCValidationError("key_not_found")

    # Step 3: decode and verify signature, expiry, audience, issuer
    try:
        payload = jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except ExpiredSignatureError:
        raise OIDCValidationError("token_expired")
    except JWTError:
        raise OIDCValidationError("token_invalid")

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise OIDCValidationError("missing_sub")

    return sub


def pseudonymise_external_id(sub: str, hmac_key: str) -> str:
    """Return HMAC-SHA256(hmac_key, sub) as a hex string.

    This is the lookup key stored in the DB — the raw sub is never persisted.
    """
    return hmac.new(hmac_key.encode(), sub.encode(), hashlib.sha256).hexdigest()
