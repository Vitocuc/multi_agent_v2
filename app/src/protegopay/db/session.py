from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base
from ..core.config import get_settings

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if "sqlite" in settings.database_url else {}
        _engine = create_engine(settings.database_url, connect_args=connect_args)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autoflush=False, autocommit=False)
    return _SessionLocal


def init_db() -> None:
    """Create all tables. Called on app startup."""
    Base.metadata.create_all(bind=_get_engine())


def get_db() -> Session:
    """FastAPI dependency — yields a DB session and closes it on exit."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()
