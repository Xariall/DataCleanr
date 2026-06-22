# Task: Railway Deploy

**Priority:** P0 — blocks everything
**Status:** Pending

## Steps

- [ ] Install Railway CLI: `brew install railway`
- [ ] Login: `railway login`
- [ ] Link project: `railway link` (select existing project or `railway init`)
- [ ] Add persistent volume in Railway dashboard → Volumes → mount at `/data`
- [ ] Set environment variables in Railway dashboard → Variables:
  - `ANTHROPIC_API_KEY` — from console.anthropic.com
  - `REDIS_URL` — from Upstash (create free Redis at upstash.com)
  - `STRIPE_SECRET_KEY` — from Stripe dashboard (use `sk_test_...` first)
  - `STRIPE_WEBHOOK_SECRET` — from Stripe dashboard → Webhooks (after deploy)
  - `DATABASE_PATH` — set to `/data/datacleanr.db`
- [ ] Deploy: `railway up`
- [ ] Verify: `curl https://your-app.railway.app/health` → `{"status":"ok"}`
- [ ] Register test user: `curl -X POST https://your-app.railway.app/register -H 'Content-Type: application/json' -d '{"email":"test@test.com"}'`
- [ ] Configure Stripe webhook URL: `https://your-app.railway.app/webhook/stripe`
- [ ] Subscribe to Stripe events: `checkout.session.completed`, `invoice.payment_failed`, `invoice.payment_succeeded`, `customer.subscription.deleted`

## Done when
`/health` returns 200 and a test `/transform` call returns clean CSV.
