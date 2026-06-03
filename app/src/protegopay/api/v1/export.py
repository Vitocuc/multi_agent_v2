"""GDPR Data Export endpoints — F-02-003 (export sub-flow).

POST /v1/me/export                          — enqueue export job; 202
GET  /v1/me/export/{export_id}              — check status; return download URL when ready
GET  /v1/me/export/{export_id}/download     — serve the export file (token-authenticated)

Security:
  - Auth: get_current_user_id dep on POST and GET status endpoints
  - Ownership: export_id ownership verified before any data is returned (403 on mismatch)
  - Download token: short-lived (15 min) signed JWT — no session cookie required for download
  - Export content: internal_user_id, limits, alert_thresholds, pause_records, audit_events
    Explicitly excluded: spending amounts, OIDC claims, other users' data
  - Audit: gdpr_data_export event emitted on POST

Pilot note: export processing is synchronous within the request (DB session is shared).
Production should use a proper async queue (Celery/SQS) with a separate worker process.
"""
import json
from datetime import datetime, timezone, timedelta

import redis as redis_lib
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.config import Settings, get_settings
from ...core.logging_setup import audit
from ...core.security import (
    create_download_token,
    decode_download_token,
    decode_session_token,
)
from ...db.models import AlertThreshold, DepositLimit, ExportJob
from ...db.session import get_db
from ..deps import get_current_user_id, get_redis
from ...services.rate_limiter import is_api_rate_limited

router = APIRouter(prefix="/v1/me", tags=["export"])

_COOKIE_NAME = "pp_session"
_DOWNLOAD_EXPIRY_MINUTES = 15


class ExportStatusResponse(BaseModel):
    export_id: str
    status: str
    download_url: str | None = None


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


def _build_export_payload(user_id: str, db: Session) -> dict:
    """Collect user's own data for export. Explicitly excludes spending amounts and OIDC claims."""
    limits = db.query(DepositLimit).filter(DepositLimit.user_id == user_id).all()
    thresholds = db.query(AlertThreshold).filter(AlertThreshold.user_id == user_id).all()

    return {
        "internal_user_id": user_id,
        "export_generated_at": datetime.now(timezone.utc).isoformat(),
        "limit_settings": [
            {"period": lim.period, "amount_eurocents": lim.amount_eurocents,
             "created_at": lim.created_at.isoformat(), "updated_at": lim.updated_at.isoformat()}
            for lim in limits
        ],
        "alert_thresholds": [
            {"id": t.id, "period": t.period, "created_at": t.created_at.isoformat()}
            # amount_eurocents intentionally excluded from export per GDPR data minimisation
            for t in thresholds
        ],
        "pause_records": [],    # F-02-002 not yet implemented
        "audit_events": [],     # Requires CloudWatch integration; not stored in DB in pilot
        # Explicitly absent: spending_amounts, oidc_claims, other users' data
    }


# ---------------------------------------------------------------------------
# POST /v1/me/export — request export
# ---------------------------------------------------------------------------

@router.post("/export", status_code=status.HTTP_202_ACCEPTED)
def request_export(
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Request a GDPR data export. Returns 202; export is processed synchronously in the pilot.

    Production note: replace with async queue (Celery/SQS) — pilot processes inline
    to avoid test/DB session isolation issues with background threads.
    """
    _enforce_rate_limit(session_token, user_id, settings, redis)

    now = datetime.now(timezone.utc)
    job = ExportJob(user_id=user_id, status="processing", created_at=now)
    db.add(job)
    db.commit()
    db.refresh(job)

    # Audit: user_id only — no export content
    audit("gdpr_data_export", "success", user_id=user_id, request_id=job.id)

    # Process synchronously (pilot) — build payload and mark ready within this request
    payload = _build_export_payload(user_id, db)
    job.export_data = json.dumps(payload)
    job.download_token = create_download_token(job.id, settings)
    job.status = "ready"
    job.expires_at = now + timedelta(minutes=_DOWNLOAD_EXPIRY_MINUTES)
    db.commit()

    return {"export_id": job.id, "status": "processing"}


# ---------------------------------------------------------------------------
# GET /v1/me/export/{export_id} — check status
# ---------------------------------------------------------------------------

@router.get("/export/{export_id}", response_model=ExportStatusResponse)
def get_export_status(
    export_id: str,
    session_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
    user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
    redis: redis_lib.Redis = Depends(get_redis),
):
    """Return export status. When ready, includes a 15-min download URL."""
    _enforce_rate_limit(session_token, user_id, settings, redis)

    job = db.query(ExportJob).filter(ExportJob.id == export_id).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export_not_found")
    if job.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    download_url: str | None = None
    if job.status == "ready" and job.download_token:
        download_url = f"/v1/me/export/{export_id}/download?token={job.download_token}"

    return ExportStatusResponse(export_id=job.id, status=job.status, download_url=download_url)


# ---------------------------------------------------------------------------
# GET /v1/me/export/{export_id}/download — serve export file
# ---------------------------------------------------------------------------

@router.get("/export/{export_id}/download")
def download_export(
    export_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Serve the export file. Authenticated by short-lived download token (no cookie needed)."""
    try:
        payload = decode_download_token(token, settings)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_or_expired_token")

    if payload.get("export_id") != export_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="token_mismatch")

    job = db.query(ExportJob).filter(ExportJob.id == export_id).first()
    if job is None or job.status != "ready" or not job.export_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export_not_ready")

    return json.loads(job.export_data)
