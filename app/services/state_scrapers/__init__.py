"""State registry scrapers orchestrator.

Runs CA, NY, TX scrapers concurrently and returns combined results.
Each scraper fails independently — exceptions are logged and the state is skipped.
"""

import asyncio
import logging

from app.services.state_scrapers import california, new_york, texas

logger = logging.getLogger(__name__)

_SCRAPERS = [
    ("CA", california, "check_california"),
    ("NY", new_york, "check_new_york"),
    ("TX", texas, "check_texas"),
]


async def check_all_states(ein_digits: str) -> list[dict]:
    """Check registration across all supported states.

    Returns list of dicts with keys: state, status, registration_number.
    Each scraper runs concurrently; failures are logged and skipped.
    """

    async def _safe_check(label: str, module, fn_name: str):
        try:
            fn = getattr(module, fn_name)
            return await fn(ein_digits)
        except Exception:
            logger.exception("State scraper %s failed for EIN %s", label, ein_digits)
            return None

    results = await asyncio.gather(
        *[_safe_check(label, mod, fn_name) for label, mod, fn_name in _SCRAPERS]
    )
    return [r for r in results if r is not None]
