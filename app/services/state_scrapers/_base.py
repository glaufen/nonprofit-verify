"""Shared utilities for state registry scrapers."""

import httpx

TIMEOUT = 15.0
USER_AGENT = "NonprofitVerify/1.0 (nonprofit verification service)"


def get_client(**kwargs) -> httpx.AsyncClient:
    """Create a configured httpx client for state scraping."""
    return httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        **kwargs,
    )
