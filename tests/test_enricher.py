from unittest.mock import AsyncMock, patch

import pytest

from app.services.enricher import verify_organization

MOCK_PROPUBLICA = {
    "organization": {
        "ein": 530196605,
        "name": "AMERICAN NATIONAL RED CROSS",
        "city": "WASHINGTON",
        "state": "DC",
        "subsection_code": 3,
        "ruling_date": "1903-12",
        "ntee_code": "P20",
        "exempt_organization_status_code": 1,
        "updated_at": "2024-01-15T00:00:00-05:00",
    },
    "filings_with_data": [
        {
            "tax_prd_yr": 2023,
            "totrevenue": 3400000000,
            "totfuncexpns": 3200000000,
            "totassetsend": 11000000000,
            "totliabend": 5000000000,
        }
    ],
}

MOCK_FILING_DATA = {
    "officers": [
        {"name": "Jane Doe", "title": "CEO", "compensation": 500000, "hours_per_week": 60.0},
        {"name": "John Smith", "title": "Board Chair", "compensation": 0, "hours_per_week": 2.0},
    ],
    "revenue_breakdown": {
        "contributions_and_grants": 2000000000,
        "program_service_revenue": 1000000000,
        "investment_income": 200000000,
        "other_revenue": 200000000,
        "total_revenue": 3400000000,
    },
    "expense_breakdown": {
        "program_services": 2800000000,
        "management_and_general": 200000000,
        "fundraising": 200000000,
        "total_expenses": 3200000000,
    },
    "schedule_j": [
        {
            "name": "Jane Doe",
            "base_compensation": 400000,
            "bonus_and_incentive": 50000,
            "other_compensation": 30000,
            "deferred_compensation": 10000,
            "nontaxable_benefits": 10000,
            "total_compensation": 500000,
        },
    ],
}


def _patch_enricher():
    """Patch propublica, irs_990, and state_registry in the enricher module."""
    return (
        patch("app.services.enricher.propublica.fetch_organization", new_callable=AsyncMock),
        patch("app.services.enricher.irs_990.get_filing_data", new_callable=AsyncMock),
        patch("app.services.enricher.state_registry.check_all_states", new_callable=AsyncMock),
    )


@pytest.mark.asyncio
async def test_verify_returns_structured_response():
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = MOCK_PROPUBLICA
        mock_990.return_value = MOCK_FILING_DATA
        mock_state.return_value = []
        result = await verify_organization("53-0196605")

    assert result is not None
    assert result.ein == "53-0196605"
    assert result.legal_name == "AMERICAN NATIONAL RED CROSS"
    assert result.status == "active"
    assert result.subsection == "501(c)(3)"
    assert result.revoked is False
    assert result.financials is not None
    assert result.financials.revenue == 3400000000
    assert result.financials.tax_year == 2023
    assert len(result.personnel) == 2
    assert result.personnel[0].name == "Jane Doe"
    assert result.personnel[0].compensation == 500000


@pytest.mark.asyncio
async def test_verify_not_found_returns_none():
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = None
        mock_990.return_value = None
        mock_state.return_value = []
        result = await verify_organization("99-9999999")
    assert result is None


@pytest.mark.asyncio
async def test_verify_no_filings_no_officers():
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = {
            "organization": {
                "ein": 123456789,
                "name": "SMALL ORG",
                "city": "NOWHERE",
                "state": "TX",
                "subsection_code": 3,
                "ruling_date": "2020-01",
                "ntee_code": None,
                "exempt_organization_status_code": 1,
                "updated_at": None,
            },
            "filings_with_data": [],
        }
        mock_990.return_value = None
        mock_state.return_value = []
        result = await verify_organization("12-3456789")

    assert result is not None
    assert result.legal_name == "SMALL ORG"
    assert result.financials is None
    assert result.personnel == []
    assert result.data_sources.irs_990 is None


@pytest.mark.asyncio
async def test_verify_invalid_ein():
    result = await verify_organization("bad-ein")
    assert result is None


@pytest.mark.asyncio
async def test_verify_includes_revenue_breakdown():
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = MOCK_PROPUBLICA
        mock_990.return_value = MOCK_FILING_DATA
        mock_state.return_value = []
        result = await verify_organization("53-0196605")

    assert result.financials is not None
    rb = result.financials.revenue_breakdown
    assert rb is not None
    assert rb.contributions_and_grants == 2000000000
    assert rb.program_service_revenue == 1000000000
    assert rb.investment_income == 200000000
    assert rb.total_revenue == 3400000000

    eb = result.financials.expense_breakdown
    assert eb is not None
    assert eb.program_services == 2800000000
    assert eb.management_and_general == 200000000
    assert eb.fundraising == 200000000
    assert eb.total_expenses == 3200000000


@pytest.mark.asyncio
async def test_verify_schedule_j_attached_to_person():
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = MOCK_PROPUBLICA
        mock_990.return_value = MOCK_FILING_DATA
        mock_state.return_value = []
        result = await verify_organization("53-0196605")

    jane = result.personnel[0]
    assert jane.name == "Jane Doe"
    assert jane.compensation_detail is not None
    assert jane.compensation_detail.base_compensation == 400000
    assert jane.compensation_detail.bonus_and_incentive == 50000
    assert jane.compensation_detail.other_compensation == 30000
    assert jane.compensation_detail.deferred_compensation == 10000
    assert jane.compensation_detail.nontaxable_benefits == 10000
    assert jane.compensation_detail.total_compensation == 500000

    # John Smith has no Schedule J entry
    john = result.personnel[1]
    assert john.compensation_detail is None


@pytest.mark.asyncio
async def test_verify_no_990_data_backward_compat():
    """When get_filing_data returns None, response should still work (backward compat)."""
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = MOCK_PROPUBLICA
        mock_990.return_value = None
        mock_state.return_value = []
        result = await verify_organization("53-0196605")

    assert result is not None
    assert result.financials is not None
    assert result.financials.revenue == 3400000000
    assert result.financials.revenue_breakdown is None
    assert result.financials.expense_breakdown is None
    assert result.personnel == []


@pytest.mark.asyncio
async def test_verify_state_registrations_populated():
    """State registrations flow through from check_all_states to response."""
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = MOCK_PROPUBLICA
        mock_990.return_value = None
        mock_state.return_value = [
            {"state": "CA", "status": "Current", "registration_number": "CT-0012345"},
            {"state": "NY", "status": "Registered (NFP)", "registration_number": "11-30-97"},
        ]
        result = await verify_organization("53-0196605")

    assert result is not None
    assert len(result.state_registrations) == 2
    assert result.state_registrations[0].state == "CA"
    assert result.state_registrations[0].status == "Current"
    assert result.state_registrations[0].registration_number == "CT-0012345"
    assert result.state_registrations[1].state == "NY"
    assert result.state_registrations[1].registration_number == "11-30-97"
    assert result.data_sources.state_registries is not None


@pytest.mark.asyncio
async def test_verify_no_state_registrations():
    """Empty state registrations → data_sources.state_registries is None."""
    p1, p2, p3 = _patch_enricher()
    with p1 as mock_pp, p2 as mock_990, p3 as mock_state:
        mock_pp.return_value = MOCK_PROPUBLICA
        mock_990.return_value = None
        mock_state.return_value = []
        result = await verify_organization("53-0196605")

    assert result is not None
    assert result.state_registrations == []
    assert result.data_sources.state_registries is None
