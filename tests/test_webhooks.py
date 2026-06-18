import json
import hashlib
import hmac
import time

import pytest


def _stripe_sig(payload: bytes, secret: str) -> str:
    ts = str(int(time.time()))
    signed = f"{ts}.{payload.decode()}"
    sig = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _post_webhook(client, event_type: str, obj: dict, event_id: str = "evt_test_001"):
    payload = json.dumps({
        "id": event_id,
        "type": event_type,
        "data": {"object": obj},
    }).encode()
    # With fake secret, signature check will fail — patch around it
    return client.post(
        "/webhook/stripe",
        content=payload,
        headers={"Content-Type": "application/json", "stripe-signature": "t=1,v1=fake"},
    )


def test_webhook_invalid_signature(client):
    r = _post_webhook(client, "checkout.session.completed", {})
    # Expect 400 because signature is fake
    assert r.status_code == 400


def test_webhook_duplicate_event_is_idempotent(fresh_db):
    """record_stripe_event returns False on second call with same id."""
    from app.database import record_stripe_event
    assert record_stripe_event("evt_dup") is True
    assert record_stripe_event("evt_dup") is False


def test_upgrade_and_downgrade_flow(fresh_db):
    from app.database import (
        create_user, get_user_by_email,
        upgrade_to_paid, downgrade_to_free, set_payment_failing,
    )
    create_user("pay@example.com")
    upgrade_to_paid("cus_123", "sub_abc", "pay@example.com")
    user = get_user_by_email("pay@example.com")
    assert user["tier"] == "PAID"
    assert user["stripe_subscription_id"] == "sub_abc"
    assert user["payment_failing"] == 0

    set_payment_failing("sub_abc", True)
    user = get_user_by_email("pay@example.com")
    assert user["tier"] == "PAID"       # NOT downgraded yet
    assert user["payment_failing"] == 1

    downgrade_to_free("sub_abc")
    user = get_user_by_email("pay@example.com")
    assert user["tier"] == "FREE"
    assert user["payment_failing"] == 0
    assert user["stripe_subscription_id"] is None
