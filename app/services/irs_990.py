"""IRS 990 XML e-file parser.

Fetches 990 XML e-files from IRS bulk data (hosted as ZIP archives) and
extracts officer/director/key employee data from Part VII Section A.

The IRS publishes e-file data in yearly ZIP archives. Each year has an index
CSV mapping EINs to OBJECT_IDs and ZIP filenames. We use the `remotezip`
library to extract individual XMLs without downloading the full archive
(~200 MB per ZIP), pulling only the central directory + target file (~100-200 KB).

Index URL pattern:
    https://apps.irs.gov/pub/epostcard/990/xml/{year}/index_{year}.csv

ZIP URL pattern:
    https://apps.irs.gov/pub/epostcard/990/xml/{year}/{zip_filename}.zip
"""

import csv
import io
import logging
import xml.etree.ElementTree as ET

import httpx
from remotezip import RemoteZip

from app.utils.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

IRS_XML_BASE = "https://apps.irs.gov/pub/epostcard/990/xml"
IRS_NS = {"irs": "http://www.irs.gov/efile"}

# Cache parsed filing data for 30 days (990 data is annual)
FILING_CACHE_TTL = 30 * 24 * 3600


async def get_filing_data(ein_digits: str) -> dict | None:
    """Get all parsed 990 data for an EIN from XML e-files.

    Returns dict with keys: officers, revenue_breakdown, expense_breakdown, schedule_j
    Returns None if no 990 XML data available.
    """
    cache_key = f"990filing:{ein_digits}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached if cached != {} else None

    for year in _recent_years():
        filing_info = await _search_year_index(ein_digits, year)
        if not filing_info:
            continue

        filing_data = await _fetch_and_parse_all(filing_info)
        if filing_data:
            await cache_set(cache_key, filing_data, FILING_CACHE_TTL)
            return filing_data

    await cache_set(cache_key, {}, FILING_CACHE_TTL)
    return None


async def get_officers(ein_digits: str) -> list[dict] | None:
    """Get officers/directors/key employees for an EIN.

    Backward-compatible wrapper around get_filing_data().
    """
    filing_data = await get_filing_data(ein_digits)
    if filing_data is None:
        return None
    officers = filing_data.get("officers")
    return officers if officers else None


async def _find_filing(ein_digits: str) -> dict | None:
    """Search IRS e-file indexes to find the most recent 990 filing for an EIN.

    Returns {year, object_id, zip_filename} or None.
    """
    # Check index cache first
    index_cache_key = f"990index:{ein_digits}"
    cached = await cache_get(index_cache_key)
    if cached is not None:
        return cached if cached != {} else None

    # Search recent years (most recent first)
    for year in _recent_years():
        result = await _search_year_index(ein_digits, year)
        if result:
            await cache_set(index_cache_key, result, FILING_CACHE_TTL)
            return result

    await cache_set(index_cache_key, {}, FILING_CACHE_TTL)
    return None


def _recent_years() -> list[int]:
    """Return recent years to search, most recent first."""
    from datetime import date

    current = date.today().year
    # Check current year and 2 prior years
    return [current, current - 1, current - 2]


async def _search_year_index(ein_digits: str, year: int) -> dict | None:
    """Stream-search an IRS yearly index CSV for a specific EIN.

    The index CSVs are 50-200 MB, so we stream and search line by line.
    We look for 990 filings only (not 990-T, 990-PF, etc).
    """
    url = f"{IRS_XML_BASE}/{year}/index_{year}.csv"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None

                best_match = None
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if ein_digits not in line:
                            continue

                        parts = line.split(",")
                        if len(parts) < 10:
                            continue

                        # CSV: RETURN_ID,FILING_TYPE,EIN,TAX_PERIOD,SUB_DATE,NAME,RETURN_TYPE,DLN,OBJECT_ID,ZIP_FILE
                        filing_ein = parts[2].strip()
                        return_type = parts[6].strip()
                        object_id = parts[8].strip()
                        zip_filename = parts[9].strip() if len(parts) > 9 else None

                        if filing_ein == ein_digits and return_type == "990":
                            best_match = {
                                "year": year,
                                "object_id": object_id,
                                "zip_filename": zip_filename,
                                "tax_period": parts[3].strip(),
                            }
                            # Don't break — keep scanning for the latest filing

                return best_match
    except Exception as e:
        logger.warning("Failed to search %s index: %s", year, e)
        return None


async def _fetch_and_parse_all(filing_info: dict) -> dict | None:
    """Fetch a 990 XML from an IRS ZIP archive and parse all sections.

    Uses remotezip to download only the specific file from the archive
    (~100-200 KB instead of ~200 MB).
    """
    year = filing_info["year"]
    object_id = filing_info["object_id"]
    zip_filename = filing_info.get("zip_filename")

    if not zip_filename:
        return None

    zip_url = f"{IRS_XML_BASE}/{year}/{zip_filename}.zip"
    xml_candidates = [
        f"{zip_filename}/{object_id}_public.xml",
        f"{object_id}_public.xml",
    ]

    try:
        with RemoteZip(zip_url) as z:
            names = z.namelist()
            xml_name = None
            for candidate in xml_candidates:
                if candidate in names:
                    xml_name = candidate
                    break
            if not xml_name:
                logger.warning("XML for %s not found in %s", object_id, zip_url)
                return None
            xml_data = z.read(xml_name)

        return _parse_all_from_xml(xml_data)
    except Exception as e:
        logger.warning("Failed to fetch/parse 990 XML: %s", e)
        return None


def _parse_all_from_xml(xml_data: bytes) -> dict:
    """Parse all supported sections from 990 XML in a single pass."""
    root = ET.fromstring(xml_data)
    return {
        "officers": _parse_officers(root),
        "revenue_breakdown": _parse_revenue_breakdown(root),
        "expense_breakdown": _parse_expense_breakdown(root),
        "schedule_j": _parse_schedule_j(root),
    }


def _parse_officers_from_xml(xml_data: bytes) -> list[dict]:
    """Parse Part VII Section A from 990 XML bytes. Kept for test compatibility."""
    root = ET.fromstring(xml_data)
    return _parse_officers(root)


def _parse_officers(root: ET.Element) -> list[dict]:
    """Parse Part VII Section A (Officers/Directors/Key Employees) from parsed root."""
    officers = root.findall(".//irs:Form990PartVIISectionAGrp", IRS_NS)
    if not officers:
        return []

    result = []
    for person in officers:
        name_el = person.find("irs:PersonNm", IRS_NS)
        biz_name_el = person.find(".//irs:BusinessNameLine1Txt", IRS_NS)
        title_el = person.find("irs:TitleTxt", IRS_NS)
        comp_el = person.find("irs:ReportableCompFromOrgAmt", IRS_NS)
        other_comp_el = person.find("irs:OtherCompensationAmt", IRS_NS)
        hours_el = person.find("irs:AverageHoursPerWeekRt", IRS_NS)

        name = (
            name_el.text
            if name_el is not None
            else (biz_name_el.text if biz_name_el is not None else None)
        )
        if not name:
            continue

        comp = _parse_int(comp_el)
        other_comp = _parse_int(other_comp_el)
        has_comp_data = comp_el is not None or other_comp_el is not None
        total_comp = (comp + other_comp) if has_comp_data else None

        result.append(
            {
                "name": _title_case(name),
                "title": title_el.text.strip() if title_el is not None and title_el.text else None,
                "compensation": total_comp,
                "hours_per_week": float(hours_el.text) if hours_el is not None and hours_el.text else None,
            }
        )

    return result


def _parse_revenue_breakdown(root: ET.Element) -> dict | None:
    """Parse Part VIII revenue breakdown from parsed root."""
    fields = {
        "contributions_and_grants": "CYContributionsGrantsAmt",
        "program_service_revenue": "CYProgramServiceRevenueAmt",
        "investment_income": "CYInvestmentIncomeAmt",
        "other_revenue": "CYOtherRevenueAmt",
        "total_revenue": "CYTotalRevenueAmt",
    }
    result = {}
    found_any = False
    for key, tag in fields.items():
        el = root.find(f".//irs:{tag}", IRS_NS)
        val = _parse_int_or_none(el)
        result[key] = val
        if val is not None:
            found_any = True
    return result if found_any else None


def _parse_expense_breakdown(root: ET.Element) -> dict | None:
    """Parse Part IX functional expense breakdown from parsed root."""
    grp = root.find(".//irs:TotalFunctionalExpensesGrp", IRS_NS)
    if grp is None:
        return None

    return {
        "program_services": _parse_int_or_none(grp.find("irs:ProgramServicesAmt", IRS_NS)),
        "management_and_general": _parse_int_or_none(grp.find("irs:ManagementAndGeneralAmt", IRS_NS)),
        "fundraising": _parse_int_or_none(grp.find("irs:FundraisingAmt", IRS_NS)),
        "total_expenses": _parse_int_or_none(grp.find("irs:TotalAmt", IRS_NS)),
    }


def _parse_schedule_j(root: ET.Element) -> list[dict]:
    """Parse Schedule J (Compensation Information) from parsed root."""
    entries = root.findall(".//irs:RptCmpOrganizationGrp", IRS_NS)
    if not entries:
        return []

    result = []
    for entry in entries:
        name_el = entry.find("irs:PersonNm", IRS_NS)
        biz_name_el = entry.find(".//irs:BusinessNameLine1Txt", IRS_NS)

        name = (
            name_el.text
            if name_el is not None
            else (biz_name_el.text if biz_name_el is not None else None)
        )
        if not name:
            continue

        base = _parse_int_or_none(entry.find("irs:BaseCompensationFilingOrgAmt", IRS_NS))
        bonus = _parse_int_or_none(entry.find("irs:BonusFilingOrganizationAmount", IRS_NS))
        other = _parse_int_or_none(entry.find("irs:OtherCompensationFilingOrgAmt", IRS_NS))
        deferred = _parse_int_or_none(entry.find("irs:DeferredCompensationFlngOrgAmt", IRS_NS))
        nontax = _parse_int_or_none(entry.find("irs:NontaxableBenefitsFilingOrgAmt", IRS_NS))
        total = _parse_int_or_none(entry.find("irs:TotalCompensationFilingOrgAmt", IRS_NS))

        result.append({
            "name": _title_case(name),
            "base_compensation": base,
            "bonus_and_incentive": bonus,
            "other_compensation": other,
            "deferred_compensation": deferred,
            "nontaxable_benefits": nontax,
            "total_compensation": total,
        })

    return result


def _parse_int(el) -> int:
    """Safely parse an XML element's text as int, defaulting to 0."""
    if el is not None and el.text:
        try:
            return int(float(el.text))
        except (ValueError, TypeError):
            return 0
    return 0


def _parse_int_or_none(el) -> int | None:
    """Parse an XML element's text as int, returning None for missing elements."""
    if el is not None and el.text:
        try:
            return int(float(el.text))
        except (ValueError, TypeError):
            return None
    return None


def _title_case(s: str) -> str:
    """Convert ALL CAPS name to Title Case."""
    if s and s == s.upper():
        return s.title()
    return s
