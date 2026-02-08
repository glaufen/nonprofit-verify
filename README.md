# NonprofitVerify API

REST API for verifying US nonprofit organizations by EIN. Aggregates data from IRS records, ProPublica, and 990 XML e-files into a single response.

## What it returns

- **Tax-exempt status** — active, revoked, or unknown
- **Organization details** — legal name, subsection (e.g. 501(c)(3)), NTEE code, ruling date
- **Financials** — revenue, expenses, assets, liabilities from the most recent filing
- **Revenue breakdown** — contributions/grants, program service revenue, investment income (Part VIII)
- **Expense breakdown** — program services, management/general, fundraising (Part IX)
- **Personnel** — officers, directors, and key employees with compensation (Part VII)
- **Executive compensation detail** — base, bonus, deferred, nontaxable benefits (Schedule J)

## Quick start

### Prerequisites

- Python 3.12+
- PostgreSQL 17
- Redis

### Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Create database
createdb nonprofit_verify
psql -d nonprofit_verify -f migrations/001_initial.sql

# Configure (optional — defaults work for local dev)
cp .env.example .env

# Generate an API key
python scripts/create_api_key.py

# Start the server
uvicorn app.main:app --reload
```

### Usage

```bash
curl -H 'X-Api-Key: npv_your_key_here' http://localhost:8000/api/v1/verify/53-0196605
```

API docs are available at `http://localhost:8000/docs`.

## Example response

```json
{
  "ein": "53-0196605",
  "legal_name": "American National Red Cross",
  "status": "active",
  "subsection": "501(c)(3)",
  "ruling_date": "1938-12-01",
  "revoked": false,
  "ntee_code": "P210",
  "city": "Washington",
  "state": "DC",
  "financials": {
    "tax_year": 2023,
    "revenue": 3217077611,
    "expenses": 2971106889,
    "assets": 4028321133,
    "liabilities": 1008326202,
    "revenue_breakdown": {
      "contributions_and_grants": 919126379,
      "program_service_revenue": 2167924872,
      "investment_income": 82218159,
      "other_revenue": 47808201,
      "total_revenue": 3217077611
    },
    "expense_breakdown": {
      "program_services": 2691201823,
      "management_and_general": 100067599,
      "fundraising": 179837467,
      "total_expenses": 2971106889
    }
  },
  "personnel": [
    {
      "name": "Gail Mcgovern",
      "title": "PRESIDENT & CEO",
      "compensation": 873211,
      "hours_per_week": 60.0,
      "compensation_detail": null
    }
  ],
  "data_sources": {
    "irs_bmf": "2026-01-22",
    "irs_990": "2023",
    "propublica": "2026-02-07"
  }
}
```

## Data sources

| Source | What it provides | Auth |
|--------|-----------------|------|
| [ProPublica Nonprofit Explorer](https://projects.propublica.org/nonprofits/) | Org details, status, summary financials | None |
| [IRS 990 XML e-files](https://www.irs.gov/charities-non-profits/form-990-series-downloads) | Officers, revenue/expense breakdowns, Schedule J compensation | None |

990 XML files are fetched from IRS bulk ZIP archives using HTTP range requests ([remotezip](https://github.com/gtsystem/python-remotezip)), pulling ~100-200 KB per filing instead of downloading the full ~200 MB archive.

## Architecture

- **FastAPI** + uvicorn
- **PostgreSQL** — API keys and usage tracking
- **Redis** — response caching (7-day TTL, 24h for 404s)
- API key auth via `X-Api-Key` header
- Rate limiting (100 requests/month on free tier)

## Tests

```bash
pytest tests/ -v
```

## License

MIT
