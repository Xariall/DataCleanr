# Architecture — DataCleanr

## System Overview

Single-container FastAPI service on Railway. No microservices in V1.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client (any language)                     │
│                 curl / Go / Node / Python / Zapier               │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Railway (NIXPACKS, Python 3.11)               │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                     FastAPI (uvicorn)                     │   │
│  │                                                           │   │
│  │  GZipMiddleware (>=1KB)                                   │   │
│  │       ↓                                                   │   │
│  │  AuthMiddleware  ──── SQLite (/data/datacleanr.db)        │   │
│  │       ↓                                                   │   │
│  │  Routes                                                   │   │
│  │   ├── POST /register                                      │   │
│  │   ├── GET  /health                                        │   │
│  │   ├── POST /explain   ──── Redis (row budget check)       │   │
│  │   ├── POST /preview   ──── Claude Haiku (LLM)             │   │
│  │   ├── POST /transform ──── Claude Haiku + Sandbox        │   │
│  │   └── POST /webhook/stripe                                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  /data volume (persistent):                                      │
│    datacleanr.db  ← SQLite WAL mode                              │
└─────────────────────────────────────────────────────────────────┘
         │                      │
         ▼                      ▼
  Upstash Redis           Anthropic API
  (rate limiting)         (Claude Haiku)
         │
         ▼
      Stripe
  (billing webhooks)
```

## Request Flow — POST /transform

```
1. GZipMiddleware        decompress request body if gzipped
2. AuthMiddleware        lookup sha256(X-API-Key) in SQLite → 401 if missing
                         inject request.state.user + request.state.request_id
3. routes._run_transform
   a. validate instructions (empty, too long)
   b. read file bytes → 413 if >10 MB
   c. detect format (CSV/JSON/xlsx via MIME + extension)
   d. parse_to_dataframe() → 400 if unparseable or 0 rows
   e. check_row_budget()   → Redis INCR check → 429 or 503
   f. build_llm_sample()   → header + first 10 rows
   g. _call_claude()       → Claude Haiku, tenacity 3-retry
   h. validate_script()    → AST deny-list + substring scan
   i. execute_script()     → asyncio subprocess (30s timeout)
   j. read output CSV      → 400 if 0 rows
   k. commit_row_usage()   → Redis INCRBY + EXPIRE 86400
   l. return Response(text/csv) with X-DataCleanr-Summary header
```

## Component Map

| File | Responsibility |
|------|---------------|
| `app/main.py` | FastAPI app factory, lifespan (init_db + Sentry), middleware stack |
| `app/database.py` | SQLite connection, schema init, user CRUD, Stripe event idempotency |
| `app/middleware.py` | Auth (X-API-Key), X-Request-Id, Redis rate limit, paid fallback |
| `app/routes.py` | All API endpoints, `_call_claude()` with tenacity, `_run_transform()` |
| `app/format_detect.py` | File parsing (CSV/JSON/xlsx → DataFrame), LLM sample builder |
| `app/sandbox.py` | AST deny-list validator, asyncio subprocess runner |
| `app/webhooks.py` | Stripe event handlers, idempotency guard |

## Data Model

### SQLite — `users` table

```sql
CREATE TABLE users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    email                 TEXT UNIQUE NOT NULL,
    api_key_hash          TEXT UNIQUE NOT NULL,   -- sha256(plaintext_key)
    tier                  TEXT DEFAULT 'FREE',    -- 'FREE' | 'PAID'
    stripe_customer_id    TEXT,
    stripe_subscription_id TEXT,
    payment_failing       INTEGER DEFAULT 0,      -- 1 = invoice failed, not yet cancelled
    created_at            TEXT DEFAULT (datetime('now'))
);
```

### SQLite — `stripe_events` table

```sql
CREATE TABLE stripe_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT UNIQUE NOT NULL,              -- Stripe event_id, INSERT OR IGNORE
    created_at TEXT DEFAULT (datetime('now'))
);
```

### Redis — rate limit keys

```
ratelimit:{api_key_hash}  →  integer (rows used today)
TTL: 86400 seconds (resets daily)
```

## Security Layers

| Layer | What it blocks |
|-------|---------------|
| File size gate | DoS via large files (413 at >10 MB, before any processing) |
| Auth middleware | Unauthenticated access to protected routes |
| Redis rate limit | Free tier Claude API abuse |
| AST deny-list | LLM-generated code importing network/fs/introspection modules |
| Substring scan | Patterns AST misses: `pd.eval(`, `__bases__`, `builtins` |
| Subprocess env strip | Generated code reading env vars (ANTHROPIC_API_KEY, etc.) |
| Stripe sig verification | Webhook replay attacks |
| stripe_events idempotency | Duplicate Stripe event processing |

## Known V1 Limitations

- **SQLite single-writer:** WAL mode handles concurrent reads, but high write concurrency will serialize. Acceptable at V1 traffic.
- **AST bypass vector:** `importlib` was blocked, but string-based dynamic import via `__builtins__` is theoretically possible. Mitigated by substring scan. Full fix: gVisor (V2).
- **In-memory rate limit:** Paid tier Redis fallback stores counter in process memory — resets on restart. Max overshoot = 30 seconds of requests.
- **No backup:** SQLite on Railway volume is not backed up. If volume is lost, user data is lost.
