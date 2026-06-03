"""Reflection Pause API — F-02-002.

POST   /v1/pause              — activate a voluntary pause (1h, 24h, or 7d)
GET    /v1/pause              — return current active pause status
DELETE /v1/pause/{pause_id}  — cancel a pause (only within 30-min revocation window)

Security:
  - Auth: get_current_user_id on all endpoints
  - Authorization: user can only modify their own pause (403 on cross-user DELETE)
  - Input: duration validated as Literal["1h", "24h", "7d"] via Pydantic
  - Rate limiting: 60 req/min per token JTI
  - Audit: pause_start on activation; pause_end on cancellation
"""
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.logging_setup import audit
from ...core.security import decode_session_token
from ...db.models import PauseRecord
from ...db.session import get_db
from ..deps import get_current_user_id, get_redis
from ...services.rate_limiter import is_api_rate_limited

router = APIRouter(prefix="/v1", tags=["pause"])

_COOKIE_NAME = "pp_session"
_REVOCATION_WINDOW = timedelta(minutes=30)

_DURATION_MAP = {
    "1h":  timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d":  timedelta(days=7),
}


class DurationEnum(str, Enum):
    h1  = "1h"
    h24 = "24h"
    d7  = "7d"


class PauseRequest(BaseModel):
    duration: DurationEnum

    model_config = {"str_strip_whitespace": True}


class PauseResponse(BaseModel):
    pause_id: str
    duration: str
    status: str
    starts_at: str
    expires_at: str
    revocable_until: str


def _utc(dt: datetime) -> datetime:
    """Attach UTC to a naive datetime (SQLite strips tzinfo on read)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _enforce_rate_limit(session_token: str | None, user_id: str, settings: Settings, redis: redis_lib.Redis) -> None:
    jti: str | None = None
    if session_token:
        try:
            payload = decode_session_token(session_token, settings)
            jti = payload.get("jti")
        except JWTError:
            pass
    if jti and is_api_rate_limited(jti, redis):
        audit("rate_limit_hit", "rejected", user_id=user_id)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate_limit_exceeded")


def _active_pause(user_id: str, db: Session, now: datetime) -> Optional[PauseRecord]:
    """Return the user's current active pause, or None."""
    return (
        db.query(PauseRecord)
        .filter(
            PauseRecord.user_id == user_id,
            PauseRecord.status == "active",
            PauseRecord.expires_at > now,
        )
        .first()
    )


def _to_response(pause: PauseRecord) -> PauseResponse:
    return PauseResponse(
        pause_id=pause.id,
        duration=pause.duration,
        status=pause.status,
        starts_at=_utc(pause.starts_at).isoformat(),
        expires_at=_utc(pause.expires_at).isoformat(),
        revocable_until=_utc(pause.revocable_until).isoformat(),
    )


# ---------------------------------------------------------------------------
# POST /v1/pause — activate pause
# ---------------------------------------------------------------------------

@router.post("/pause", response_model=PauseResponse, status_code=status.HTTP_200_OK)
def activate_pause(
    body: PauseRequest,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Activate a voluntary reflection pause. Returns 409 if a pause is already active."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    now = datetime.now(timezone.utc)
    if _active_pause(user_id, db, now):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "pause_already_active"},
        )

    delta = _DURATION_MAP[body.duration.value]
    pause = PauseRecord(
        user_id=user_id,
        duration=body.duration.value,
        status="active",
        starts_at=now,
        expires_at=now + delta,
        revocable_until=now + _REVOCATION_WINDOW,
    )
    db.add(pause)
    db.commit()
    db.refresh(pause)

    audit("pause_start", "success", user_id=user_id, request_id=pause.id)
    return _to_response(pause)


# ---------------------------------------------------------------------------
# GET /v1/pause — current pause status
# ---------------------------------------------------------------------------

@router.get("/pause", status_code=status.HTTP_200_OK)
def get_pause(
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Return the user's current active pause, or null if none."""
    _enforce_rate_limit(session_token, user_id, settings, redis)
    now = datetime.now(timezone.utc)
    pause = _active_pause(user_id, db, now)
    if pause is None:
        return {"pause_active": False}
    return {"pause_active": True, **_to_response(pause).model_dump()}


# ---------------------------------------------------------------------------
# DELETE /v1/pause/{pause_id} — cancel pause
# ---------------------------------------------------------------------------

@router.delete("/pause/{pause_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_pause(
    pause_id: str,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Cancel a pause within the 30-minute revocation window. Returns 409 after that."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    pause = db.query(PauseRecord).filter(PauseRecord.id == pause_id).first()
    if pause is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="pause_not_found")
    if pause.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    now = datetime.now(timezone.utc)
    if now > _utc(pause.revocable_until):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "pause_irrevocable"},
        )

    pause.status = "cancelled"
    db.commit()

    audit("pause_end", "success", user_id=user_id, request_id=pause_id)
