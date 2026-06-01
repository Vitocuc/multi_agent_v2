"""Sliding-window rate limiter backed by Redis.

For auth endpoints: counts consecutive failures per IP.
Fails closed — if Redis is unavailable, requests are blocked.
"""
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
