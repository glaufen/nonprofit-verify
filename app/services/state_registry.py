"""State charity registration checks.

Phase 1 stub - returns empty results.
Phase 4 will add scrapers for CA, NY, TX and more.
"""


async def check_all_states(ein_digits: str) -> list[dict]:
    """Check registration across supported states.

    Returns list of dicts with keys: state, status, registration_number.
    """
    # TODO: Implement state registry scrapers (CA, NY, TX)
    return []
