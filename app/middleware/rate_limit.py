from datetime import datetime, timezone

from fastapi import HTTPException

from app.utils.cache import get_redis


async def check_rate_limit(api_key_info: dict) -> int:
    """Check monthly rate limit for an API key. Returns current count."""
    r = await get_redis()
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"ratelimit:{api_key_info['id']}:{period}"

    count = await r.incr(key)
    if count == 1:
        # Expire after ~35 days so counters auto-clean
        await r.expire(key, 35 * 24 * 3600)

    limit = api_key_info["monthly_limit"]
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly rate limit exceeded ({limit} requests/month). Upgrade your plan for higher limits.",
            headers={"Retry-After": "86400"},
        )

    return count


async def check_rate_limit_batch(api_key_info: dict, count: int) -> int:
    """Check monthly rate limit for a batch request. Increments by count. Returns new total."""
    r = await get_redis()
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"ratelimit:{api_key_info['id']}:{period}"

    new_total = await r.incrby(key, count)
    if new_total == count:
        # First increment this month — set expiry
        await r.expire(key, 35 * 24 * 3600)

    limit = api_key_info["monthly_limit"]
    if new_total > limit:
        # Roll back the increment so the caller can retry later
        await r.decrby(key, count)
        raise HTTPException(
            status_code=429,
            detail=f"Monthly rate limit exceeded ({limit} requests/month). This batch of {count} would exceed your limit. Upgrade your plan for higher limits.",
            headers={"Retry-After": "86400"},
        )

    return new_total
