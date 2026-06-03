"""Spending Dashboard API — F-01-002 + F-02-002 pause extension.

GET /v1/dashboard  — return authenticated user's aggregated spending summary.
                     If a reflection pause is active, returns a reduced view
                     (no spending amounts) per F-02-002.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

import redis as redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.logging_setup import audit
from ...core.security import decode_session_token
from ...db.models import AlertRecord, PauseRecord, SpendingEvent
from ...db.session import get_db
from ..deps import get_current_user_id, get_redis
from ...services.rate_limiter import is_api_rate_limited

router = APIRouter(prefix="/v1", tags=["dashboard"])

_COOKIE_NAME = "pp_session"


class Period(str, Enum):
    current_month = "current_month"
    last_month = "last_month"


class AlertInfo(BaseModel):
    id: str
    alert_type: str
    period: str
    acknowledged: bool


class DashboardResponse(BaseModel):
    period_start: str
    period_end: str
    # Spending fields — omitted when a reflection pause is active
    total_deposit_eurocents: Optional[int] = None
    session_count: Optional[int] = None
    alerts: List[AlertInfo]
    # Pause fields — present only when pause is active
    pause_active: bool = False
    pause_expires_at: Optional[str] = None
    message: Optional[str] = None


def _month_boundaries(period: Period, now: datetime) -> tuple[datetime, datetime]:
    if period == Period.current_month:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(month=start.month + 1) if start.month < 12 else start.replace(year=start.year + 1, month=1)
    else:
        first_of_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = first_of_current.replace(month=first_of_current.month - 1) if first_of_current.month > 1 \
            else first_of_current.replace(year=first_of_current.year - 1, month=12)
        end = first_of_current
    return start, end


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    period: Period = Query(default=Period.current_month),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Return aggregated spending summary. Returns reduced view when a pause is active."""
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

    now = datetime.now(timezone.utc)
    period_start, period_end = _month_boundaries(period, now)

    # Check for active reflection pause — ownership enforced by user_id from JWT
    active_pause = (
        db.query(PauseRecord)
        .filter(
            PauseRecord.user_id == user_id,
            PauseRecord.status == "active",
            PauseRecord.expires_at > now,
        )
        .first()
    )

    # Unacknowledged alerts — always included (ownership enforced)
    unacked_alerts = (
        db.query(AlertRecord)
        .filter(AlertRecord.user_id == user_id, AlertRecord.acknowledged == False)  # noqa: E712
        .all()
    )
    alerts = [AlertInfo(id=a.id, alert_type=a.alert_type, period=a.period, acknowledged=a.acknowledged)
              for a in unacked_alerts]

    audit("data_access", "success", user_id=user_id, request_id=period.value)

    if active_pause:
        # Reduced view: no spending amounts returned during pause
        return DashboardResponse(
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            alerts=alerts,
            pause_active=True,
            pause_expires_at=(active_pause.expires_at if active_pause.expires_at.tzinfo else active_pause.expires_at.replace(tzinfo=timezone.utc)).isoformat(),
            message="You have an active reflection pause.",
        )

    row = (
        db.query(
            func.coalesce(func.sum(SpendingEvent.deposit_eurocents), 0),
            func.count(SpendingEvent.id),
        )
        .filter(
            SpendingEvent.user_id == user_id,
            SpendingEvent.event_at >= period_start,
            SpendingEvent.event_at < period_end,
        )
        .one()
    )

    return DashboardResponse(
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        total_deposit_eurocents=int(row[0]),
        session_count=int(row[1]),
        alerts=alerts,
        pause_active=False,
    )
