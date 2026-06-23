#!/usr/bin/env bash
# Test the full Stripe → DataCleanr webhook flow against production.
#
# Requirements:
#   brew install stripe/stripe-cli/stripe
#   stripe login
#
# Usage:
#   STRIPE_SECRET_KEY=sk_test_... ./scripts/stripe_test_flow.sh

set -euo pipefail

BASE="${1:-https://datacleanr-production.up.railway.app}"
WEBHOOK_URL="$BASE/webhook/stripe"

echo "=== DataCleanr Stripe webhook test ==="
echo "Target: $WEBHOOK_URL"
echo ""

# 1. Register a test user
echo "1. Registering test user..."
EMAIL="stripe_test_$(date +%s)@example.com"
REGISTER=$(curl -sf -X POST "$BASE/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\"}")
API_KEY=$(echo "$REGISTER" | python3 -c "import sys,json; print(json.load(sys.stdin)['api_key'])")
echo "   Email:   $EMAIL"
echo "   API key: $API_KEY"

# 2. Check /me — should be FREE
echo ""
echo "2. Checking /me (expect tier=FREE)..."
ME=$(curl -sf "$BASE/me" -H "X-API-Key: $API_KEY")
echo "   $ME"

# 3. Forward webhooks to production and trigger checkout.session.completed
echo ""
echo "3. Triggering checkout.session.completed (requires stripe CLI)..."
echo "   stripe trigger checkout.session.completed"
echo "   NOTE: This sets customer_email in Stripe test mode — may not match $EMAIL"
echo "   For a real test, complete an actual checkout with this email."

echo ""
echo "=== Done ==="
echo "To forward webhooks locally: stripe listen --forward-to http://localhost:8000/webhook/stripe"
