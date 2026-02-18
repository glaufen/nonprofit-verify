from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.models.schemas import VerifyResponse
from app.services.enricher import verify_organization
from app.utils.cache import cache_get, cache_set, get_redis
from app.utils.ein import ein_to_digits, validate_ein

DAILY_LIMIT = 20

router = APIRouter()


async def _check_ip_rate_limit(ip: str):
    """Simple daily rate limit by IP address for public lookups."""
    r = await get_redis()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"public_ratelimit:{ip}:{day}"

    count = await r.incr(key)
    if count == 1:
        await r.expire(key, 48 * 3600)

    if count > DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Daily lookup limit exceeded ({DAILY_LIMIT}/day). Get a free API key for more.",
            headers={"Retry-After": "3600"},
        )


@router.get(
    "/public/verify/{ein}",
    response_model=VerifyResponse,
    summary="Public nonprofit lookup (no API key required)",
    description="Free public lookup with daily rate limiting per IP. For higher volume, get an API key.",
)
async def public_verify(ein: str, request: Request):
    client_ip = request.headers.get("x-forwarded-for", request.client.host)
    # Use first IP if multiple are chained
    if "," in client_ip:
        client_ip = client_ip.split(",")[0].strip()

    await _check_ip_rate_limit(client_ip)

    normalized = validate_ein(ein)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid EIN format: '{ein}'. Expected XX-XXXXXXX or XXXXXXXXX.",
        )

    cache_key = f"verify:{ein_to_digits(normalized)}"
    cached = await cache_get(cache_key)
    if cached is not None:
        if cached.get("_not_found"):
            raise HTTPException(status_code=404, detail=f"No nonprofit found with EIN {normalized}")
        return cached

    result = await verify_organization(normalized)
    if result is None:
        await cache_set(cache_key, {"_not_found": True}, settings.cache_404_ttl_seconds)
        raise HTTPException(status_code=404, detail=f"No nonprofit found with EIN {normalized}")

    await cache_set(cache_key, result.model_dump(), settings.cache_ttl_seconds)
    return result
