from pydantic import BaseModel, Field


class RevenueBreakdown(BaseModel):
    contributions_and_grants: int | None = None
    program_service_revenue: int | None = None
    investment_income: int | None = None
    other_revenue: int | None = None
    total_revenue: int | None = None


class ExpenseBreakdown(BaseModel):
    program_services: int | None = None
    management_and_general: int | None = None
    fundraising: int | None = None
    total_expenses: int | None = None


class CompensationDetail(BaseModel):
    base_compensation: int | None = None
    bonus_and_incentive: int | None = None
    other_compensation: int | None = None
    deferred_compensation: int | None = None
    nontaxable_benefits: int | None = None
    total_compensation: int | None = None


class Financials(BaseModel):
    tax_year: int | None = None
    revenue: int | None = None
    expenses: int | None = None
    assets: int | None = None
    liabilities: int | None = None
    revenue_breakdown: RevenueBreakdown | None = None
    expense_breakdown: ExpenseBreakdown | None = None


class Person(BaseModel):
    name: str
    title: str | None = None
    compensation: int | None = None
    hours_per_week: float | None = None
    compensation_detail: CompensationDetail | None = None


class StateRegistration(BaseModel):
    state: str
    status: str | None = None
    registration_number: str | None = None


class DataSources(BaseModel):
    irs_bmf: str | None = None
    irs_990: str | None = None
    propublica: str | None = None
    state_registries: str | None = None


class VerifyResponse(BaseModel):
    ein: str
    legal_name: str | None = None
    status: str | None = None
    subsection: str | None = None
    ruling_date: str | None = None
    revoked: bool = False
    ntee_code: str | None = None
    city: str | None = None
    state: str | None = None
    financials: Financials | None = None
    personnel: list[Person] = []
    state_registrations: list[StateRegistration] = []
    data_sources: DataSources = DataSources()
    propublica_url: str | None = None


class BatchVerifyRequest(BaseModel):
    eins: list[str] = Field(min_length=1)


class BatchVerifyResult(BaseModel):
    ein: str
    success: bool
    data: VerifyResponse | None = None
    error: str | None = None


class BatchVerifyResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BatchVerifyResult]


class ErrorResponse(BaseModel):
    detail: str
