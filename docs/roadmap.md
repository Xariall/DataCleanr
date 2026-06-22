# Roadmap — DataCleanr

## V1 — Shipped ✅

**Goal:** Working paid API, deployed on Railway, first real user.

| Feature | Status |
|---------|--------|
| `POST /transform` — CSV/JSON/xlsx + instructions → clean CSV | ✅ Done |
| `POST /preview` — 10 rows, no quota, fast | ✅ Done |
| `POST /explain` — dry run without file | ✅ Done |
| `POST /register` — free-tier API key | ✅ Done |
| `GET /health` | ✅ Done |
| SQLite + WAL mode (users + billing) | ✅ Done |
| Redis rate limiting (fail-closed free / in-memory paid) | ✅ Done |
| AST sandbox + subprocess isolation | ✅ Done |
| Stripe webhooks (dunning, idempotency) | ✅ Done |
| Sentry error monitoring | ✅ Done (optional, via env var) |
| 46/46 tests | ✅ Done |
| PRD, ADR, architecture docs | ✅ Done |

**Remaining before first user:**
- [ ] Railway deploy (`railway up` + env vars)
- [ ] Stripe Product + Checkout link ($9/month)
- [ ] Stripe webhook URL configured
- [ ] Show HN post

---

## V1.1 — Post-Launch Fixes (after first 10 users)

**Goal:** Fix what real users break. No new features until feedback is gathered.

- [ ] GitHub Actions → Railway auto-deploy (CI/CD)
- [ ] SQLite daily backup to S3 or Railway backup
- [ ] Raise free tier to 5,000 rows/day for first 90 days (if signups are slow)
- [ ] `/upgrade` redirect endpoint → Stripe Checkout (currently requires manual Payment Link)
- [ ] Email verification on `/register` (only if spam occurs)
- [ ] `mode=diff` on `/transform` — returns change log alongside CSV
- [ ] Rate limit keyed on email (not just API key) to prevent key rotation abuse

---

## V2 — Platform Features (after $500 MRR)

**Goal:** Turn DataCleanr into a sticky platform, not just a stateless API.

### Named Transformations (Platform Inflection Point)
Save a transformation by name, call it by name:
```bash
# Save
POST /transformations
{"name": "clean_customer_emails", "instructions": "remove rows where email is empty, lowercase all emails"}

# Apply
POST /transform?transformation=clean_customer_emails
```
Requires a `transformations` table in SQLite. This is the moment the product
compounds: each user's saved transformations make the product more valuable.

### Security Upgrade
- Replace subprocess sandbox with gVisor or a dedicated sandbox container
- Block `pickle.loads()` via base64 string (current AST bypass vector)

### Metered Billing Tier
- Pay-per-use: $0.01/1K rows (via Stripe metered subscription)
- Free: 500 rows/day (unchanged)
- Paid flat: $9/month, 500K rows/day (unchanged)
- Metered: no subscription, pay as you go

### Webhooks for Large Files
- Async mode: POST large file → receive job ID → GET result when ready
- Required for files >1 MB with complex transformations (30s timeout is tight)

### Multi-Language SDKs
- Python SDK (thin wrapper around httpx)
- Node.js SDK
- Go SDK

---

## V3 — Enterprise (after $2K MRR)

**Goal:** Land first team account.

- Team API keys (shared quota across a team)
- Audit log (who called what, when, with what instructions)
- Transformation library (browse community transformations)
- SLA guarantees (99.9% uptime, dedicated support)
- SOC 2 Type I (if required by enterprise prospects)
- Postgres migration (replace SQLite for multi-region writes)

---

## Deferred Indefinitely

| Feature | Why deferred |
|---------|-------------|
| Chat-style interface | ChatGPT already does this. Wedge is API, not chat. |
| Browser extension | Wrong audience. Developers use APIs. |
| Self-hosted version | Undermines subscription revenue. |
| Custom LLM (fine-tuned) | Not worth it until Haiku quality becomes a bottleneck. |
