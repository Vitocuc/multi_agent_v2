"""Alert evaluation service — F-02-001.

Called after a spending event is ingested (or on demand for the pilot with mock data).
Checks the user's current-period spending against:
  1. Voluntary deposit limits (80% and 100% thresholds)
  2. User-configured custom alert thresholds

Creates AlertRecord rows where a threshold is newly crossed.
Deduplication key: (user_id, period, alert_type) — one alert per type per period.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db.models import AlertRecord, AlertThreshold, DepositLimit, SpendingEvent


def _period_boundaries(period: str, now: datetime) -> tuple[datetime, datetime]:
    """Return (start_inclusive, end_exclusive) for the named period."""
    if period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
    elif period == "weekly":
        # ISO week: Monday → Sunday
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(weeks=1)
    else:  # monthly
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
    return start, end


def _current_spending(user_id: str, period: str, db: Session, now: datetime) -> int:
    start, end = _period_boundaries(period, now)
    total = (
        db.query(func.coalesce(func.sum(SpendingEvent.deposit_eurocents), 0))
        .filter(
            SpendingEvent.user_id == user_id,
            SpendingEvent.event_at >= start,
            SpendingEvent.event_at < end,
        )
        .scalar()
    )
    return int(total)


def _alert_exists(user_id: str, period: str, alert_type: str, db: Session) -> bool:
    return (
        db.query(AlertRecord)
        .filter(
            AlertRecord.user_id == user_id,
            AlertRecord.period == period,
            AlertRecord.alert_type == alert_type,
        )
        .first()
    ) is not None


def _create_alert(user_id: str, period: str, alert_type: str, db: Session, now: datetime) -> None:
    if _alert_exists(user_id, period, alert_type, db):
        return
    alert = AlertRecord(
        user_id=user_id,
        period=period,
        alert_type=alert_type,
        acknowledged=False,
        created_at=now,
    )
    db.add(alert)
    db.flush()  # write within current transaction; caller commits


def evaluate_all_alerts(user_id: str, db: Session, now: datetime | None = None) -> None:
    """Evaluate alert conditions for all periods and create new AlertRecords as needed.

    Safe to call multiple times — deduplication prevents duplicate records.
    Caller is responsible for db.commit() after this function returns.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    periods = ["daily", "weekly", "monthly"]
    for period in periods:
        spending = _current_spending(user_id, period, db, now)

        # Limit-based alerts
        limit = (
            db.query(DepositLimit)
            .filter(DepositLimit.user_id == user_id, DepositLimit.period == period)
            .first()
        )
        if limit and limit.amount_eurocents > 0:
            if spending >= limit.amount_eurocents:
                _create_alert(user_id, period, "limit_100pct", db, now)
            elif spending >= limit.amount_eurocents * 0.8:
                _create_alert(user_id, period, "limit_80pct", db, now)

        # Custom threshold alerts
        thresholds = (
            db.query(AlertThreshold)
            .filter(AlertThreshold.user_id == user_id, AlertThreshold.period == period)
            .all()
        )
        for threshold in thresholds:
            if spending >= threshold.amount_eurocents:
                _create_alert(user_id, period, "custom_threshold", db, now)
                break  # one custom_threshold alert per period is enough
