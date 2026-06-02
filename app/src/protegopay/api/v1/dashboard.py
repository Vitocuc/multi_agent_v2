"""Spending Dashboard API — F-01-002.

GET /v1/dashboard  — return authenticated user's aggregated spending summary
                     for the current or previous calendar month.

Security enforced here:
  - Auth: get_current_user_id dep validates JWT + Redis blacklist
  - Authorization: user_id comes from JWT claim only — never from request
  - Rate limiting: 60 req/min per session token JTI (sliding window, Redis)
  - Audit log: data_access event emitted per successful response (no amounts)
  - Response: aggregated totals only — no raw events, no transaction IDs, no PII
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List

import redis as redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.logging_setup import audit
from ...db.models import AlertRecord, SpendingEvent
from ...db.session import get_db
from ..deps import get_current_user_id, get_redis
from ...services.rate_limiter import is_api_rate_limited
from ...core.security import decode_session_token
from jose import JWTError

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
    period_start: str   # ISO 8601
    period_end: str     # ISO 8601
    total_deposit_eurocents: int
    session_count: int
    alerts: List[AlertInfo]  # unacknowledged alerts for this user (all periods)


def _month_boundaries(period: Period, now: datetime) -> tuple[datetime, datetime]:
    """Return (start_inclusive, end_exclusive) for the requested period."""
    if period == Period.current_month:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    else:  # last_month
        first_of_current = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if first_of_current.month == 1:
            start = first_of_current.replace(year=first_of_current.year - 1, month=12)
        else:
            start = first_of_current.replace(month=first_of_current.month - 1)
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
    """Return aggregated spending summary for the authenticated user."""
    # Rate limiting — per-token JTI (60 req/min sliding window)
    jti: str | None = None
    if session_token:
        try:
            payload = decode_session_token(session_token, settings)
            jti = payload.get("jti")
        except JWTError:
            pass  # already validated by get_current_user_id; treat missing jti as no key

    if jti and is_api_rate_limited(jti, redis):
        audit("rate_limit_hit", "rejected", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
        )

    now = datetime.now(timezone.utc)
    period_start, period_end = _month_boundaries(period, now)

    # Aggregate totals — ownership enforced via user_id from JWT
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
    total_deposit_eurocents = int(row[0])
    session_count = int(row[1])

    # Fetch unacknowledged alerts — ownership enforced by user_id from JWT
    unacked_alerts = (
        db.query(AlertRecord)
        .filter(AlertRecord.user_id == user_id, AlertRecord.acknowledged == False)  # noqa: E712
        .all()
    )
    alerts = [
        AlertInfo(id=a.id, alert_type=a.alert_type, period=a.period, acknowledged=a.acknowledged)
        for a in unacked_alerts
    ]

    # Audit log: user_id + period only — never amounts
    audit("data_access", "success", user_id=user_id, request_id=period.value)

    return DashboardResponse(
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        total_deposit_eurocents=total_deposit_eurocents,
        session_count=session_count,
        alerts=alerts,
    )
