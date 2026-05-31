"""FastAPI dependency functions shared across routers."""
from typing import Generator

import redis as redis_lib
from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.security import decode_session_token
from ..db.session import get_db
from ..services.session_store import get_redis_client, is_blacklisted


def get_redis(settings: Settings = Depends(get_settings)) -> redis_lib.Redis:
    return get_redis_client(settings)


def get_current_user_id(
    request: Request,
    session_token: str | None = Cookie(default=None, alias="pp_session"),
    settings: Settings = Depends(get_settings),
    redis: redis_lib.Redis = Depends(get_redis),
) -> str:
    """Resolve the internal user UUID from the session cookie.

    Checks:
    1. Cookie present
    2. JWT signature and expiry valid
    3. JTI not on the Redis blacklist

    Returns the internal user UUID string.
    """
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")

    try:
        payload = decode_session_token(session_token, settings)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")

    jti = payload.get("jti")
    if jti and is_blacklisted(jti, redis):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_revoked")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")

    return user_id
