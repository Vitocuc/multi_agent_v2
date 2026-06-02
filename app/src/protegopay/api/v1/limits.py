"""Voluntary Deposit Limits API — F-01-003.

PUT    /v1/limits/{period}  — upsert (create or update) a deposit limit
GET    /v1/limits            — list all active limits for the authenticated user
DELETE /v1/limits/{period}  — remove a deposit limit

Security enforced here:
  - Auth: get_current_user_id dep validates JWT + Redis blacklist on every request
  - Authorization: user_id from JWT only — never from request body or path
  - Input: period validated as Literal enum; amount validated > 0 and ≤ 10_000_000
  - Rate limiting: 60 req/min per token JTI (sliding window, Redis)
  - Audit log: limit_change event per write — no amount value logged
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
from ...db.models import DepositLimit
from ...db.session import get_db
from ..deps import get_current_user_id, get_redis
from ...services.rate_limiter import is_api_rate_limited

router = APIRouter(prefix="/v1", tags=["limits"])

_COOKIE_NAME = "pp_session"
_MAX_AMOUNT = 10_000_000  # €100k ceiling for pilot


class PeriodEnum(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class LimitRequest(BaseModel):
    amount_eurocents: int

    model_config = {"str_strip_whitespace": True}


class LimitResponse(BaseModel):
    period: str
    amount_eurocents: int
    created_at: str   # ISO 8601
    updated_at: str   # ISO 8601


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


def _validate_amount(amount: int) -> None:
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "amount must be a positive integer"},
        )
    if amount > _MAX_AMOUNT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": f"amount_eurocents exceeds maximum of {_MAX_AMOUNT}"},
        )


def _limit_to_response(limit: DepositLimit) -> LimitResponse:
    return LimitResponse(
        period=limit.period,
        amount_eurocents=limit.amount_eurocents,
        created_at=limit.created_at.isoformat(),
        updated_at=limit.updated_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# PUT /v1/limits/{period} — upsert
# ---------------------------------------------------------------------------

@router.put("/limits/{period}", response_model=LimitResponse)
def upsert_limit(
    period: PeriodEnum,
    body: LimitRequest,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Create or update a voluntary deposit limit for the authenticated user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)
    _validate_amount(body.amount_eurocents)

    now = datetime.now(timezone.utc)
    existing = (
        db.query(DepositLimit)
        .filter(DepositLimit.user_id == user_id, DepositLimit.period == period.value)
        .first()
    )

    if existing is None:
        limit = DepositLimit(
            user_id=user_id,
            period=period.value,
            amount_eurocents=body.amount_eurocents,
            created_at=now,
            updated_at=now,
        )
        db.add(limit)
        action = "created"
    else:
        existing.amount_eurocents = body.amount_eurocents
        existing.updated_at = now
        limit = existing
        action = "updated"

    db.commit()
    db.refresh(limit)

    # Audit: user_id + period + action — amount intentionally excluded
    audit("limit_change", "success", user_id=user_id, request_id=f"{period.value}:{action}")
    return _limit_to_response(limit)


# ---------------------------------------------------------------------------
# GET /v1/limits — list all limits for user
# ---------------------------------------------------------------------------

@router.get("/limits", response_model=List[LimitResponse])
def list_limits(
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Return all active deposit limits for the authenticated user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    limits = (
        db.query(DepositLimit)
        .filter(DepositLimit.user_id == user_id)
        .all()
    )
    return [_limit_to_response(lim) for lim in limits]


# ---------------------------------------------------------------------------
# DELETE /v1/limits/{period} — remove a limit
# ---------------------------------------------------------------------------

@router.delete("/limits/{period}", status_code=status.HTTP_204_NO_CONTENT)
def delete_limit(
    period: PeriodEnum,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Remove a voluntary deposit limit for the authenticated user."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    limit = (
        db.query(DepositLimit)
        .filter(DepositLimit.user_id == user_id, DepositLimit.period == period.value)
        .first()
    )
    if limit is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="limit_not_found")

    db.delete(limit)
    db.commit()

    # Audit: user_id + period + action — amount intentionally excluded
    audit("limit_change", "success", user_id=user_id, request_id=f"{period.value}:deleted")
