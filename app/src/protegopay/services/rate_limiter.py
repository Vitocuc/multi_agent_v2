"""Sliding-window rate limiter backed by Redis.

For auth endpoints: counts consecutive failures per IP.
For API endpoints: sliding-window request count per token JTI (60 req/min).
Fails closed — if Redis is unavailable, requests are blocked.
"""
import time

import redis as redis_lib


def record_auth_failure(ip: str, window_seconds: int, client: redis_lib.Redis) -> int:
    """Increment the failure counter for this IP. Returns the new count."""
    key = f"rate_limit:auth_fail:{ip}"
    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds, nx=True)  # set TTL only on first failure
    results = pipe.execute()
    return results[0]  # current count after increment


def get_auth_failure_count(ip: str, client: redis_lib.Redis) -> int:
    """Return the current failure count for this IP (0 if not set)."""
    key = f"rate_limit:auth_fail:{ip}"
    val = client.get(key)
    return int(val) if val else 0


def is_rate_limited(ip: str, max_failures: int, client: redis_lib.Redis) -> bool:
    return get_auth_failure_count(ip, client) >= max_failures


_API_WINDOW_SECONDS = 60
_API_MAX_REQUESTS = 60


def is_api_rate_limited(jti: str, client: redis_lib.Redis) -> bool:
    """Sliding-window check: 60 req/min per session token JTI.

    Uses a Redis sorted set keyed by JTI. Timestamps outside the 60-second
    window are pruned before counting. Fails closed: if Redis raises, block.
    """
    key = f"rate_limit:api:{jti}"
    now = time.time()
    window_start = now - _API_WINDOW_SECONDS

    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _API_WINDOW_SECONDS + 1)
        results = pipe.execute()
        count = results[2]
        return count > _API_MAX_REQUESTS
    except redis_lib.RedisError:
        return True  # fail closed
