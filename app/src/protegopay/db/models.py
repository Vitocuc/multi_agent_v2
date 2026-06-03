import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, Text, String, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Maps a pseudonymised external identity to an internal UUID.

    external_id_hmac is HMAC-SHA256(HMAC_KEY, oidc_sub_claim).
    The raw OIDC sub claim is never stored.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    external_id_hmac: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SpendingEvent(Base):
    """Aggregated spending record for a single gaming session deposit.

    Amounts are stored as integer eurocents (never float).
    No raw session identifiers or PII are stored.
    """
    __tablename__ = "spending_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    deposit_eurocents: Mapped[int] = mapped_column(Integer, nullable=False)
    event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class DepositLimit(Base):
    """Voluntary advisory deposit limit per period.

    Amounts stored as integer eurocents. One limit per user per period
    (daily/weekly/monthly). Limits are advisory — they do not block deposits.
    """
    __tablename__ = "deposit_limits"
    __table_args__ = (UniqueConstraint("user_id", "period", name="uq_deposit_limit_user_period"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)   # daily | weekly | monthly
    amount_eurocents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AlertThreshold(Base):
    """User-configured custom alert threshold per period.

    Stored as integer eurocents. No amounts logged.
    """
    __tablename__ = "alert_thresholds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)   # daily | weekly | monthly
    amount_eurocents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class AlertRecord(Base):
    """An in-app alert for a user, deduped per (user_id, period, alert_type).

    alert_type: limit_80pct | limit_100pct | custom_threshold
    Once created, it is not recreated within the same period unless acknowledged.
    """
    __tablename__ = "alert_records"
    __table_args__ = (
        UniqueConstraint("user_id", "period", "alert_type", name="uq_alert_user_period_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class ExportJob(Base):
    """GDPR Art. 20 data export job record.

    status: processing | ready | failed
    export_data: serialised JSON of the user's data — stored server-side,
                 never returned directly in API responses.
    download_token: short-lived signed token used to authorise the download URL.
    Pilot: data stored in DB; production should upload to S3 and store only the key.
    """
    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="processing")
    export_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
