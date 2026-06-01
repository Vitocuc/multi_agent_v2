"""Redis-backed JWT blacklist for session revocation on logout."""
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib

from ..core.config import Settings


def get_redis_client(settings: Settings) -> redis_lib.Redis:
    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def blacklist_token(jti: str, expires_at: datetime, client: redis_lib.Redis) -> None:
    """Add a JWT ID to the blacklist with a TTL matching the token's remaining lifetime."""
    now = datetime.now(timezone.utc)
    ttl_seconds = max(1, int((expires_at - now).total_seconds()))
    client.setex(f"blacklist:{jti}", ttl_seconds, "1")


def is_blacklisted(jti: str, client: redis_lib.Redis) -> bool:
    return client.exists(f"blacklist:{jti}") == 1
