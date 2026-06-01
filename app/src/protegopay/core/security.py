import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from jose import jwt, JWTError

from .config import Settings


def create_session_token(internal_user_id: str, settings: Settings) -> tuple[str, datetime]:
    """Issue a short-lived ProtegoPay session JWT.

    Returns the encoded token string and its expiry datetime.
    The token contains only the internal UUID — no external IdP claims.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.session_expiry_seconds)
    jti = str(uuid.uuid4())
    payload = {
        "sub": internal_user_id,
        "exp": expires_at,
        "iat": now,
        "jti": jti,
    }
    token = jwt.encode(payload, settings.session_secret, algorithm=settings.session_algorithm)
    return token, expires_at


def decode_session_token(token: str, settings: Settings) -> dict:
    """Decode and verify a ProtegoPay session JWT.

    Raises jose.JWTError on any validation failure.
    Returns the raw payload dict on success.
    """
    return jwt.decode(token, settings.session_secret, algorithms=[settings.session_algorithm])
