# Task: Show HN Launch

**Priority:** P1
**Status:** Pending
**Depends on:** 01-railway-deploy.md, 02-stripe-setup.md

## Draft Title

"Show HN: REST API to clean CSVs with plain English — works from any language, any pipeline"

## Draft Post

```
DataCleanr: POST a messy CSV/JSON/xlsx file + plain English instructions → get clean CSV back.

No Python required. Works from any stack: Go, Node, Ruby, PHP, no-code tools, shell scripts.

Quick example:
  curl -X POST https://datacleanr-production.up.railway.app/transform \
    -H "X-API-Key: dc_..." \
    -F "file=@customers.csv" \
    -F "instructions=remove rows where email is empty, standardize dates to ISO 8601, deduplicate on email keeping newest row"

Under the hood: Claude Haiku generates a pandas script → AST-sandboxed subprocess runs it → clean CSV returned.

Free tier: 500 rows/day (no credit card). Paid: $9/month for 500K rows/day.

API docs: https://datacleanr-production.up.railway.app/docs

What I'd love feedback on:
- Does the "no Python required" angle resonate? The main competition is PandasAI which requires a local Python install.
- What would make you trust an API with real customer data?
- Would you pay $9/month for this? If not, what price point works?
```

## Checklist before posting

- [x] Live URL working (`/health` → 200)
- [x] `/docs` Swagger UI looks clean
- [x] Free tier test: register + transform small CSV works end-to-end
- [x] Landing page at `/` live
- [ ] Stripe checkout tested (skip — post free tier first, add paid later)
- [ ] Post at 9am PT on a weekday (Mon–Wed for best HN traction)

## Target communities (after HN)

- Indie Hackers (Show IH)
- Twitter/X — tag @levelsio and other indie hackers
- Reddit r/selfhosted, r/Python, r/datascience
- Product Hunt (Week 2 if HN gets traction)
