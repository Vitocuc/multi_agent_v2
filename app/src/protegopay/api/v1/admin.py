"""Admin endpoints — F-02-003 (admin sub-flow).

GET /v1/admin/stats  — concessionaire_admin only; returns anonymised aggregates.
                       Never returns individual user data, amounts, or identifiers.

Security:
  - Auth: get_admin_user_id dep (JWT + blacklist + role == concessionaire_admin)
  - Admin separation: this router is independent of user-scope endpoints
  - Audit: admin_action event emitted on every call
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends, status

from ...core.logging_setup import audit
from ...db.models import DepositLimit, User
from ...db.session import get_db
from ..deps import get_admin_user_id
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1/admin", tags=["admin"])


class AdminStatsResponse(BaseModel):
    active_users_count: int
    limits_configured_count: int
    pauses_active_count: int   # F-02-002 not yet implemented; always 0 in pilot


@router.get("/stats", response_model=AdminStatsResponse)
def get_admin_stats(
    admin_user_id: str = Depends(get_admin_user_id),
    db: Session = Depends(get_db),
):
    """Return anonymised aggregate statistics. Never returns individual user data."""
    active_users = db.query(User).count()
    limits_configured = db.query(DepositLimit).count()

    audit("admin_action", "success", user_id=admin_user_id, request_id="get_stats")

    return AdminStatsResponse(
        active_users_count=active_users,
        limits_configured_count=limits_configured,
        pauses_active_count=0,  # F-02-002 pause records not yet implemented
    )
