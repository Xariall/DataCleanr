# Task: Show HN Launch

**Priority:** P1
**Status:** Ready to post
**Depends on:** ~~02-stripe-setup.md~~ (removed dependency — posting free tier first)

## Draft Title

"Show HN: REST API to clean CSVs with plain English — no Python, works from any stack"

## Draft Post

```
DataCleanr: POST a messy CSV/JSON/xlsx file + plain English → get clean CSV back.

No Python required. One curl command from any stack.

  curl -X POST https://datacleanr-production.up.railway.app/transform \
    -H "X-API-Key: dc_..." \
    -F "file=@customers.csv" \
    -F "instructions=remove rows where email is empty, standardize dates to ISO 8601, deduplicate on email keeping newest row" \
    -o clean.csv

Register free (no credit card):
  curl -X POST https://datacleanr-production.up.railway.app/register \
    -H "Content-Type: application/json" \
    -d '{"email":"you@example.com"}'

Under the hood: Gemini 2.5-flash generates a pandas script → AST-sandboxed subprocess runs it → clean CSV returned.

Free tier: 500 rows/day. API docs: https://datacleanr-production.up.railway.app/docs

What I'd love feedback on:
- Does the "no Python required" angle resonate? Main competition is PandasAI which needs a local Python env.
- What would make you trust an API with real customer data?
- What data cleaning tasks do you do manually that you wish were automated?
```

## Checklist before posting

- [x] Live URL working (`/health` → 200)
- [x] `/docs` Swagger UI clean
- [x] Free tier: register + transform works end-to-end
- [x] Landing page at `/` live
- [x] GET /me shows tier + usage
- [ ] Push commits to Railway (git push origin main)
- [ ] Post at 9am PT, Mon–Wed for best HN traction

## Target communities (after HN)

- Indie Hackers (Show IH)
- Twitter/X — tag @levelsio and other indie hackers
- Reddit r/Python, r/datascience, r/MachineLearning
- Product Hunt (Week 2 if HN gets traction)
