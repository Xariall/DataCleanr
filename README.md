# DataCleanr

**POST a messy CSV/JSON/xlsx + plain English → get clean CSV back.**

No Python required. One curl command. Works from any stack.

**Live:** https://datacleanr-production.up.railway.app

---

## Quick start

```bash
# 1. Register (free, no credit card)
curl -X POST https://datacleanr-production.up.railway.app/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com"}'
# → {"api_key": "dc_...", "next_step": "..."}

# 2. Clean your data
curl -X POST https://datacleanr-production.up.railway.app/transform \
  -H "X-API-Key: dc_YOUR_KEY" \
  -F "file=@customers.csv" \
  -F "instructions=remove rows where email is empty, standardize dates to ISO 8601, deduplicate on email keeping newest" \
  -o clean.csv
```

**Free tier:** 500 rows/day, no credit card.

---

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | No | Landing page |
| `POST` | `/register` | No | Get an API key |
| `GET` | `/me` | Yes | Your tier + daily usage |
| `POST` | `/transform` | Yes | Transform a file |
| `POST` | `/preview` | Yes | Dry-run on first 10 rows (no quota) |
| `POST` | `/explain` | Yes | Explain what a transform will do |
| `GET` | `/health` | No | Status check |
| `GET` | `/docs` | No | Swagger UI |

---

## Examples

### Standardize dates

```bash
curl -X POST .../transform \
  -H "X-API-Key: dc_..." \
  -F "file=@orders.csv" \
  -F "instructions=standardize all date columns to ISO 8601 (YYYY-MM-DD)" \
  -o orders_clean.csv
```

### Remove nulls + deduplicate

```bash
curl -X POST .../transform \
  -H "X-API-Key: dc_..." \
  -F "file=@users.csv" \
  -F "instructions=remove rows where more than 50% of columns are empty; deduplicate on email keeping the most recent row" \
  -o users_clean.csv
```

### Preview before committing (no quota used)

```bash
curl -X POST .../preview \
  -H "X-API-Key: dc_..." \
  -F "file=@big_file.csv" \
  -F "instructions=rename columns to snake_case" \
  -o preview.csv
```

### Check your usage

```bash
curl https://datacleanr-production.up.railway.app/me \
  -H "X-API-Key: dc_..."
# → {"email":"...", "tier":"FREE", "rows_used_today":42, "rows_limit_today":500}
```

---

## How it works

```
POST /transform
  ↓
Auth (X-API-Key SHA-256 lookup in SQLite)
  ↓
Rate limit check (Redis INCR, 500 rows/day free)
  ↓
Parse file → pandas DataFrame (CSV / JSON / xlsx, max 10 MB)
  ↓
Build sample (header + 10 rows) → Gemini 2.5-flash generates pandas code
  ↓
AST deny-list validation (no eval, no file I/O, no network)
  ↓
asyncio subprocess with stripped env + 30s timeout
  ↓
Return clean CSV with X-DataCleanr-Summary header
```

### Security

Generated code is validated by an AST deny-list before execution:

- **Blocked imports:** `os`, `sys`, `subprocess`, `socket`, `requests`, `httpx`, `pickle`, `ctypes`, and more
- **Blocked calls:** `eval`, `exec`, `open`, `__import__`, `getattr`, `setattr`
- **Blocked patterns:** `pd.eval()`, `.query()`, `pd.read_*()`, `__subclasses__`, `mro()`
- Runs in a subprocess with stripped environment variables (no secrets leaked)

---

## Response headers

| Header | Example |
|--------|---------|
| `X-DataCleanr-Summary` | `Removed 12 rows, 88 rows remaining` |
| `X-DataCleanr-Warning` | `Removed 45% of input rows - verify instructions` |
| `X-Request-Id` | `550e8400-e29b-41d4-a716-446655440000` |

---

## Error codes

| Code | HTTP | Meaning |
|------|------|---------|
| `MISSING_API_KEY` | 401 | No `X-API-Key` header |
| `INVALID_API_KEY` | 401 | Key not found |
| `INVALID_EMAIL` | 400 | Bad email on register |
| `EMPTY_INSTRUCTIONS` | 400 | Blank instructions |
| `FILE_TOO_LARGE` | 413 | > 10 MB |
| `INVALID_FILE` | 400 | Unparseable file |
| `RATE_LIMIT_EXCEEDED` | 429 | Daily quota exhausted |
| `BLOCKED_INSTRUCTIONS` | 400 | AST deny-list triggered |
| `UNINTERPRETABLE_INSTRUCTIONS` | 400 | LLM couldn't parse instructions |
| `EMPTY_RESULT` | 400 | Transform removed all rows |
| `LLM_UNAVAILABLE` | 502 | Gemini API error (after 3 retries) |
| `TRANSFORM_TIMEOUT` | 502 | Subprocess > 30s |
| `TRANSFORM_FAILED` | 502 | Subprocess exited non-zero |

---

## Self-hosting

```bash
git clone https://github.com/Xariall/DataCleanr
cd DataCleanr
pip install -r requirements.txt
cp .env.example .env
# edit .env — set GEMINI_API_KEY and REDIS_URL
uvicorn app.main:app --reload
```

Run tests:

```bash
python -m pytest tests/ --ignore=tests/evals -v
```

---

## Stack

- **FastAPI** — async Python API
- **Gemini 2.5-flash** — code generation (via `google-genai`)
- **pandas** — DataFrame transformations
- **SQLite** (WAL mode) — users + API keys
- **Redis** — daily rate limiting
- **Railway** — hosting + persistent volume
