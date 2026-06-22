# Task: Stripe Product + Checkout

**Priority:** P0 — needed for first paying user
**Status:** Pending
**Depends on:** 01-railway-deploy.md (need live URL for webhook)

## Steps

- [ ] Create Product in Stripe dashboard:
  - Name: "DataCleanr Paid"
  - Price: $9.00 / month, recurring
  - Description: "500,000 rows/day — transform CSVs with plain English"

- [ ] Create Payment Link (no-code Checkout):
  - Product: DataCleanr Paid
  - Collect: email address (needed to match against user in DB)
  - Success URL: `https://your-app.railway.app/docs` (or landing page)

- [ ] Test the full flow with Stripe CLI:
  ```bash
  stripe listen --forward-to https://your-app.railway.app/webhook/stripe
  stripe trigger checkout.session.completed
  ```
  Verify: user tier in SQLite changes to PAID.

- [ ] Test dunning flow:
  ```bash
  stripe trigger invoice.payment_failed
  stripe trigger customer.subscription.deleted
  ```

- [ ] Add payment link to docs / landing page

## Done when
Full checkout flow: register → click payment link → pay → tier=PAID in DB.
