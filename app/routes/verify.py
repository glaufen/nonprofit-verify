import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.database import get_pool
from app.middleware.auth import verify_api_key
from app.middleware.rate_limit import check_rate_limit
from app.models.schemas import ErrorResponse, VerifyResponse
from app.services.enricher import verify_organization
from app.utils.cache import cache_get, cache_set
from app.utils.ein import ein_to_digits, validate_ein

router = APIRouter()


@router.get(
    "/verify/{ein}",
    response_model=VerifyResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid EIN format"},
        401: {"model": ErrorResponse, "description": "Invalid API key"},
        404: {"model": ErrorResponse, "description": "Nonprofit not found"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Verify a nonprofit organization by EIN",
    description="Returns comprehensive nonprofit verification data including tax status, financials, and state registrations.",
)
async def verify_nonprofit(
    ein: str,
    api_key_info: dict = Depends(verify_api_key),
):
    start = time.time()

    # Validate EIN format
    normalized = validate_ein(ein)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid EIN format: '{ein}'. Expected XX-XXXXXXX or XXXXXXXXX.",
        )

    # Rate limit check
    await check_rate_limit(api_key_info)

    # Check cache
    cache_key = f"verify:{ein_to_digits(normalized)}"
    cached = await cache_get(cache_key)
    if cached is not None:
        elapsed_ms = int((time.time() - start) * 1000)
        await _record_usage(api_key_info, normalized, 200 if not cached.get("_not_found") else 404, elapsed_ms, True)
        if cached.get("_not_found"):
            raise HTTPException(status_code=404, detail=f"No nonprofit found with EIN {normalized}")
        return cached

    # Fetch fresh data from all sources
    result = await verify_organization(normalized)
    elapsed_ms = int((time.time() - start) * 1000)

    if result is None:
        await cache_set(cache_key, {"_not_found": True}, settings.cache_404_ttl_seconds)
        await _record_usage(api_key_info, normalized, 404, elapsed_ms, False)
        raise HTTPException(status_code=404, detail=f"No nonprofit found with EIN {normalized}")

    # Cache and return
    response_dict = result.model_dump()
    await cache_set(cache_key, response_dict, settings.cache_ttl_seconds)
    await _record_usage(api_key_info, normalized, 200, elapsed_ms, False)

    return result


async def _record_usage(
    api_key_info: dict, ein: str, status: int, elapsed_ms: int, cache_hit: bool
):
    """Record API usage in PostgreSQL. Best-effort (won't fail the request)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO api_usage (api_key_id, endpoint, ein, response_status, response_time_ms, cache_hit)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                api_key_info["id"],
                "verify",
                ein,
                status,
                elapsed_ms,
                cache_hit,
            )
    except Exception:
        pass  # Usage tracking is non-critical
