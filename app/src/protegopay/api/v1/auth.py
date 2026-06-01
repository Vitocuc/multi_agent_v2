"""Auth endpoints — F-01-001: Concessionaire SSO Integration.

POST   /v1/auth/session  — validate OIDC ID token, issue session JWT cookie
GET    /v1/auth/me       — return current user_id and session expiry
DELETE /v1/auth/session  — revoke session (blacklist JTI, clear cookie)
"""
import uuid
from datetime import datetime, timezone

import redis as redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.logging_setup import audit
from ...core.security import create_session_token, decode_session_token
from ...db.models import User
from ...db.session import get_db
from ...services.oidc import OIDCValidationError, pseudonymise_external_id, validate_id_token
from ...services.rate_limiter import is_rate_limited, record_auth_failure
from ...services.session_store import blacklist_token, get_redis_client, is_blacklisted
from ..deps import get_current_user_id, get_redis

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_COOKIE_NAME = "pp_session"
_COOKIE_OPTS = {
    "httponly": True,
    "secure": True,
    "samesite": "strict",
    "path": "/",
}


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SessionRequest(BaseModel):
    """Pydantic schema — validated before any external call is made."""
    id_token: str

    model_config = {"str_strip_whitespace": True}

    def model_post_init(self, __context) -> None:
        if not self.id_token or len(self.id_token) < 20:
            raise ValueError("id_token is required and must be a JWT string")
        if len(self.id_token) > 8192:
            raise ValueError("id_token exceeds maximum length")


class MeResponse(BaseModel):
    user_id: str
    session_expires_at: str  # ISO 8601


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _upsert_user(external_id_hmac: str, db: Session) -> str:
    """Return internal user UUID, creating the user record on first login."""
    user = db.query(User).filter(User.external_id_hmac == external_id_hmac).first()
    if user is None:
        user = User(id=str(uuid.uuid4()), external_id_hmac=external_id_hmac)
        db.add(user)
        db.commit()
    return user.id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/session", status_code=status.HTTP_200_OK)
def create_session(
    body: SessionRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Exchange a concessionaire OIDC ID token for a ProtegoPay session cookie."""
    ip = _client_ip(request)

    # Rate-limit check — before any further processing
    if is_rate_limited(ip, settings.auth_fail_max, redis):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_requests",
        )

    # Validate the OIDC ID token (Pydantic ran first above)
    try:
        sub = validate_id_token(body.id_token, settings)
    except OIDCValidationError as exc:
        record_auth_failure(ip, settings.auth_fail_window_seconds, redis)
        audit("auth_failure", "failure", reason_code=exc.reason_code)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token"},
        )

    # Pseudonymise external identity and upsert user record
    external_id_hmac = pseudonymise_external_id(sub, settings.external_id_hmac_key)
    internal_user_id = _upsert_user(external_id_hmac, db)

    # Issue session JWT
    token, expires_at = create_session_token(internal_user_id, settings)

    # Set httpOnly cookie — max_age in seconds
    max_age = settings.session_expiry_seconds
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=int(expires_at.timestamp()),
        **_COOKIE_OPTS,
    )

    audit("auth_success", "success", user_id=internal_user_id)
    return {"user_id": internal_user_id, "session_expires_at": expires_at.isoformat()}


@router.get("/me", response_model=MeResponse)
def get_me(
    user_id: str = Depends(get_current_user_id),
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
):
    """Return the authenticated user's internal UUID and session expiry."""
    # Decode again to get expiry — token already validated by get_current_user_id
    try:
        payload = decode_session_token(session_token, settings)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")

    exp_ts = payload.get("exp")
    if exp_ts is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")

    expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
    return MeResponse(
        user_id=user_id,
        session_expires_at=expires_at.isoformat(),
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    response: Response,
    user_id: str = Depends(get_current_user_id),
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    settings: Settings = Depends(get_settings),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Revoke the session: add JTI to Redis blacklist and clear the cookie."""
    try:
        payload = decode_session_token(session_token, settings)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")

    jti = payload.get("jti")
    exp_ts = payload.get("exp")
    if jti and exp_ts:
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        blacklist_token(jti, expires_at, redis)

    response.delete_cookie(key=_COOKIE_NAME, path="/")
    audit("session_logout", "success", user_id=user_id)
