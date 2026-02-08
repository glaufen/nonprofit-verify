from datetime import date

from app.models.schemas import (
    CompensationDetail,
    DataSources,
    ExpenseBreakdown,
    Financials,
    Person,
    RevenueBreakdown,
    StateRegistration,
    VerifyResponse,
)
from app.services import irs_990, propublica, state_registry
from app.utils.ein import ein_to_digits, validate_ein

SUBSECTION_MAP = {
    3: "501(c)(3)",
    4: "501(c)(4)",
    5: "501(c)(5)",
    6: "501(c)(6)",
    7: "501(c)(7)",
    8: "501(c)(8)",
    9: "501(c)(9)",
    10: "501(c)(10)",
    13: "501(c)(13)",
    14: "501(c)(14)",
    19: "501(c)(19)",
}

# Exempt org status codes that indicate active status.
# ProPublica returns these as integers (1, 2, ...).
ACTIVE_STATUS_CODES = {1, 2, "01", "02", "1", "2"}


async def verify_organization(ein_raw: str) -> VerifyResponse | None:
    """Fetch and combine data from all sources for a given EIN."""
    normalized = validate_ein(ein_raw)
    if not normalized:
        return None

    digits = ein_to_digits(normalized)

    # Primary data source: ProPublica (includes IRS BMF data)
    pp_data = await propublica.fetch_organization(digits)
    if not pp_data:
        return None

    org = pp_data.get("organization", {})
    filings = pp_data.get("filings_with_data", [])

    # ProPublica returns stub records for any EIN — detect by checking key fields
    if not org.get("subsection_code") and not org.get("ruling_date") and org.get("name") == "Unknown Organization":
        return None

    # Status — ProPublica returns status_code as int or string depending on org
    raw_status = org.get("exempt_organization_status_code")
    has_status = raw_status is not None and raw_status != ""
    status = "active" if raw_status in ACTIVE_STATUS_CODES else ("unknown" if not has_status else "revoked")
    revoked = has_status and raw_status not in ACTIVE_STATUS_CODES

    # Subsection
    sub_code = org.get("subsection_code")
    subsection = SUBSECTION_MAP.get(sub_code)
    if subsection is None and sub_code is not None:
        subsection = f"501(c)({sub_code})"

    # 990 XML filing data (officers, revenue/expense breakdown, schedule J)
    filing_data = await irs_990.get_filing_data(digits)

    revenue_breakdown = None
    expense_breakdown = None
    schedule_j_map: dict[str, dict] = {}
    if filing_data:
        if filing_data.get("revenue_breakdown"):
            revenue_breakdown = RevenueBreakdown(**filing_data["revenue_breakdown"])
        if filing_data.get("expense_breakdown"):
            expense_breakdown = ExpenseBreakdown(**filing_data["expense_breakdown"])
        # Build case-insensitive lookup for Schedule J compensation
        for entry in filing_data.get("schedule_j") or []:
            schedule_j_map[entry["name"].lower()] = entry

    # Financials from most recent filing
    financials = None
    if filings:
        f = filings[0]
        financials = Financials(
            tax_year=f.get("tax_prd_yr"),
            revenue=f.get("totrevenue"),
            expenses=f.get("totfuncexpns"),
            assets=f.get("totassetsend"),
            liabilities=f.get("totliabend"),
            revenue_breakdown=revenue_breakdown,
            expense_breakdown=expense_breakdown,
        )
    elif revenue_breakdown or expense_breakdown:
        # 990 XML data exists but no ProPublica filings
        financials = Financials(
            revenue_breakdown=revenue_breakdown,
            expense_breakdown=expense_breakdown,
        )

    # Personnel from 990 XML e-files
    personnel = []
    officers_data = filing_data.get("officers") if filing_data else None
    if officers_data:
        for p in officers_data:
            comp_detail = None
            sj = schedule_j_map.get(p["name"].lower())
            if sj:
                comp_detail = CompensationDetail(
                    base_compensation=sj.get("base_compensation"),
                    bonus_and_incentive=sj.get("bonus_and_incentive"),
                    other_compensation=sj.get("other_compensation"),
                    deferred_compensation=sj.get("deferred_compensation"),
                    nontaxable_benefits=sj.get("nontaxable_benefits"),
                    total_compensation=sj.get("total_compensation"),
                )
            personnel.append(Person(**p, compensation_detail=comp_detail))

    # State registrations (stub — Phase 4)
    state_reg_data = await state_registry.check_all_states(digits)
    state_regs = [StateRegistration(**sr) for sr in state_reg_data]

    # Data source timestamps
    updated_raw = org.get("updated_at") or ""
    irs_bmf_date = updated_raw[:10] if len(updated_raw) >= 10 else None
    data_sources = DataSources(
        propublica=date.today().isoformat(),
        irs_bmf=irs_bmf_date,
        irs_990=str(filings[0]["tax_prd_yr"]) if filings and "tax_prd_yr" in filings[0] else None,
    )

    return VerifyResponse(
        ein=normalized,
        legal_name=org.get("name"),
        status=status,
        subsection=subsection,
        ruling_date=org.get("ruling_date"),
        revoked=revoked,
        ntee_code=org.get("ntee_code"),
        city=org.get("city"),
        state=org.get("state"),
        financials=financials,
        personnel=personnel,
        state_registrations=state_regs,
        data_sources=data_sources,
        propublica_url=f"https://projects.propublica.org/nonprofits/organizations/{digits}",
    )
