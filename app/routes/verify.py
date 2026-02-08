import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.database import get_pool
from app.middleware.auth import verify_api_key
from app.middleware.rate_limit import check_rate_limit, check_rate_limit_batch
from app.models.schemas import (
    BatchVerifyRequest,
    BatchVerifyResponse,
    BatchVerifyResult,
    ErrorResponse,
    VerifyResponse,
)
from app.services.enricher import verify_organization
from app.utils.cache import cache_get, cache_set
from app.utils.ein import ein_to_digits, validate_ein

MAX_BATCH_SIZE = 50

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


@router.post(
    "/verify/batch",
    response_model=BatchVerifyResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid EIN or batch too large"},
        401: {"model": ErrorResponse, "description": "Invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Verify multiple nonprofit organizations by EIN",
    description="Returns verification data for up to 50 EINs in a single request. Each EIN is processed independently; individual failures don't affect other results.",
)
async def verify_batch(
    request: BatchVerifyRequest,
    api_key_info: dict = Depends(verify_api_key),
):
    # Validate batch size
    if len(request.eins) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(request.eins)} exceeds maximum of {MAX_BATCH_SIZE} EINs per request.",
        )

    # Validate all EINs upfront
    normalized_map: dict[str, str] = {}  # original -> normalized
    for ein in request.eins:
        normalized = validate_ein(ein)
        if not normalized:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid EIN format: '{ein}'. Expected XX-XXXXXXX or XXXXXXXXX.",
            )
        normalized_map[ein] = normalized

    # Deduplicate by normalized EIN (digits)
    unique_eins: dict[str, str] = {}  # digits -> normalized
    for normalized in normalized_map.values():
        digits = ein_to_digits(normalized)
        if digits not in unique_eins:
            unique_eins[digits] = normalized

    # Rate limit check (costs 1 per unique EIN)
    await check_rate_limit_batch(api_key_info, len(unique_eins))

    # Process all unique EINs concurrently
    async def _process_ein(normalized: str) -> tuple[str, VerifyResponse | None, str | None]:
        """Returns (normalized_ein, data_or_none, error_or_none)."""
        try:
            cache_key = f"verify:{ein_to_digits(normalized)}"
            cached = await cache_get(cache_key)
            if cached is not None:
                if cached.get("_not_found"):
                    return (normalized, None, f"No nonprofit found with EIN {normalized}")
                return (normalized, VerifyResponse(**cached), None)

            result = await verify_organization(normalized)
            if result is None:
                await cache_set(cache_key, {"_not_found": True}, settings.cache_404_ttl_seconds)
                return (normalized, None, f"No nonprofit found with EIN {normalized}")

            await cache_set(cache_key, result.model_dump(), settings.cache_ttl_seconds)
            return (normalized, result, None)
        except Exception as e:
            return (normalized, None, str(e))

    tasks = [_process_ein(normalized) for normalized in unique_eins.values()]
    results_raw = await asyncio.gather(*tasks)

    # Index results by digits for lookup
    results_by_digits: dict[str, tuple[VerifyResponse | None, str | None]] = {}
    for normalized, data, error in results_raw:
        results_by_digits[ein_to_digits(normalized)] = (data, error)

    # Assemble response in original request order
    results: list[BatchVerifyResult] = []
    succeeded = 0
    failed = 0
    for ein in request.eins:
        normalized = normalized_map[ein]
        digits = ein_to_digits(normalized)
        data, error = results_by_digits[digits]
        if data is not None:
            results.append(BatchVerifyResult(ein=normalized, success=True, data=data))
            succeeded += 1
        else:
            results.append(BatchVerifyResult(ein=normalized, success=False, error=error))
            failed += 1

    # Record usage (best-effort, one row per unique EIN)
    start = time.time()
    for normalized in unique_eins.values():
        digits = ein_to_digits(normalized)
        data, error = results_by_digits[digits]
        status_code = 200 if data is not None else 404
        elapsed_ms = int((time.time() - start) * 1000)
        await _record_usage(api_key_info, normalized, status_code, elapsed_ms, False, endpoint="batch")

    return BatchVerifyResponse(
        total=len(request.eins),
        succeeded=succeeded,
        failed=failed,
        results=results,
    )


async def _record_usage(
    api_key_info: dict, ein: str, status: int, elapsed_ms: int, cache_hit: bool,
    *, endpoint: str = "verify",
):
    """Record API usage in PostgreSQL. Best-effort (won't fail the request)."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO api_usage (api_key_id, endpoint, ein, response_status, response_time_ms, cache_hit)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                api_key_info["id"],
                endpoint,
                ein,
                status,
                elapsed_ms,
                cache_hit,
            )
    except Exception:
        pass  # Usage tracking is non-critical
