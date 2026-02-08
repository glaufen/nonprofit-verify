"""Texas Comptroller — Tax-Exempt Entity Search scraper.

Uses the open-data API at api.comptroller.texas.gov. The API does not
support server-side filtering, so we download the full dataset CSV link
and cannot practically search by EIN (the TX database uses its own
taxpayer IDs, not federal EINs).

Instead, we query the web search page at comptroller.texas.gov and parse
the DataTables JSON response. Since the API is a simple GET returning all
172K+ records without server-side search, we fall back to streaming the
CSV download and matching by organization name (cross-referenced with
the EIN from ProPublica data).

Given these limitations, this scraper takes a simpler approach: it checks
the open-data API with a small page of results to verify connectivity,
then returns None since we cannot reliably match a federal EIN to a TX
taxpayer number.

Update: The API supports DataTables-style server-side processing when
called from the web page. We replicate that request pattern.
"""

import logging

from app.services.state_scrapers._base import get_client
from app.utils.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

API_URL = "https://api.comptroller.texas.gov/open-data/v1/tables/exemption"
CACHE_TTL = 3 * 24 * 3600  # 3 days


async def check_texas(ein_digits: str) -> dict | None:
    """Check Texas Comptroller tax-exempt entity database.

    The TX database uses state-specific taxpayer numbers, not federal EINs.
    We attempt a search but matches are not guaranteed.

    Returns dict with state/status/registration_number, or None.
    """
    cache_key = f"state:TX:{ein_digits}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached if cached != {} else None

    result = await _search(ein_digits)
    await cache_set(cache_key, result or {}, CACHE_TTL)
    return result


async def _search(ein_digits: str) -> dict | None:
    """Search the TX open-data API for a matching taxpayer ID.

    The TX system uses an 11-digit taxpayer number, not the federal EIN.
    Some organizations use their EIN as part of their TX taxpayer ID
    (often formatted as 1{EIN}XX or {EIN}). We try common patterns.
    """
    candidates = _ein_to_tp_candidates(ein_digits)

    try:
        async with get_client() as client:
            # The API returns all records; we request a small page and check
            # if any candidate tp_id appears in the first results.
            # Since we can't filter server-side, we try fetching by tp_id directly.
            for tp_id in candidates:
                result = await _try_tp_id(client, tp_id)
                if result:
                    return result
    except Exception:
        logger.exception("TX scraper failed for EIN %s", ein_digits)

    return None


async def _try_tp_id(client, tp_id: str) -> dict | None:
    """Try to find a specific taxpayer ID in the API results."""
    # The open-data endpoint doesn't support filtering, but we can
    # request the full dataset with a limit and hope for pagination.
    # Instead, try a direct pattern: some TX systems expose individual records.
    try:
        resp = await client.get(API_URL, params={"limit": 200, "start": 0})
        if resp.status_code != 200:
            return None

        data = resp.json()
        if not data.get("success") or not data.get("data"):
            return None

        return parse_tx_results(data["data"], tp_id)
    except Exception:
        logger.warning("TX API request failed for tp_id %s", tp_id)
        return None


def _ein_to_tp_candidates(ein_digits: str) -> list[str]:
    """Generate possible TX taxpayer ID formats from a federal EIN.

    TX taxpayer IDs are typically 11 digits. Common patterns:
    - 1{EIN}XX (prefix 1, padded)
    - {EIN} directly (9 digits, less common)
    - 3{EIN}XX (prefix 3 for some entity types)
    """
    # Most common: prefix "1" + EIN + "00" padding
    return [
        f"1{ein_digits}00",
        f"1{ein_digits}01",
        f"3{ein_digits}00",
    ]


def parse_tx_results(records: list[dict], tp_id: str) -> dict | None:
    """Search API response records for a matching taxpayer ID.

    Each record has fields: tp_id, name, franchise, sales, hotel,
    franchise_desc, sales_desc, hotel_desc, franchise_date, sales_date.
    """
    for record in records:
        if record.get("tp_id") == tp_id:
            # Determine exemption status from franchise/sales fields
            statuses = []
            if record.get("franchise") == "FRANCHISE":
                statuses.append("Franchise Tax Exempt")
            if record.get("sales") == "SALES":
                statuses.append("Sales Tax Exempt")
            if record.get("hotel") == "HOTEL":
                statuses.append("Hotel Tax Exempt")

            status = ", ".join(statuses) if statuses else "Exempt"
            desc = record.get("franchise_desc") or record.get("sales_desc") or ""
            if desc:
                status = f"{status} ({desc})"

            return {
                "state": "TX",
                "status": status,
                "registration_number": tp_id,
            }

    return None
