"""California Attorney General — Registry of Charitable Trusts scraper.

Searches rct.doj.ca.gov by FEIN. The site is an ASP.NET WebForms app,
so we first GET the search page to obtain fresh __VIEWSTATE and
__EVENTVALIDATION tokens, then POST the search form.

Results table columns: Registration Number, Record Type, Organization Name,
Registry Status, City, State, FEIN.
"""

import logging
import re

from bs4 import BeautifulSoup

from app.services.state_scrapers._base import get_client
from app.utils.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

SEARCH_URL = "https://rct.doj.ca.gov/Verification/Web/Search.aspx?facility=Y"
CACHE_TTL = 7 * 24 * 3600  # 7 days


async def check_california(ein_digits: str) -> dict | None:
    """Check California AG Registry of Charitable Trusts by FEIN.

    Returns dict with state/status/registration_number, or None.
    """
    cache_key = f"state:CA:{ein_digits}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached if cached != {} else None

    result = await _scrape(ein_digits)
    await cache_set(cache_key, result or {}, CACHE_TTL)
    return result


async def _scrape(ein_digits: str) -> dict | None:
    """Perform the two-step ASP.NET form search."""
    try:
        async with get_client() as client:
            # Step 1: GET the page to obtain viewstate tokens
            get_resp = await client.get(SEARCH_URL)
            if get_resp.status_code != 200:
                logger.warning("CA search GET returned %s", get_resp.status_code)
                return None

            tokens = _extract_asp_tokens(get_resp.text)
            if not tokens:
                logger.warning("CA search: could not extract ASP.NET tokens")
                return None

            # Step 2: POST with FEIN
            form_data = {
                **tokens,
                "t_web_lookup__federal_id": ein_digits,
                "t_web_lookup__license_no": "",
                "t_web_lookup__charter_number": "",
                "t_web_lookup__full_name": "",
                "t_web_lookup__doing_business_as": "",
                "t_web_lookup__profession_name": "",
                "t_web_lookup__license_type_name": "",
                "t_web_lookup__license_status_name": "",
                "sch_button": "Search",
            }
            post_resp = await client.post(SEARCH_URL, data=form_data)
            if post_resp.status_code != 200:
                logger.warning("CA search POST returned %s", post_resp.status_code)
                return None

            return parse_ca_results(post_resp.text, ein_digits)
    except Exception:
        logger.exception("CA scraper failed for EIN %s", ein_digits)
        return None


def _extract_asp_tokens(html: str) -> dict | None:
    """Extract __VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    tokens = {}
    for field_name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": field_name})
        if el and el.get("value"):
            tokens[field_name] = el["value"]
        else:
            return None
    return tokens


def parse_ca_results(html: str, ein_digits: str) -> dict | None:
    """Parse the CA search results HTML for a matching FEIN.

    The results table has columns:
    Registration Number | Record Type | Organization Name | Registry Status | City | State | FEIN
    """
    soup = BeautifulSoup(html, "html.parser")

    # Look for datagrid results table
    table = soup.find("table", {"id": re.compile(r"datagrid", re.I)})
    if not table:
        # Try any table with registration number header
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
            if any("registration" in h for h in headers) and any("status" in h for h in headers):
                table = t
                break

    if not table:
        return None

    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        texts = [c.get_text(strip=True) for c in cells]

        # Try to find the FEIN column and match
        fein_match = False
        for text in texts:
            cleaned = re.sub(r"\D", "", text)
            if cleaned == ein_digits:
                fein_match = True
                break

        if not fein_match:
            continue

        # Extract registration number (first column) and status
        reg_number = texts[0] if texts[0] else None
        status = texts[3] if len(texts) > 3 else None

        return {
            "state": "CA",
            "status": status,
            "registration_number": reg_number,
        }

    return None
