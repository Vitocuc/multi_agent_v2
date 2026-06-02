"""Spending Alert Notifications API — F-02-001.

GET    /v1/alerts                          — list unacknowledged alerts for user
PATCH  /v1/alerts/{alert_id}/acknowledge   — mark an alert acknowledged (own only)
POST   /v1/alert-thresholds               — create a custom alert threshold
GET    /v1/alert-thresholds               — list user's custom thresholds
DELETE /v1/alert-thresholds/{id}          — delete a custom threshold (own only)

Security enforced here:
  - Auth: get_current_user_id on every endpoint
  - Authorization: ownership check — user can only access their own alerts/thresholds
  - Input: period and amount validated via Pydantic
  - Rate limiting: 60 req/min per token JTI
  - Audit log: alert_config_change on every threshold write — no amounts logged
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List

import redis as redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.logging_setup import audit
from ...core.security import decode_session_token
from ...db.models import AlertRecord, AlertThreshold
from ...db.session import get_db
from ..deps import get_current_user_id, get_redis
from ...services.rate_limiter import is_api_rate_limited

router = APIRouter(prefix="/v1", tags=["alerts"])

_COOKIE_NAME = "pp_session"
_MAX_THRESHOLD = 10_000_000


class PeriodEnum(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class ThresholdRequest(BaseModel):
    amount_eurocents: int
    period: PeriodEnum

    model_config = {"str_strip_whitespace": True}


class ThresholdResponse(BaseModel):
    id: str
    period: str
    created_at: str


class AlertResponse(BaseModel):
    id: str
    alert_type: str
    period: str
    acknowledged: bool


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


# ---------------------------------------------------------------------------
# GET /v1/alerts — list unacknowledged alerts
# ---------------------------------------------------------------------------

@router.get("/alerts", response_model=List[AlertResponse])
def list_alerts(
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Return all unacknowledged alerts for the authenticated user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    alerts = (
        db.query(AlertRecord)
        .filter(AlertRecord.user_id == user_id, AlertRecord.acknowledged == False)  # noqa: E712
        .all()
    )
    return [AlertResponse(id=a.id, alert_type=a.alert_type, period=a.period, acknowledged=a.acknowledged)
            for a in alerts]


# ---------------------------------------------------------------------------
# PATCH /v1/alerts/{alert_id}/acknowledge — mark acknowledged
# ---------------------------------------------------------------------------

@router.patch("/alerts/{alert_id}/acknowledge", status_code=status.HTTP_200_OK)
def acknowledge_alert(
    alert_id: str,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Mark an alert as acknowledged. Returns 403 if alert belongs to another user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="alert_not_found")
    if alert.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    alert.acknowledged = True
    db.commit()
    return AlertResponse(id=alert.id, alert_type=alert.alert_type, period=alert.period, acknowledged=True)


# ---------------------------------------------------------------------------
# POST /v1/alert-thresholds — create custom threshold
# ---------------------------------------------------------------------------

@router.post("/alert-thresholds", response_model=ThresholdResponse, status_code=status.HTTP_200_OK)
def create_threshold(
    body: ThresholdRequest,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Create a custom alert threshold for the authenticated user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    if body.amount_eurocents <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "amount must be a positive integer"},
        )
    if body.amount_eurocents > _MAX_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": f"amount_eurocents exceeds maximum of {_MAX_THRESHOLD}"},
        )

    now = datetime.now(timezone.utc)
    threshold = AlertThreshold(
        user_id=user_id,
        period=body.period.value,
        amount_eurocents=body.amount_eurocents,
        created_at=now,
    )
    db.add(threshold)
    db.commit()
    db.refresh(threshold)

    # Audit: user_id + period + action — amount intentionally excluded
    audit("alert_config_change", "success", user_id=user_id, request_id=f"{body.period.value}:created")
    return ThresholdResponse(id=threshold.id, period=threshold.period, created_at=threshold.created_at.isoformat())


# ---------------------------------------------------------------------------
# GET /v1/alert-thresholds — list custom thresholds
# ---------------------------------------------------------------------------

@router.get("/alert-thresholds", response_model=List[ThresholdResponse])
def list_thresholds(
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Return all custom alert thresholds for the authenticated user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    thresholds = db.query(AlertThreshold).filter(AlertThreshold.user_id == user_id).all()
    return [ThresholdResponse(id=t.id, period=t.period, created_at=t.created_at.isoformat())
            for t in thresholds]


# ---------------------------------------------------------------------------
# DELETE /v1/alert-thresholds/{id} — remove a threshold
# ---------------------------------------------------------------------------

@router.delete("/alert-thresholds/{threshold_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_threshold(
    threshold_id: str,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Delete a custom alert threshold. Returns 403 if threshold belongs to another user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    threshold = db.query(AlertThreshold).filter(AlertThreshold.id == threshold_id).first()
    if threshold is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="threshold_not_found")
    if threshold.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    db.delete(threshold)
    db.commit()

    # Audit: user_id + period + action — amount intentionally excluded
    audit("alert_config_change", "success", user_id=user_id, request_id=f"{threshold.period}:deleted")
