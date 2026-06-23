#!/usr/bin/env python3
"""
One-shot Stripe product + payment link setup for DataCleanr.

Usage:
    STRIPE_SECRET_KEY=sk_live_... python scripts/stripe_setup.py

Outputs the STRIPE_PAYMENT_LINK value to set in Railway env vars.
"""
import os
import sys

import stripe

api_key = os.getenv("STRIPE_SECRET_KEY", "")
if not api_key or not api_key.startswith("sk_"):
    print("ERROR: set STRIPE_SECRET_KEY=sk_live_... (or sk_test_...)")
    sys.exit(1)

stripe.api_key = api_key
is_test = api_key.startswith("sk_test_")
mode = "TEST" if is_test else "LIVE"
print(f"Using Stripe {mode} mode\n")

# 1. Product
product = stripe.Product.create(
    name="DataCleanr Paid",
    description="500,000 rows/day — transform CSVs with plain English",
)
print(f"Product created: {product.id} ({product.name})")

# 2. Price ($9/month recurring)
price = stripe.Price.create(
    product=product.id,
    unit_amount=900,   # cents
    currency="usd",
    recurring={"interval": "month"},
)
print(f"Price created:   {price.id} ($9.00/month)")

# 3. Payment Link (Stripe no-code Checkout)
payment_link = stripe.PaymentLink.create(
    line_items=[{"price": price.id, "quantity": 1}],
    after_completion={"type": "redirect", "redirect": {"url": "https://datacleanr-production.up.railway.app/docs"}},
    billing_address_collection="required",
    customer_creation="always",
    metadata={"product": "datacleanr_paid"},
)
print(f"Payment link:    {payment_link.url}\n")

print("=" * 60)
print("Add this to Railway env vars (DataCleanr service > Variables):")
print(f"  STRIPE_PAYMENT_LINK = {payment_link.url}")
print("=" * 60)
