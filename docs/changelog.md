# Changelog — DataCleanr

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased]

### In Progress
- Railway deploy
- Stripe Product + Checkout link
- GitHub Actions CI/CD

---

## [1.0.0] — 2026-06-18

Initial V1 release. All 46 tests passing. Not yet deployed.

### Added
- `POST /transform` — CSV/JSON/xlsx + plain English instructions → clean CSV
- `POST /preview` — first 10 rows only, no quota deduction, 3s timeout
- `POST /explain` — dry run (no file), returns will/will_not JSON
- `POST /register` — free-tier API key via email
- `GET /health` — Railway healthcheck
- `POST /webhook/stripe` — billing lifecycle (checkout, payment_failed, subscription.deleted)
- SQLite user storage with WAL mode and sha256 API key hashing
- Redis rate limiting: 500 rows/day (free), 500K/day (paid)
- AST deny-list sandbox + asyncio subprocess execution
- GZip middleware (responses ≥1 KB)
- Sentry error monitoring (optional via `SENTRY_DSN`)
- tenacity retry (3 attempts, exponential backoff) on Claude API calls
- X-Request-Id UUID header on all responses
- X-DataCleanr-Summary and X-DataCleanr-Warning response headers
- All error responses include `"try"` field with working cURL example
- LLM eval suite (5 scenarios: dates, nulls, dedup, rename, xlsx)
- Railway deploy config (`railway.toml` with `/data` volume)

### Fixed
- Subprocess runner: user code was being indented causing `IndentationError`
- HTTP headers: em dash `—` caused `UnicodeEncodeError` (replaced with `-`)
- Test file size for "too large" test was under the 10 MB limit (fixed to 12 MB)
- Transform tests: mocked `check_row_budget` and `commit_row_usage` to avoid Redis dependency

### Technical
- Python 3.11+
- FastAPI 0.115+, uvicorn, pandas 2.2+, anthropic 0.40+
- Redis 5.2+, Stripe 11+, tenacity 9+, sentry-sdk 2+
- pytest + pytest-asyncio, 46 tests across 5 test files

---

## [0.1.0] — 2026-06-15

Planning phase complete.

### Added
- Design doc (problem statement, API spec, monetization, constraints)
- CEO review (scope decisions, competitive positioning vs PandasAI, timeline)
- Eng review (architecture decisions E1–E5, test plan, edge cases)
- `docs/PRD.md`, `docs/ADR.md`, `docs/architecture.md`
