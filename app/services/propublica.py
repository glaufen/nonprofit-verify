import httpx

PROPUBLICA_BASE = "https://projects.propublica.org/nonprofits/api/v2"


async def fetch_organization(ein_digits: str) -> dict | None:
    """Fetch organization data from ProPublica Nonprofit Explorer API.

    Args:
        ein_digits: EIN as 9 digits (no dash).

    Returns:
        Full API response dict, or None if not found / error.
    """
    url = f"{PROPUBLICA_BASE}/organizations/{ein_digits}.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError:
            return None
