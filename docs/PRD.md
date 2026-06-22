# PRD: DataCleanr — AI-Powered Data Transformation API

**Status:** V1 shipped (46/46 tests, pending Railway deploy)
**Last updated:** 2026-06-22
**Author:** Asan
**Sources:** `/office-hours` design doc (2026-06-15), `/plan-ceo-review` (2026-06-15), `/plan-eng-review` (2026-06-18)

---

## Problem Statement

Developers and data analysts spend hours every week on repetitive ETL tasks: normalizing column names, filling nulls, standardizing date formats, removing duplicates, reshaping CSVs. Every project re-invents the same 20 transformations from scratch.

Existing tools require either:
- **Python + local install** (PandasAI, pandas, OpenRefine) — unusable from Go/Node/Ruby/no-code pipelines
- **Manual chat** (ChatGPT) — can't be called by a cron job or embedded in a pipeline

**The gap:** a language-agnostic REST endpoint that accepts a file + plain English instructions and returns clean data. Any stack can call it.

---

## Target User

**Primary (V1):** Developers who need to embed data cleaning into their own applications or automated pipelines — regardless of their tech stack.

**Why not data analysts?** Data analysts do manual cleanup; developers need it embedded. API-first targets developers.

**First specific user type (open question):** Go/Node developer with a data ingestion pipeline, or Python developer who already knows PandasAI pain? Answer this before writing landing page copy.

---

## Positioning

**Headline:** "Clean messy CSV data in plain English. No Python required. POST to our API from any language."

**The actual moat vs PandasAI (YC-backed, 7M downloads):**
- PandasAI requires Python + local library execution
- DataCleanr is a language-agnostic REST endpoint — Go, Node, Ruby, PHP, Zapier, Bubble.io can all call it

**Competitive landscape:**

| Tool | Requires Python | Embeddable in pipeline | Describes in English |
|------|----------------|----------------------|---------------------|
| pandas | Yes | Yes (if Python) | No |
| PandasAI | Yes | Yes (if Python) | Yes |
| OpenRefine | No | No (GUI only) | No |
| ChatGPT | No | No (chat only) | Yes |
| **DataCleanr** | **No** | **Yes (REST API)** | **Yes** |

---

## V1 Scope

### In (shipped)

| Feature | Endpoint | Notes |
|---------|----------|-------|
| Transform file | `POST /transform` | CSV/JSON/xlsx in, clean CSV out |
| Preview (10 rows) | `POST /preview` | No quota deduction, 3s timeout |
| Dry-run explain | `POST /explain` | No file needed, costs 1 row |
| Free registration | `POST /register` | Email only, no payment |
| Health check | `GET /health` | Railway healthcheck |
| Stripe webhooks | `POST /webhook/stripe` | Billing lifecycle |

### Out (deferred to V2+)

| Feature | Reason deferred |
|---------|----------------|
| Named/saved transformations | Requires templates table — platform inflection point |
| `mode=diff` change log | Nice DX, not blocking launch |
| Pay-per-use tier | Stripe metered billing adds UX complexity |
| Email verification on /register | Add only if abuse occurs |
| gVisor/nsjail sandbox | V1 subprocess + env isolation is adequate |
| Multi-language SDKs | Document the API well instead |
| Webhook callbacks for large files | V2 |
| GitHub Actions CD | `railway up` manual for now |

---

## API Spec (V1)

### Authentication

All protected routes require `X-API-Key: <key>` header. Missing/invalid → 401.

Free-tier key: `POST /register` — accepts `{"email": "..."}`, returns `{"api_key": "dc_..."}` once. No recovery path.

Paid key: On `checkout.session.completed` Stripe webhook, flip user record to `PAID` tier.

### Endpoints

#### `POST /transform`

```
Content-Type: multipart/form-data

Fields:
  file          required  CSV/JSON/xlsx, max 10 MB
  instructions  required  plain English, max 2000 chars

Response 200:
  Content-Type: text/csv
  X-DataCleanr-Summary: "Removed 2 rows, 1 rows remaining"
  X-DataCleanr-Warning: "Removed 67% of input rows - verify instructions"  (if >30%)

Error codes:
  400  EMPTY_INSTRUCTIONS, INSTRUCTIONS_TOO_LONG, INVALID_FILE, EMPTY_FILE,
       EMPTY_RESULT, BLOCKED_INSTRUCTIONS, UNINTERPRETABLE_INSTRUCTIONS
  401  MISSING_API_KEY, INVALID_API_KEY
  413  FILE_TOO_LARGE
  429  RATE_LIMIT_EXCEEDED
  502  LLM_UNAVAILABLE, TRANSFORM_TIMEOUT, TRANSFORM_FAILED
  503  SERVICE_UNAVAILABLE (Redis down, free tier)
```

All error responses include a `"try"` field with a working cURL example.

#### `POST /preview`

Same as `/transform` but:
- Slices input to first 10 rows before sending to LLM
- Subprocess timeout: 3s (vs 30s)
- Does NOT deduct from row quota
- Requires `X-API-Key` (prevents free Claude API abuse)

#### `POST /explain`

```
Content-Type: multipart/form-data
Fields:
  instructions  required  plain English

Response 200:
  {"will": "...", "will_not": "..."}

Costs 1 row against daily quota (same as /transform, prevents abuse).
```

#### `POST /register`

```
Content-Type: application/json
{"email": "user@example.com"}

Response 200:
  {"api_key": "dc_...", "message": "Store this key safely — it will not be shown again."}

Errors: 400 INVALID_EMAIL, 409 EMAIL_EXISTS
```

### Execution Model

```
File upload
  → format detection (CSV/JSON/xlsx via MIME + extension)
  → parse to DataFrame (max 10 MB, first sheet for xlsx)
  → build LLM sample (header + first 10 rows as CSV string)
  → Claude Haiku: generates pandas script
  → AST deny-list validation
  → asyncio subprocess (stripped env, temp files, timeout)
  → validate output (0 rows → 400, >30% removed → warning)
  → return CSV
```

**LLM noop marker:** If Claude cannot interpret instructions, it returns `# DataCleanr-noop: true` → API returns 400 `UNINTERPRETABLE_INSTRUCTIONS`.

**Sandbox:** subprocess with env stripped to `PATH=/usr/bin:/bin:/usr/local/bin`. Input/output via temp files in `tempfile.TemporaryDirectory()`. AST deny-list blocks network, filesystem, and introspection imports before exec.

---

## Rate Limiting

| Tier | Rows/day | Redis failure |
|------|----------|--------------|
| FREE | 500 | 503 (fail-closed) |
| PAID ($9/month) | 500,000 | 30s in-memory fallback |

Counter key: `ratelimit:{api_key_hash}`. Redis `INCR` + `EXPIRE 86400`.

**Note on free tier limit:** 500 rows/day may be too low to validate on real datasets. Consider raising to 5,000 rows for the first 90 days to drive signups and feedback, then lower once paid conversion is validated.

---

## Monetization

**V1:** $9/month flat subscription via Stripe Checkout. 500K rows/day.

**Billing lifecycle:**
1. User clicks upgrade link → Stripe Checkout (no-code Payment Link)
2. `checkout.session.completed` → set `tier=PAID` in SQLite
3. `invoice.payment_failed` → set `payment_failing=1` flag (no downgrade yet)
4. `customer.subscription.deleted` → set `tier=FREE`

---

## Infrastructure

| Component | Choice | Why |
|-----------|--------|-----|
| Hosting | Railway | Supports persistent volumes, long-running processes, large file uploads |
| Database | SQLite (WAL mode) on Railway volume | Zero ops, survives redeploys via `/data` volume |
| Cache/rate-limit | Upstash Redis | Serverless Redis, free tier, Railway-native |
| LLM | Claude Haiku | Fast, cheap (<$0.005/request at V1 limits) |
| Error monitoring | Sentry | Free tier, FastAPI integration |
| Billing | Stripe | Industry standard, webhook-driven |

**Not Vercel:** Vercel doesn't support long-running Python processes or large file uploads.

---

## Success Criteria

| Milestone | Target |
|-----------|--------|
| V1 deployed publicly | Within 14 days of start |
| 3 real developers call `/transform` | First 2 weeks post-launch |
| First paying customer | Within 30 days of launch |
| HN Show HN | ≥50 upvotes OR ≥3 meaningful comments from non-Python devs |
| Portfolio | API callable during a technical interview |

---

## Launch Plan

1. **Deploy:** `railway up` + Stripe webhook URL configured
2. **Copy:** Fix landing page headline (PandasAI repositioning: "No Python required")
3. **Channel:** Show HN — "Show HN: REST API to clean CSVs with plain English — works from any language, any pipeline"
4. **Follow-up:** RapidAPI listing at week 3+ after traction confirmed

---

## Open Questions

1. **First specific user type** — Go/Node dev or Python dev who already knows PandasAI? Changes the landing page copy and demo data.
2. **Free tier row limit** — raise to 5,000/day for first 90 days?
3. **`/upgrade` endpoint** — Stripe Payment Link (no-code) or custom `/upgrade` redirect in V1?
