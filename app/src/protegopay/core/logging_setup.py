import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("event_type", "user_id", "request_id", "outcome", "reason_code"):
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        return json.dumps(entry)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def audit(
    event_type: str,
    outcome: str,
    *,
    user_id: Optional[str] = None,
    reason_code: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    """Emit a structured audit log entry.

    Only safe, non-PII fields are accepted. Amounts, tokens, passwords,
    and connection strings must never be passed here.
    """
    logger = get_logger("audit")
    extra: dict = {"event_type": event_type, "outcome": outcome}
    if user_id is not None:
        extra["user_id"] = user_id
    if reason_code is not None:
        extra["reason_code"] = reason_code
    if request_id is not None:
        extra["request_id"] = request_id
    logger.info("audit_event", extra=extra)
