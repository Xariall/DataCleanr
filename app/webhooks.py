import os

import stripe
from fastapi import APIRouter, HTTPException, Request

from .database import (
    downgrade_to_free,
    record_stripe_event,
    set_payment_failing,
    upgrade_to_paid,
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

webhooks_router = APIRouter()


@webhooks_router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig, _WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Idempotency: skip duplicate deliveries
    if not record_stripe_event(event["id"]):
        return {"status": "duplicate"}

    etype = event["type"]
    obj = event["data"]["object"]

    if etype == "checkout.session.completed":
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        email = (obj.get("customer_details") or {}).get("email")
        if customer_id and subscription_id and email:
            upgrade_to_paid(customer_id, subscription_id, email)

    elif etype == "invoice.payment_failed":
        sub_id = obj.get("subscription")
        if sub_id:
            set_payment_failing(sub_id, True)

    elif etype == "invoice.payment_succeeded":
        sub_id = obj.get("subscription")
        if sub_id:
            set_payment_failing(sub_id, False)

    elif etype == "customer.subscription.deleted":
        sub_id = obj.get("id")
        if sub_id:
            downgrade_to_free(sub_id)

    # Unknown event types: log-and-200 (no crash)
    return {"status": "ok"}
