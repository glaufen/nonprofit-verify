# NonprofitVerify API — Build Plan
## Nonprofit Organization Verification & Data API

**Product Summary:** A REST API that takes an organization name or EIN and returns structured nonprofit data: 501(c)(3) status, annual revenue, program areas, key personnel, recent 990 filings, state registration status, and compliance indicators. A one-stop verification and enrichment endpoint for any platform that touches nonprofit data.

**Competitive Advantage:** Getting structured nonprofit data today requires querying multiple sources (IRS BMF, ProPublica, state registries, GuideStar/Candid) and normalizing the results yourself. NonprofitVerify does this in a single API call with a clean, consistent schema. Candid's API exists but costs $10,000+/year and is designed for enterprise. NonprofitVerify targets the long tail of developers and small platforms that need nonprofit data but can't justify Candid pricing.

**Target Market:**
- Donor-advised fund platforms (need to verify 501(c)(3) status before disbursement)
- Corporate giving/matching platforms (verify employee donation recipients)
- Grant management software (auto-populate applicant data)
- Fintech/banking (due diligence on nonprofit accounts)
- CRM platforms (enrich nonprofit contact records)
- Fundraising platforms (verify org legitimacy)
- Nonprofit job boards (verify posting organizations)

**Revenue Model:**
- Free tier: 100 lookups/month (attracts developers, builds adoption)
- Starter: $49/month (1,000 lookups/month)
- Growth: $149/month (10,000 lookups/month)
- Scale: $499/month (100,000 lookups/month)
- Enterprise: Custom pricing (unlimited, SLA, dedicated support)
- Overage: $0.05 per lookup above plan limit

**Tech Stack:**
- API Server: Node.js + Express (or Fastify for performance)
- Database: PostgreSQL (Supabase) — cache layer for IRS/state data
- Data Sources: IRS BMF files, ProPublica Nonprofit Explorer API, state charity registries
- Cache: Redis (Upstash) — reduce repeated lookups
- Auth: API key-based authentication
- Rate Limiting: Redis-based token bucket
- Documentation: Swagger/OpenAPI + hosted docs page
- Monitoring: PostHog or simple custom analytics
- Payments: Stripe (usage-based billing via metered subscriptions)
- Deployment: Railway or Render (persistent server for API)

---

## PHASE 1 — Core API Server & IRS Data Integration
**Goal:** Build the API server and integrate the primary data source (IRS)

### Directory Structure
```
nonprofit-verify/
├── src/
│   ├── server.ts                    # Express/Fastify server entry
│   ├── routes/
│   │   ├── lookup.ts                # GET /v1/lookup?ein=XX-XXXXXXX
│   │   ├── search.ts                # GET /v1/search?name=Camp+Mak-A-Dream
│   │   ├── batch.ts                 # POST /v1/batch (multiple lookups)
│   │   ├── health.ts                # GET /health
│   │   └── docs.ts                  # Swagger UI redirect
│   ├── services/
│   │   ├── irs-bmf.ts               # IRS Business Master File integration
│   │   ├── propublica.ts            # ProPublica Nonprofit Explorer API
│   │   ├── irs-990.ts               # 990 e-file data (AWS hosted)
│   │   ├── state-registry.ts        # State charity registration scrapers
│   │   ├── org-enricher.ts          # Combines all sources into unified response
│   │   └── name-matcher.ts          # Fuzzy matching for org name searches
│   ├── middleware/
│   │   ├── auth.ts                  # API key validation
│   │   ├── rate-limiter.ts          # Usage tracking + rate limiting
│   │   ├── usage-tracker.ts         # Log every request for billing
│   │   └── error-handler.ts         # Standardized error responses
│   ├── data/
│   │   ├── irs-bmf-loader.ts        # Monthly BMF file download & import
│   │   ├── ntee-codes.ts            # NTEE code → human-readable mapping
│   │   └── state-requirements.ts    # State registration requirements
│   ├── utils/
│   │   ├── ein-validator.ts         # Validate EIN format
│   │   ├── cache.ts                 # Redis caching layer
│   │   ├── logger.ts
│   │   └── response-formatter.ts    # Consistent API response structure
│   └── types/
│       └── index.ts
├── scripts/
│   ├── import-bmf.ts               # Script to download & import IRS BMF
│   ├── seed-test-data.ts
│   └── generate-api-key.ts
├── docs/
│   ├── openapi.yaml                 # OpenAPI 3.0 specification
│   └── examples/
│       ├── lookup-response.json
│       ├── search-response.json
│       └── batch-response.json
├── tests/
│   ├── routes/
│   │   ├── lookup.test.ts
│   │   ├── search.test.ts
│   │   └── batch.test.ts
│   ├── services/
│   │   ├── irs-bmf.test.ts
│   │   └── name-matcher.test.ts
│   └── middleware/
│       ├── auth.test.ts
│       └── rate-limiter.test.ts
├── package.json
├── tsconfig.json
├── .env.example
├── Dockerfile
└── docker-compose.yml              # Local dev: API + PostgreSQL + Redis
```

### Database Schema
```sql
-- Cached organization records (refreshed monthly from IRS BMF)
CREATE TABLE organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ein VARCHAR(10) UNIQUE NOT NULL,       -- XX-XXXXXXX format stored as XXXXXXXXX
  name VARCHAR(500) NOT NULL,
  name_normalized VARCHAR(500),          -- Lowercase, stripped for fuzzy matching
  
  -- IRS BMF data
  irs_status VARCHAR(20),                -- 'active', 'revoked', 'not_found'
  subsection VARCHAR(10),                -- '501(c)(3)', '501(c)(4)', etc.
  classification_codes VARCHAR(100),
  ruling_date VARCHAR(10),               -- YYYYMM
  deductibility VARCHAR(50),             -- 'deductible', 'not_deductible'
  foundation_code VARCHAR(10),
  activity_codes VARCHAR(20),
  organization_type VARCHAR(50),
  
  -- NTEE classification
  ntee_code VARCHAR(10),
  ntee_major VARCHAR(100),               -- Human-readable major category
  ntee_minor VARCHAR(200),               -- Human-readable minor category
  
  -- Location
  street VARCHAR(500),
  city VARCHAR(100),
  state VARCHAR(2),
  zip VARCHAR(10),
  
  -- Financial (from most recent 990)
  revenue_total BIGINT,
  expenses_total BIGINT,
  assets_total BIGINT,
  fiscal_year_end INTEGER,               -- Month (1-12)
  most_recent_990_year INTEGER,
  
  -- Personnel (from 990 Part VII)
  officers JSONB DEFAULT '[]',
  -- [{ name, title, compensation, hours }]
  
  -- State registration
  state_registration JSONB DEFAULT '{}',
  -- { state: { registered: bool, registrationNumber: string, expirationDate: string } }
  
  -- Metadata
  data_sources JSONB DEFAULT '[]',       -- Which sources contributed data
  last_irs_update TIMESTAMPTZ,
  last_990_update TIMESTAMPTZ,
  last_state_update TIMESTAMPTZ,
  confidence_score FLOAT DEFAULT 0,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- API keys
CREATE TABLE api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_hash VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256 of API key
  key_prefix VARCHAR(8) NOT NULL,        -- First 8 chars for identification
  name VARCHAR(255) NOT NULL,            -- "My App - Production"
  email VARCHAR(255) NOT NULL,
  organization VARCHAR(255),
  
  plan VARCHAR(20) DEFAULT 'free',
  monthly_limit INTEGER DEFAULT 100,
  stripe_customer_id VARCHAR(255),
  stripe_subscription_id VARCHAR(255),
  
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  last_used_at TIMESTAMPTZ
);

-- Usage tracking (for billing and analytics)
CREATE TABLE api_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  api_key_id UUID REFERENCES api_keys(id),
  endpoint VARCHAR(50) NOT NULL,         -- 'lookup', 'search', 'batch'
  query JSONB NOT NULL,                  -- { ein: "...", name: "..." }
  response_status INTEGER,
  response_time_ms INTEGER,
  cache_hit BOOLEAN DEFAULT FALSE,
  period_month VARCHAR(7) NOT NULL,      -- '2025-03' for billing period
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Monthly usage aggregates (for billing)
CREATE TABLE usage_aggregates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  api_key_id UUID REFERENCES api_keys(id),
  period_month VARCHAR(7) NOT NULL,
  total_requests INTEGER DEFAULT 0,
  cache_hits INTEGER DEFAULT 0,
  billable_requests INTEGER DEFAULT 0,
  UNIQUE(api_key_id, period_month)
);

-- Indexes
CREATE INDEX idx_orgs_ein ON organizations(ein);
CREATE INDEX idx_orgs_name_normalized ON organizations USING gin(name_normalized gin_trgm_ops);
CREATE INDEX idx_orgs_state ON organizations(state);
CREATE INDEX idx_orgs_ntee ON organizations(ntee_code);
CREATE INDEX idx_usage_key_period ON api_usage(api_key_id, period_month);
CREATE INDEX idx_usage_created ON api_usage(created_at);
```

### API Response Schema
```typescript
// GET /v1/lookup?ein=81-0631303
interface LookupResponse {
  status: 'found' | 'not_found' | 'revoked';
  data: {
    ein: string;                    // "81-0631303"
    name: string;                   // "Children's Oncology Camp Foundation"
    also_known_as: string[];        // ["Camp Mak-A-Dream"]
    
    tax_status: {
      type: string;                 // "501(c)(3)"
      deductibility: string;        // "Contributions are deductible"
      ruling_date: string;          // "1995-06"
      foundation_type: string;      // "Organization which receives a substantial part of its support from a governmental unit or the general public"
      irs_status: string;           // "active"
    };
    
    classification: {
      ntee_code: string;            // "P30"
      ntee_major: string;           // "Human Services"
      ntee_minor: string;           // "Children & Youth Services"
      activity_description: string;
    };
    
    location: {
      street: string;
      city: string;                 // "Gold Creek"
      state: string;                // "MT"
      zip: string;                  // "59733"
    };
    
    financials: {
      fiscal_year_end: number;      // 12
      most_recent_year: number;     // 2023
      revenue: number;              // 2847523
      expenses: number;             // 2654891
      assets: number;               // 3215467
      revenue_trend: {              // Last 3 years if available
        year: number;
        revenue: number;
      }[];
    };
    
    people: {
      name: string;                 // "George Laufenberg"
      title: string;                // "Executive Director"
      compensation: number | null;
      hours_per_week: number | null;
    }[];
    
    compliance: {
      state_registrations: {
        state: string;
        registered: boolean;
        registration_number: string | null;
        expiration_date: string | null;
      }[];
      most_recent_990_filed: string; // "2023"
      consecutive_990s_filed: number; // 5
    };
    
    data_freshness: {
      irs_bmf_date: string;         // "2025-01-15"
      last_990_date: string;        // "2024-03-01"
      state_check_date: string;     // "2025-02-01"
    };
    
    links: {
      irs_determination_letter: string | null;
      propublica_profile: string;
      guidestar_profile: string;
      most_recent_990_pdf: string | null;
    };
  };
  
  meta: {
    request_id: string;
    response_time_ms: number;
    cache_hit: boolean;
    data_sources: string[];         // ["irs_bmf", "propublica", "990_efile"]
  };
}

// GET /v1/search?name=camp+mak&state=MT
interface SearchResponse {
  results: {
    ein: string;
    name: string;
    city: string;
    state: string;
    ntee_major: string;
    revenue: number | null;
    match_score: number;            // 0-1 fuzzy match confidence
  }[];
  total_results: number;
  page: number;
  per_page: number;
  meta: {
    request_id: string;
    response_time_ms: number;
  };
}
```

### Phase 1 Deliverables
- [ ] Express/Fastify server with route structure
- [ ] API key authentication middleware
- [ ] Rate limiting middleware (Redis-based)
- [ ] Usage tracking middleware
- [ ] IRS BMF file downloader and importer (monthly refresh)
- [ ] EIN lookup endpoint (primary use case)
- [ ] Organization name search endpoint (fuzzy matching with pg_trgm)
- [ ] ProPublica API integration for 990 financial data
- [ ] Response formatting and error handling
- [ ] OpenAPI specification
- [ ] Docker Compose for local development
- [ ] Basic test suite

---

## PHASE 2 — 990 E-File Data Integration
**Goal:** Deep financial and personnel data from electronic 990 filings

### Data Source
- IRS 990 e-file data hosted on AWS (free, public)
- XML format with well-defined schema
- Covers ~300,000 organizations per year

### Extracted Fields
- Part I: Revenue, expenses, assets, liabilities (summary)
- Part VII: Officer/director names, titles, compensation, hours
- Part VIII: Revenue breakdown by source
- Part IX: Expense breakdown by functional category
- Schedule J: Detailed executive compensation

### Implementation
- Monthly job to download new 990 e-file indexes from AWS
- Parse XML to extract target fields
- Match to organizations table by EIN
- Store extracted data in JSONB columns
- Compute revenue trend (3-year) for each org

---

## PHASE 3 — State Registration Data
**Goal:** Check state charity registration status

### Priority States (by nonprofit density)
1. California, New York, Texas, Florida, Pennsylvania
2. Illinois, Ohio, Massachusetts, New Jersey, Virginia
3. Remaining states as scrapers are built

### Implementation
- Each state has different registry format (some searchable, some PDF-based)
- Build individual scrapers per state
- Cache results with 30-day refresh
- Return registration status, number, and expiration in API response
- Flag organizations registered in some states but not others

---

## PHASE 4 — Billing & Developer Portal
**Goal:** Self-service API key management and usage-based billing

### Developer Portal Pages
- Sign up / sign in
- API key management (create, revoke, rename)
- Usage dashboard (requests this month, by endpoint, cache hit rate)
- Plan selection and upgrade
- Billing history (Stripe Customer Portal)
- Documentation and API playground

### Stripe Integration
- Metered billing: report usage at end of billing cycle
- Plan limits enforced in real-time via rate limiter
- Overage billing for requests above plan limit
- Webhook handling for subscription events

---

## PHASE 5 — Batch Endpoint & Webhooks
**Goal:** High-volume verification for enterprise customers

### Batch Endpoint
```
POST /v1/batch
Content-Type: application/json

{
  "lookups": [
    { "ein": "81-0631303" },
    { "ein": "13-1837418" },
    { "name": "Red Cross", "state": "DC" }
  ]
}
```
- Process up to 100 lookups per request
- Return partial results (some may fail)
- Async option for large batches (webhook callback when complete)

### Webhooks (Enterprise)
- Configure webhook URLs in developer portal
- Events: organization_status_changed, 990_filed, registration_expired
- Signed webhooks (HMAC) for security

---

## PHASE 6 — Documentation & Marketing Site
**Goal:** Developer-grade documentation and SEO-friendly landing page

### Documentation
- Getting started guide (get API key → make first request in 2 minutes)
- API reference (all endpoints, parameters, response schemas)
- Code examples in Python, JavaScript, Ruby, PHP, cURL
- Webhooks guide
- Rate limits and error codes
- Changelog

### Landing Page
- Hero: "Verify any US nonprofit in one API call"
- Live demo: type an EIN or org name, see real response
- Use cases by industry (fintech, corporate giving, grant management)
- Pricing table
- Developer testimonials (after launch)

---

## PHASE 7 — Testing & Launch
**Goal:** Production-ready API with comprehensive testing

### Testing
- Unit tests: EIN validation, name matching, response formatting
- Integration tests: full lookup flow (IRS → ProPublica → response)
- Load tests: ensure <200ms response time at expected volume
- Security: API key brute force protection, SQL injection, rate limit bypass
- Documentation: all examples actually work

### Launch Sequence
1. Soft launch with free tier — announce on Hacker News, Reddit r/nonprofit
2. Reach out to 10 fintech/nonprofit tech companies for beta testing
3. Write blog post: "Building a Nonprofit Verification API" (developer audience)
4. Submit to API directories (RapidAPI, ProgrammableWeb)
5. LinkedIn posts targeting nonprofit technology professionals
6. Cold outreach to donor-advised fund platforms

---

## CLAUDE CODE KICKOFF PROMPT

```
I'm building NonprofitVerify API — a REST API that returns structured nonprofit data from IRS filings, ProPublica, and state registries. Read nonprofit-verify-build-plan.md for the complete specification.

Start with Phase 1:
1. Initialize a Node.js + TypeScript project with Express
2. Install dependencies: express, @types/express, pg, ioredis, stripe, swagger-ui-express, yamljs, winston, helmet, cors, express-rate-limit, crypto, dotenv, jest, ts-jest, supertest
3. Create the complete directory structure from the build plan
4. Build the Express server with route structure
5. Build API key authentication middleware (SHA-256 hashed keys, lookup from database)
6. Build rate limiting middleware using Redis token bucket
7. Build usage tracking middleware that logs every request
8. Build the IRS BMF integration service (download monthly file, parse, import to PostgreSQL)
9. Build the ProPublica API integration service
10. Build the EIN lookup endpoint that combines IRS BMF + ProPublica data
11. Build the organization name search endpoint with fuzzy matching
12. Build consistent response formatting (match the schema in the build plan)
13. Build error handling middleware with standard error codes
14. Create the database migration file with all tables and indexes
15. Create Docker Compose for local development (API + PostgreSQL + Redis)
16. Write the OpenAPI specification
17. Write initial test suite

Use .env.example for all credentials. The API should be runnable locally with Docker Compose.

After Phase 1, continue to Phase 2 (990 e-file integration).
```

---

## ESTIMATED BUILD TIME
- Core API + IRS integration (Phase 1–2): ~4 hours
- State registrations (Phase 3): ~3 hours (ongoing as states are added)
- Billing + developer portal (Phase 4): ~3 hours
- Batch + webhooks (Phase 5): ~2 hours
- Docs + marketing (Phase 6): ~2 hours
- Testing + launch (Phase 7): ~2 hours
- **Total to functional API: ~16 hours across 1–2 weeks**

## ESTIMATED REVENUE POTENTIAL
- 200 free tier users in month 1 (developer adoption)
- 30 paid users by month 3 at average $100/month = $3,000/month
- 100 paid users by month 12 at average $120/month = $12,000/month
- 1 enterprise contract at $2,000/month = $14,000/month total
- Strong acquisition target for Candid, Every Action, or Bloomerang
