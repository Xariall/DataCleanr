# Architecture Decision Records — DataCleanr

Each ADR captures one architectural decision: context (why the question arose),
decision (what we chose), consequences (what it costs and what it enables).
Status: **Accepted** unless marked Superseded.

---

## ADR-001: SQLite over PostgreSQL for user storage

**Status:** Accepted
**Date:** 2026-06-15 (CEO Review)

**Context:**
Need to store user accounts, API keys, and billing state. Options were
PostgreSQL (managed, relational) vs SQLite (embedded, zero-ops).

**Decision:**
SQLite in WAL mode on a Railway persistent volume at `/data/datacleanr.db`.

**Consequences:**
- Zero ops cost — no managed database service to pay for or maintain
- Survives Railway redeploys because the `/data` volume persists
- WAL mode (`PRAGMA journal_mode=WAL`) enables concurrent reads without blocking writes
- Single-node only — no horizontal scaling. Acceptable for V1 traffic
- If the Railway volume is lost, all user data is lost (no backups in V1)
- Migration path: swap `sqlite3` for `asyncpg` + PostgreSQL when concurrent write load justifies it

---

## ADR-002: sha256(key) stored, plaintext returned once

**Status:** Accepted
**Date:** 2026-06-18 (Eng Review / Outside Voice)

**Context:**
API keys must be stored in SQLite for lookup on every request. Options:
- Store plaintext (simple, reversible — leaking DB = leaking all keys)
- Store bcrypt hash (secure, but bcrypt is slow for per-request lookup)
- Store sha256 hash (fast lookup, one-way)

**Decision:**
Store `sha256(api_key)` in SQLite. Return the plaintext key exactly once at
`POST /register`. No recovery path — if lost, user must re-register.

**Consequences:**
- DB leak does not expose usable API keys
- Lookup is fast (sha256 is O(1) for fixed-length keys)
- No key recovery UX — explicitly a feature: forces users to store the key safely
- Format: `"dc_" + secrets.token_urlsafe(32)` — 43 bytes of entropy, `dc_` prefix for easy grep

---

## ADR-003: Redis fail-closed for free tier

**Status:** Accepted
**Date:** 2026-06-15 (CEO Review, D8 cross-model tension)

**Context:**
When Redis is unavailable, the rate limiter cannot check the daily row quota.
Two options:
- **Fail-open:** allow the request (user gets free Claude API calls)
- **Fail-closed:** return 503 (user is blocked)

An earlier draft chose fail-open as "better UX." Outside voice overturned this.

**Decision:**
Free tier: fail-closed → 503 `SERVICE_UNAVAILABLE`.
Paid tier: 30-second in-memory sliding-window fallback (see ADR-004).

**Consequences:**
- Free tier users see a 503 during Redis outage — bad UX, acceptable trade-off
- Protects Claude API budget: without this, a Redis outage = unlimited free LLM calls
- Sentry alert fires on Redis failure so the outage is visible
- Paid users are not penalized (ADR-004 covers their fallback)

---

## ADR-004: In-memory fallback for paid tier Redis outage

**Status:** Accepted
**Date:** 2026-06-18 (Outside Voice)

**Context:**
ADR-003 makes free tier fail-closed. Paid users pay $9/month — a 503 during
a Redis outage would be a significant SLA violation for them.

**Decision:**
Paid tier uses a 30-second in-memory sliding-window counter (`_paid_fallback` dict
in `app/middleware.py`) when Redis is unavailable. Window resets on Redis recovery.

**Consequences:**
- Paid users can overshoot their daily 500K limit during a Redis outage (TOCTOU)
- Worst case: 30 seconds of unchecked paid requests — acceptable for V1
- Memory overhead is negligible (one int per paid user per 30-second window)
- No persistent state: in-memory fallback resets on process restart

---

## ADR-005: AST deny-list sandbox (not gVisor/nsjail)

**Status:** Accepted (V1), Superseded in V2
**Date:** 2026-06-15 (CEO Review, Section 3)

**Context:**
The LLM generates Python code that runs on the server. Full container isolation
(gVisor, nsjail) would be ideal but requires Linux kernel features and adds
infra complexity incompatible with Railway's single-container NIXPACKS deploy.

**Decision:**
Two-layer AST-based sandbox:
1. **AST deny-list** — parse the script, reject if it imports blocked modules
   (`pickle`, `ctypes`, `requests`, `socket`, `subprocess`, `os`, `sys`, `pathlib`,
   `io`, `importlib`, `threading`, `multiprocessing`, etc.) or calls blocked
   functions (`eval`, `exec`, `compile`, `__import__`, `open`, `getattr`, `setattr`)
2. **Substring scan** — reject if raw code contains `pd.eval(`, `.query(`, `pd.read_`,
   `__class__`, `__bases__`, `__subclasses__`, `builtins`
3. **Subprocess isolation** — run in a child process with env stripped to
   `PATH=/usr/bin:/bin:/usr/local/bin` and no other env vars

**Consequences:**
- Prevents the most obvious attack vectors: network calls, filesystem access, shell exec
- Known bypass: `pickle.loads()` via base64-encoded string in a variable — not blocked by AST
  (the import is blocked, but a crafty LLM could use `importlib` before that was denied)
- Acceptable for V1 because the LLM prompt explicitly tells Claude not to do this,
  and the output is reviewed against the deny-list
- V2: replace with gVisor or a dedicated sandbox container

---

## ADR-006: User code at top-level of subprocess template (not indented)

**Status:** Accepted
**Date:** 2026-06-18 (Bug fix during implementation)

**Context:**
The sandbox runner wraps user code in a template:
```python
import sys, pandas as pd, numpy as np
df = pd.read_csv(sys.argv[1])
{code}
df.to_csv(sys.argv[2], index=False)
```
An earlier version indented `{code}` by 4 spaces (as if inside a function body).
This caused `IndentationError` in the subprocess for any correctly-formatted user code.

**Decision:**
Insert `{code}` at the top level, with no indentation added by the template renderer.
`_RUNNER_TEMPLATE.replace("{code}", code)` — no `textwrap.indent()`.

**Consequences:**
- User code runs at module scope, same as the surrounding template
- `df` and `pd`/`np` are available as module-level names — no scoping issues
- User code that defines functions or classes works correctly (they're defined at top-level)

---

## ADR-007: Stripe dunning — two-event lifecycle

**Status:** Accepted
**Date:** 2026-06-18 (Eng Review E3 + Outside Voice)

**Context:**
Stripe sends multiple events during a billing failure:
1. `invoice.payment_failed` — first failure
2. `customer.subscription.deleted` — after grace period, subscription cancelled

An earlier draft downgraded to FREE on the first `invoice.payment_failed`.

**Decision:**
- `invoice.payment_failed` → set `payment_failing=1` flag only. **No tier change.**
- `invoice.payment_succeeded` → clear `payment_failing=0` flag.
- `customer.subscription.deleted` → set `tier=FREE`. This is the only downgrade event.

**Consequences:**
- Users get Stripe's full retry grace period (typically 4 attempts over ~2 weeks)
  before losing paid access
- `payment_failing` flag is available for future use (e.g., show a warning in API response)
- Simpler than managing a grace period manually — Stripe handles the retry schedule
- Two-event idempotency required: `record_stripe_event()` uses `INSERT OR IGNORE`
  on `stripe_event_id` to prevent duplicate processing

---

## ADR-008: /preview requires API key, no quota deduction

**Status:** Accepted
**Date:** 2026-06-18 (Eng Review E5)

**Context:**
`/preview` is a free trust-building endpoint (see first 10 rows before paying quota).
Two options:
- No auth required (truly free, maximizes trial usage)
- Auth required, but no quota deduction

**Decision:**
Auth required (`X-API-Key`), no quota deduction.

**Consequences:**
- Prevents anonymous abuse of Claude API (each preview call = one LLM call)
- Still accessible to all free-tier users at zero row cost
- New users must call `/register` first — one extra step, but acceptable friction
- Subprocess timeout is 3s (vs 30s for `/transform`) to limit resource use

---

## ADR-009: HTTP headers must be ASCII/latin-1

**Status:** Accepted
**Date:** 2026-06-18 (Bug fix during implementation)

**Context:**
`X-DataCleanr-Warning` header originally contained an em dash: `"Removed 67% of rows — verify instructions"`.
FastAPI raises `UnicodeEncodeError: 'latin-1' codec can't encode character '—'`
because HTTP/1.1 headers are latin-1 encoded.

**Decision:**
All HTTP header values use only ASCII characters. Replace `—` with `-` in all header strings.

**Consequences:**
- Header values are slightly less typographically clean
- No `UnicodeEncodeError` in production
- Rule applies to all future header values: `X-DataCleanr-Summary`, `X-DataCleanr-Stats`,
  `X-DataCleanr-Warning`

---

## ADR-010: Railway over Vercel for hosting

**Status:** Accepted
**Date:** 2026-06-15 (Design Doc)

**Context:**
Deployment platform options: Railway, Vercel, Render, Fly.io.

**Decision:**
Railway with NIXPACKS build system.

**Consequences:**
- Railway supports persistent volumes (`/data` mount) — SQLite DB survives redeploys
- Railway supports long-running Python processes — no 10s serverless timeout
- Railway supports large file uploads (10 MB) — no Vercel body size limit
- Railway free tier has execution limits; production needs paid plan (~$5/month)
- NIXPACKS auto-detects Python + `requirements.txt` — no Dockerfile needed

---

## ADR-011: Claude Haiku as default LLM

**Status:** Accepted
**Date:** 2026-06-15 (Design Doc)

**Context:**
LLM options: Claude Haiku (fast, cheap), Claude Sonnet (better quality, 5-10x cost).

**Decision:**
`claude-haiku-4-5-20251001` as default. Configurable via `CLAUDE_MODEL` env var.

**Consequences:**
- Estimated cost: <$0.005 per `/transform` request at V1 row limits
- Haiku is sufficient for structured code generation from a template prompt
- Sonnet opt-in available via env var — useful for debugging complex transformations
- If Haiku model is deprecated, update the env var default — no code change needed

---

## ADR-012: $9/month flat subscription in V1

**Status:** Accepted
**Date:** 2026-06-15 (CEO Review)

**Context:**
Billing options: pay-per-use ($0.01/1K rows) vs flat subscription ($9/month).

**Decision:**
V1: $9/month flat only. Pay-per-use deferred to V2.

**Consequences:**
- Stripe metered billing adds UX complexity (subscription + usage record + invoice)
- Flat subscription is simpler: one Checkout Session, one webhook to handle
- Predictable revenue for the operator
- 500K rows/day at $9/month is extremely generous — may need to lower limit or raise price

---

## ADR-013: Test mocking strategy — never hit real Redis in unit tests

**Status:** Accepted
**Date:** 2026-06-18 (Implementation)

**Context:**
Tests need to verify `/transform` behavior without a running Redis instance.

**Decision:**
- `app.routes.check_row_budget` → `AsyncMock(return_value=(True, 0, 500))`
- `app.routes.commit_row_usage` → `AsyncMock()`
- `app.routes._call_claude` → `AsyncMock(return_value=<code string>)`

Tests that need Redis behavior (rate limiting) use `app.middleware._get_redis`
directly with `patch` and `side_effect=Exception("Redis down")`.

**Consequences:**
- Tests run without any external services (no Redis, no Stripe, no Anthropic API)
- LLM quality tested separately in `tests/evals/eval_suite.py` (requires real API key)
- Mock paths must match the module where the function is *used*, not where it's *defined*:
  `patch("app.routes.check_row_budget")` not `patch("app.middleware.check_row_budget")`
