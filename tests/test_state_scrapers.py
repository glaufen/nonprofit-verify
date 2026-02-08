"""Tests for state registry scrapers (CA, NY, TX) and orchestrator."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.state_scrapers import check_all_states
from app.services.state_scrapers.california import parse_ca_results
from app.services.state_scrapers.new_york import parse_ny_results
from app.services.state_scrapers.texas import parse_tx_results


# ---------------------------------------------------------------------------
# Sample HTML/JSON fixtures
# ---------------------------------------------------------------------------

CA_RESULTS_HTML = """
<html><body>
<table id="datagrid_results">
<tr>
  <th>Registration Number</th><th>Record Type</th>
  <th>Organization Name</th><th>Registry Status</th>
  <th>City</th><th>State</th><th>FEIN</th>
</tr>
<tr>
  <td>CT-0012345</td><td>Charity</td>
  <td>AMERICAN NATIONAL RED CROSS</td><td>Current</td>
  <td>WASHINGTON</td><td>DC</td><td>530196605</td>
</tr>
</table>
</body></html>
"""

CA_NO_RESULTS_HTML = """
<html><body>
<p>No records found.</p>
</body></html>
"""

CA_MALFORMED_HTML = """
<html><body>
<table id="datagrid_results">
<tr><th>Reg</th><th>Status</th></tr>
<tr><td>CT-999</td></tr>
</table>
</body></html>
"""

NY_RESULTS_HTML = """
<html><body>
<table cellpadding="4" class="Bordered">
<thead>
<tr>
  <th>Organization Name</th><th>NY_Reg#_</th>
  <th>EIN</th><th>Registrant Type</th>
  <th>City</th><th>State</th>
</tr>
</thead>
<tbody>
<tr class="odd">
  <td><u>AMERICAN NATIONAL RED CROSS AND ALL CHAPTERS</u></td>
  <td>11-30-97</td>
  <td>530196605</td>
  <td>NFP</td>
  <td>WASHINGTON</td>
  <td>DC</td>
</tr>
</tbody>
</table>
</body></html>
"""

NY_NO_RESULTS_HTML = """
<html><body>
<p class="pagebanner">No items found.</p>
</body></html>
"""

NY_MALFORMED_HTML = """
<html><body>
<table class="Bordered">
<tr><th>Name</th></tr>
<tr><td>Some Org</td></tr>
</table>
</body></html>
"""

TX_API_RESPONSE = [
    {
        "id": "15301966050",
        "tp_id": "15301966050",
        "name": "AMERICAN RED CROSS",
        "address": "123 MAIN ST",
        "city": "DALLAS",
        "state": "TX",
        "county": "DALLAS",
        "zip": "75201",
        "sales": "SALES",
        "franchise": "FRANCHISE",
        "hotel": "NOT EXEMPT",
        "franchise_code": "19",
        "franchise_desc": "NP 501 (c)(3)",
        "sales_code": "19",
        "sales_desc": "N-P 501(c)(3)",
        "hotel_code": "",
        "hotel_desc": "",
    }
]

TX_EMPTY_RESPONSE = []

TX_UNEXPECTED_FORMAT = [
    {"tp_id": "99999999999", "name": "UNKNOWN"}
]


# ---------------------------------------------------------------------------
# CA parsing unit tests
# ---------------------------------------------------------------------------

class TestCaliforniaParsing:
    def test_parse_with_match(self):
        result = parse_ca_results(CA_RESULTS_HTML, "530196605")
        assert result is not None
        assert result["state"] == "CA"
        assert result["status"] == "Current"
        assert result["registration_number"] == "CT-0012345"

    def test_parse_no_match(self):
        result = parse_ca_results(CA_RESULTS_HTML, "999999999")
        assert result is None

    def test_parse_no_results(self):
        result = parse_ca_results(CA_NO_RESULTS_HTML, "530196605")
        assert result is None

    def test_parse_malformed_rows(self):
        result = parse_ca_results(CA_MALFORMED_HTML, "530196605")
        assert result is None


# ---------------------------------------------------------------------------
# NY parsing unit tests
# ---------------------------------------------------------------------------

class TestNewYorkParsing:
    def test_parse_with_result(self):
        result = parse_ny_results(NY_RESULTS_HTML, "530196605")
        assert result is not None
        assert result["state"] == "NY"
        assert result["status"] == "Registered (NFP)"
        assert result["registration_number"] == "11-30-97"

    def test_parse_no_results(self):
        result = parse_ny_results(NY_NO_RESULTS_HTML, "530196605")
        assert result is None

    def test_parse_malformed_html(self):
        result = parse_ny_results(NY_MALFORMED_HTML, "530196605")
        assert result is None

    def test_parse_no_match(self):
        result = parse_ny_results(NY_RESULTS_HTML, "999999999")
        assert result is None


# ---------------------------------------------------------------------------
# TX parsing unit tests
# ---------------------------------------------------------------------------

class TestTexasParsing:
    def test_parse_with_result(self):
        # tp_id candidate for EIN 530196605 with prefix "1" + EIN + "05" -> won't match
        # Correct: "1" + "530196605" + "0" = "15301966050"
        result = parse_tx_results(TX_API_RESPONSE, "15301966050")
        assert result is not None
        assert result["state"] == "TX"
        assert "Franchise Tax Exempt" in result["status"]
        assert "Sales Tax Exempt" in result["status"]
        assert result["registration_number"] == "15301966050"

    def test_parse_empty_results(self):
        result = parse_tx_results(TX_EMPTY_RESPONSE, "15301966050")
        assert result is None

    def test_parse_no_match(self):
        result = parse_tx_results(TX_UNEXPECTED_FORMAT, "15301966050")
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests (mock httpx + cache)
# ---------------------------------------------------------------------------

def _mock_cache():
    """Return patched cache_get and cache_set as AsyncMocks."""
    return (
        patch("app.services.state_scrapers.california.cache_get", new_callable=AsyncMock),
        patch("app.services.state_scrapers.california.cache_set", new_callable=AsyncMock),
    )


def _mock_ny_cache():
    return (
        patch("app.services.state_scrapers.new_york.cache_get", new_callable=AsyncMock),
        patch("app.services.state_scrapers.new_york.cache_set", new_callable=AsyncMock),
    )


def _mock_tx_cache():
    return (
        patch("app.services.state_scrapers.texas.cache_get", new_callable=AsyncMock),
        patch("app.services.state_scrapers.texas.cache_set", new_callable=AsyncMock),
    )


class TestCaliforniaIntegration:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        from app.services.state_scrapers.california import check_california

        p1, p2 = _mock_cache()
        with p1 as mock_get, p2:
            mock_get.return_value = {"state": "CA", "status": "Current", "registration_number": "CT-123"}
            result = await check_california("530196605")

        assert result is not None
        assert result["state"] == "CA"
        assert result["status"] == "Current"

    @pytest.mark.asyncio
    async def test_cache_hit_not_found(self):
        from app.services.state_scrapers.california import check_california

        p1, p2 = _mock_cache()
        with p1 as mock_get, p2:
            mock_get.return_value = {}  # not-found sentinel
            result = await check_california("999999999")

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_miss_http_success(self):
        from app.services.state_scrapers.california import check_california

        # Mock both cache and httpx
        mock_get_resp = AsyncMock()
        mock_get_resp.status_code = 200
        mock_get_resp.text = """
        <html><body>
        <form>
        <input name="__VIEWSTATE" value="abc"/>
        <input name="__VIEWSTATEGENERATOR" value="def"/>
        <input name="__EVENTVALIDATION" value="ghi"/>
        </form>
        </body></html>
        """

        mock_post_resp = AsyncMock()
        mock_post_resp.status_code = 200
        mock_post_resp.text = CA_RESULTS_HTML

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_get_resp)
        mock_client.post = AsyncMock(return_value=mock_post_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        p1, p2 = _mock_cache()
        with (
            p1 as mock_cache_get,
            p2 as mock_cache_set,
            patch("app.services.state_scrapers.california.get_client", return_value=mock_client),
        ):
            mock_cache_get.return_value = None
            result = await check_california("530196605")

        assert result is not None
        assert result["state"] == "CA"
        assert result["registration_number"] == "CT-0012345"
        mock_cache_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        from app.services.state_scrapers.california import check_california

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        p1, p2 = _mock_cache()
        with (
            p1 as mock_cache_get,
            p2 as mock_cache_set,
            patch("app.services.state_scrapers.california.get_client", return_value=mock_client),
        ):
            mock_cache_get.return_value = None
            result = await check_california("530196605")

        assert result is None
        # Should cache the not-found sentinel
        mock_cache_set.assert_called_once_with("state:CA:530196605", {}, 7 * 24 * 3600)


class TestNewYorkIntegration:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        from app.services.state_scrapers.new_york import check_new_york

        p1, p2 = _mock_ny_cache()
        with p1 as mock_get, p2:
            mock_get.return_value = {"state": "NY", "status": "Registered", "registration_number": "11-30-97"}
            result = await check_new_york("530196605")

        assert result is not None
        assert result["state"] == "NY"

    @pytest.mark.asyncio
    async def test_cache_miss_http_success(self):
        from app.services.state_scrapers.new_york import check_new_york

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.text = NY_RESULTS_HTML

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        p1, p2 = _mock_ny_cache()
        with (
            p1 as mock_cache_get,
            p2 as mock_cache_set,
            patch("app.services.state_scrapers.new_york.get_client", return_value=mock_client),
        ):
            mock_cache_get.return_value = None
            result = await check_new_york("530196605")

        assert result is not None
        assert result["state"] == "NY"
        assert result["registration_number"] == "11-30-97"
        mock_cache_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        from app.services.state_scrapers.new_york import check_new_york

        mock_resp = AsyncMock()
        mock_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        p1, p2 = _mock_ny_cache()
        with (
            p1 as mock_cache_get,
            p2,
            patch("app.services.state_scrapers.new_york.get_client", return_value=mock_client),
        ):
            mock_cache_get.return_value = None
            result = await check_new_york("530196605")

        assert result is None


class TestTexasIntegration:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        from app.services.state_scrapers.texas import check_texas

        p1, p2 = _mock_tx_cache()
        with p1 as mock_get, p2:
            mock_get.return_value = {"state": "TX", "status": "Exempt", "registration_number": "15301966050"}
            result = await check_texas("530196605")

        assert result is not None
        assert result["state"] == "TX"

    @pytest.mark.asyncio
    async def test_cache_miss_no_match(self):
        from app.services.state_scrapers.texas import check_texas

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {"success": True, "data": TX_EMPTY_RESPONSE}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        p1, p2 = _mock_tx_cache()
        with (
            p1 as mock_cache_get,
            p2 as mock_cache_set,
            patch("app.services.state_scrapers.texas.get_client", return_value=mock_client),
        ):
            mock_cache_get.return_value = None
            result = await check_texas("530196605")

        assert result is None
        mock_cache_set.assert_called_once()


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------

class TestOrchestrator:
    """Tests for check_all_states orchestrator.

    The orchestrator uses getattr(module, fn_name) to look up scraper functions,
    so we patch on the individual scraper modules.
    """

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """One scraper throws, others succeed."""
        with (
            patch("app.services.state_scrapers.california.check_california", new_callable=AsyncMock) as mock_ca,
            patch("app.services.state_scrapers.new_york.check_new_york", new_callable=AsyncMock) as mock_ny,
            patch("app.services.state_scrapers.texas.check_texas", new_callable=AsyncMock) as mock_tx,
        ):
            mock_ca.side_effect = RuntimeError("CA site down")
            mock_ny.return_value = {"state": "NY", "status": "Registered", "registration_number": "11-30-97"}
            mock_tx.return_value = None

            results = await check_all_states("530196605")

        assert len(results) == 1
        assert results[0]["state"] == "NY"

    @pytest.mark.asyncio
    async def test_all_none_returns_empty(self):
        """All scrapers return None → empty list."""
        with (
            patch("app.services.state_scrapers.california.check_california", new_callable=AsyncMock) as mock_ca,
            patch("app.services.state_scrapers.new_york.check_new_york", new_callable=AsyncMock) as mock_ny,
            patch("app.services.state_scrapers.texas.check_texas", new_callable=AsyncMock) as mock_tx,
        ):
            mock_ca.return_value = None
            mock_ny.return_value = None
            mock_tx.return_value = None

            results = await check_all_states("530196605")

        assert results == []

    @pytest.mark.asyncio
    async def test_all_found(self):
        """All scrapers return data."""
        with (
            patch("app.services.state_scrapers.california.check_california", new_callable=AsyncMock) as mock_ca,
            patch("app.services.state_scrapers.new_york.check_new_york", new_callable=AsyncMock) as mock_ny,
            patch("app.services.state_scrapers.texas.check_texas", new_callable=AsyncMock) as mock_tx,
        ):
            mock_ca.return_value = {"state": "CA", "status": "Current", "registration_number": "CT-123"}
            mock_ny.return_value = {"state": "NY", "status": "Registered", "registration_number": "11-30-97"}
            mock_tx.return_value = {"state": "TX", "status": "Exempt", "registration_number": "15301966050"}

            results = await check_all_states("530196605")

        assert len(results) == 3
        states = {r["state"] for r in results}
        assert states == {"CA", "NY", "TX"}

    @pytest.mark.asyncio
    async def test_all_scrapers_throw(self):
        """All scrapers throw → empty list, no exception."""
        with (
            patch("app.services.state_scrapers.california.check_california", new_callable=AsyncMock) as mock_ca,
            patch("app.services.state_scrapers.new_york.check_new_york", new_callable=AsyncMock) as mock_ny,
            patch("app.services.state_scrapers.texas.check_texas", new_callable=AsyncMock) as mock_tx,
        ):
            mock_ca.side_effect = RuntimeError("CA down")
            mock_ny.side_effect = RuntimeError("NY down")
            mock_tx.side_effect = RuntimeError("TX down")

            results = await check_all_states("530196605")

        assert results == []
