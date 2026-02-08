"""New York Charities Bureau — Registry Search scraper.

POSTs to charitiesnys.com/RegistrySearch/search_charities_action.jsp
with the EIN and parses the HTML results table.

Results table columns:
Organization Name | NY_Reg#_ | EIN | Registrant Type | City | State
"""

import logging

from bs4 import BeautifulSoup

from app.services.state_scrapers._base import get_client
from app.utils.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.charitiesnys.com/RegistrySearch/search_charities_action.jsp"
CACHE_TTL = 7 * 24 * 3600  # 7 days


async def check_new_york(ein_digits: str) -> dict | None:
    """Check NY Charities Bureau registry by EIN.

    Returns dict with state/status/registration_number, or None.
    """
    cache_key = f"state:NY:{ein_digits}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached if cached != {} else None

    result = await _scrape(ein_digits)
    await cache_set(cache_key, result or {}, CACHE_TTL)
    return result


async def _scrape(ein_digits: str) -> dict | None:
    """POST the search form and parse results."""
    # EIN format: first 2 digits, remaining 7 digits
    num1 = ein_digits[:2]
    num2 = ein_digits[2:]

    form_data = {
        "project": "Charities",
        "reg1": "",
        "reg2": "",
        "reg3": "",
        "orgId": "",
        "num1": num1,
        "num2": num2,
        "ein": ein_digits,
        "orgName": "",
        "searchType": "contains",
        "regType": "ALL",
    }

    try:
        async with get_client() as client:
            resp = await client.post(SEARCH_URL, data=form_data)
            if resp.status_code != 200:
                logger.warning("NY search returned %s", resp.status_code)
                return None

            return parse_ny_results(resp.text, ein_digits)
    except Exception:
        logger.exception("NY scraper failed for EIN %s", ein_digits)
        return None


def parse_ny_results(html: str, ein_digits: str) -> dict | None:
    """Parse the NY search results HTML for a matching EIN.

    The results table has class 'Bordered' and columns:
    Organization Name | NY_Reg#_ | EIN | Registrant Type | City | State
    """
    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", class_="Bordered")
    if not table:
        return None

    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        texts = [c.get_text(strip=True) for c in cells]

        # Column layout: Name | Reg# | EIN | Type | City | State
        # Verify EIN matches (column index 2)
        row_ein = texts[2].replace("-", "").strip() if len(texts) > 2 else ""
        if row_ein != ein_digits:
            continue

        reg_number = texts[1] if len(texts) > 1 else None
        registrant_type = texts[3] if len(texts) > 3 else None

        # NY doesn't show explicit status on search results;
        # presence in the registry means "Registered"
        status = f"Registered ({registrant_type})" if registrant_type else "Registered"

        return {
            "state": "NY",
            "status": status,
            "registration_number": reg_number,
        }

    return None
