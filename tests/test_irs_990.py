import xml.etree.ElementTree as ET

import pytest

from app.services.irs_990 import (
    _parse_all_from_xml,
    _parse_expense_breakdown,
    _parse_officers_from_xml,
    _parse_revenue_breakdown,
    _parse_schedule_j,
    _title_case,
    IRS_NS,
)

SAMPLE_990_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<Return xmlns="http://www.irs.gov/efile" returnVersion="2022v5.0">
  <ReturnData>
    <IRS990>
      <Form990PartVIISectionAGrp>
        <PersonNm>JANE DOE</PersonNm>
        <TitleTxt>Executive Director</TitleTxt>
        <ReportableCompFromOrgAmt>125000</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>15000</OtherCompensationAmt>
        <AverageHoursPerWeekRt>40.00</AverageHoursPerWeekRt>
      </Form990PartVIISectionAGrp>
      <Form990PartVIISectionAGrp>
        <PersonNm>JOHN SMITH</PersonNm>
        <TitleTxt>Board Chair</TitleTxt>
        <ReportableCompFromOrgAmt>0</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>0</OtherCompensationAmt>
        <AverageHoursPerWeekRt>2.00</AverageHoursPerWeekRt>
      </Form990PartVIISectionAGrp>
      <Form990PartVIISectionAGrp>
        <BusinessName>
          <BusinessNameLine1Txt>ACME CONSULTING LLC</BusinessNameLine1Txt>
        </BusinessName>
        <TitleTxt>Fiscal Agent</TitleTxt>
        <ReportableCompFromOrgAmt>50000</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>0</OtherCompensationAmt>
        <AverageHoursPerWeekRt>0.00</AverageHoursPerWeekRt>
      </Form990PartVIISectionAGrp>
    </IRS990>
  </ReturnData>
</Return>"""

SAMPLE_990_XML_FULL = b"""<?xml version="1.0" encoding="utf-8"?>
<Return xmlns="http://www.irs.gov/efile" returnVersion="2022v5.0">
  <ReturnData>
    <IRS990>
      <Form990PartVIISectionAGrp>
        <PersonNm>JANE DOE</PersonNm>
        <TitleTxt>Executive Director</TitleTxt>
        <ReportableCompFromOrgAmt>125000</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>15000</OtherCompensationAmt>
        <AverageHoursPerWeekRt>40.00</AverageHoursPerWeekRt>
      </Form990PartVIISectionAGrp>
      <Form990PartVIISectionAGrp>
        <PersonNm>JOHN SMITH</PersonNm>
        <TitleTxt>Board Chair</TitleTxt>
        <ReportableCompFromOrgAmt>0</ReportableCompFromOrgAmt>
        <OtherCompensationAmt>0</OtherCompensationAmt>
        <AverageHoursPerWeekRt>2.00</AverageHoursPerWeekRt>
      </Form990PartVIISectionAGrp>
      <CYContributionsGrantsAmt>2000000</CYContributionsGrantsAmt>
      <CYProgramServiceRevenueAmt>500000</CYProgramServiceRevenueAmt>
      <CYInvestmentIncomeAmt>100000</CYInvestmentIncomeAmt>
      <CYOtherRevenueAmt>50000</CYOtherRevenueAmt>
      <CYTotalRevenueAmt>2650000</CYTotalRevenueAmt>
      <TotalFunctionalExpensesGrp>
        <ProgramServicesAmt>1800000</ProgramServicesAmt>
        <ManagementAndGeneralAmt>300000</ManagementAndGeneralAmt>
        <FundraisingAmt>200000</FundraisingAmt>
        <TotalAmt>2300000</TotalAmt>
      </TotalFunctionalExpensesGrp>
    </IRS990>
    <IRS990ScheduleJ>
      <RptCmpOrganizationGrp>
        <PersonNm>JANE DOE</PersonNm>
        <BaseCompensationFilingOrgAmt>120000</BaseCompensationFilingOrgAmt>
        <BonusFilingOrganizationAmount>5000</BonusFilingOrganizationAmount>
        <OtherCompensationFilingOrgAmt>10000</OtherCompensationFilingOrgAmt>
        <DeferredCompensationFlngOrgAmt>3000</DeferredCompensationFlngOrgAmt>
        <NontaxableBenefitsFilingOrgAmt>2000</NontaxableBenefitsFilingOrgAmt>
        <TotalCompensationFilingOrgAmt>140000</TotalCompensationFilingOrgAmt>
      </RptCmpOrganizationGrp>
    </IRS990ScheduleJ>
  </ReturnData>
</Return>"""


def test_parse_officers_basic():
    officers = _parse_officers_from_xml(SAMPLE_990_XML)
    assert len(officers) == 3

    ed = officers[0]
    assert ed["name"] == "Jane Doe"
    assert ed["title"] == "Executive Director"
    assert ed["compensation"] == 140000  # 125000 + 15000
    assert ed["hours_per_week"] == 40.0


def test_parse_officers_board_member():
    officers = _parse_officers_from_xml(SAMPLE_990_XML)
    board = officers[1]
    assert board["name"] == "John Smith"
    assert board["title"] == "Board Chair"
    assert board["compensation"] == 0
    assert board["hours_per_week"] == 2.0


def test_parse_officers_business_name():
    officers = _parse_officers_from_xml(SAMPLE_990_XML)
    biz = officers[2]
    assert biz["name"] == "Acme Consulting Llc"
    assert biz["title"] == "Fiscal Agent"


def test_parse_officers_empty_xml():
    xml = b"""<?xml version="1.0"?>
    <Return xmlns="http://www.irs.gov/efile">
      <ReturnData><IRS990></IRS990></ReturnData>
    </Return>"""
    officers = _parse_officers_from_xml(xml)
    assert officers == []


def test_title_case_all_caps():
    assert _title_case("GAIL MCGOVERN") == "Gail Mcgovern"


def test_title_case_already_mixed():
    assert _title_case("Jane O'Brien") == "Jane O'Brien"


def test_title_case_single_word():
    assert _title_case("PRESIDENT") == "President"


# --- Revenue Breakdown Tests ---


def test_parse_revenue_breakdown():
    root = ET.fromstring(SAMPLE_990_XML_FULL)
    result = _parse_revenue_breakdown(root)
    assert result is not None
    assert result["contributions_and_grants"] == 2000000
    assert result["program_service_revenue"] == 500000
    assert result["investment_income"] == 100000
    assert result["other_revenue"] == 50000
    assert result["total_revenue"] == 2650000


def test_parse_revenue_breakdown_missing():
    xml = b"""<?xml version="1.0"?>
    <Return xmlns="http://www.irs.gov/efile">
      <ReturnData><IRS990></IRS990></ReturnData>
    </Return>"""
    root = ET.fromstring(xml)
    result = _parse_revenue_breakdown(root)
    assert result is None


# --- Expense Breakdown Tests ---


def test_parse_expense_breakdown():
    root = ET.fromstring(SAMPLE_990_XML_FULL)
    result = _parse_expense_breakdown(root)
    assert result is not None
    assert result["program_services"] == 1800000
    assert result["management_and_general"] == 300000
    assert result["fundraising"] == 200000
    assert result["total_expenses"] == 2300000


def test_parse_expense_breakdown_missing():
    xml = b"""<?xml version="1.0"?>
    <Return xmlns="http://www.irs.gov/efile">
      <ReturnData><IRS990></IRS990></ReturnData>
    </Return>"""
    root = ET.fromstring(xml)
    result = _parse_expense_breakdown(root)
    assert result is None


# --- Schedule J Tests ---


def test_parse_schedule_j():
    root = ET.fromstring(SAMPLE_990_XML_FULL)
    result = _parse_schedule_j(root)
    assert len(result) == 1
    entry = result[0]
    assert entry["name"] == "Jane Doe"
    assert entry["base_compensation"] == 120000
    assert entry["bonus_and_incentive"] == 5000
    assert entry["other_compensation"] == 10000
    assert entry["deferred_compensation"] == 3000
    assert entry["nontaxable_benefits"] == 2000
    assert entry["total_compensation"] == 140000


def test_parse_schedule_j_missing():
    xml = b"""<?xml version="1.0"?>
    <Return xmlns="http://www.irs.gov/efile">
      <ReturnData><IRS990></IRS990></ReturnData>
    </Return>"""
    root = ET.fromstring(xml)
    result = _parse_schedule_j(root)
    assert result == []


# --- parse_all Tests ---


def test_parse_all_returns_all_sections():
    result = _parse_all_from_xml(SAMPLE_990_XML_FULL)
    assert "officers" in result
    assert "revenue_breakdown" in result
    assert "expense_breakdown" in result
    assert "schedule_j" in result
    assert len(result["officers"]) == 2
    assert result["revenue_breakdown"]["total_revenue"] == 2650000
    assert result["expense_breakdown"]["total_expenses"] == 2300000
    assert len(result["schedule_j"]) == 1


def test_parse_all_empty_xml():
    xml = b"""<?xml version="1.0"?>
    <Return xmlns="http://www.irs.gov/efile">
      <ReturnData><IRS990></IRS990></ReturnData>
    </Return>"""
    result = _parse_all_from_xml(xml)
    assert result["officers"] == []
    assert result["revenue_breakdown"] is None
    assert result["expense_breakdown"] is None
    assert result["schedule_j"] == []
