"""
billing.py  —  Stripe billing integration for the Freight Intelligence Dashboard

Provides:
  - Checkout session creation ($49.99/mo)
  - Webhook handling (payment success, failure, cancellation)
  - Customer portal (manage subscription, invoices)
  - Trial → Paid conversion
"""

import os
from datetime import datetime
from database import get_db
from tenant import update_subscription, get_tenant

# ── Stripe config ────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")  # $49.99/mo price ID from Stripe dashboard

_stripe = None


def _get_stripe():
    """Lazy-load stripe to avoid import errors when not configured."""
    global _stripe
    if _stripe is None:
        if not STRIPE_SECRET_KEY:
            return None
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
        _stripe = stripe
    return _stripe


def is_configured() -> bool:
    """Check if Stripe is configured."""
    return bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)


# ─────────────────────────────────────────────────────────────────────────────
#  Checkout
# ─────────────────────────────────────────────────────────────────────────────

def create_checkout_session(tenant_id: int, user_email: str, success_url: str, cancel_url: str) -> dict:
    """Create a Stripe Checkout session for $49.99/mo subscription."""
    stripe = _get_stripe()
    if not stripe:
        return {"ok": False, "error": "Billing is not configured. Set STRIPE_SECRET_KEY."}

    tenant = get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Workspace not found."}

    try:
        # Create or reuse Stripe customer
        customer_id = tenant.get("stripe_customer_id", "")
        if not customer_id:
            customer = stripe.Customer.create(
                email=user_email,
                metadata={"tenant_id": str(tenant_id), "tenant_name": tenant.get("name", "")},
            )
            customer_id = customer.id
            update_subscription(tenant_id, stripe_customer_id=customer_id)

        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": str(tenant_id)},
            subscription_data={
                "metadata": {"tenant_id": str(tenant_id)},
            },
        )
        return {"ok": True, "checkout_url": session.url, "session_id": session.id}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Customer Portal (manage subscription, invoices, payment method)
# ─────────────────────────────────────────────────────────────────────────────

def create_portal_session(tenant_id: int, return_url: str) -> dict:
    """Create a Stripe Customer Portal session."""
    stripe = _get_stripe()
    if not stripe:
        return {"ok": False, "error": "Billing is not configured."}

    tenant = get_tenant(tenant_id)
    if not tenant or not tenant.get("stripe_customer_id"):
        return {"ok": False, "error": "No billing account found. Please subscribe first."}

    try:
        session = stripe.billing_portal.Session.create(
            customer=tenant["stripe_customer_id"],
            return_url=return_url,
        )
        return {"ok": True, "portal_url": session.url}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Webhook Handler
# ─────────────────────────────────────────────────────────────────────────────

def handle_webhook(payload: bytes, sig_header: str) -> dict:
    """Process Stripe webhook events."""
    stripe = _get_stripe()
    if not stripe:
        return {"ok": False, "error": "Stripe not configured"}

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return {"ok": False, "error": f"Webhook verification failed: {e}"}

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)

    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data)

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data)

    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data)

    elif event_type == "invoice.paid":
        _handle_invoice_paid(data)

    return {"ok": True, "event": event_type}


def _handle_checkout_completed(session):
    """New subscription created via checkout."""
    tenant_id = session.get("metadata", {}).get("tenant_id")
    if not tenant_id:
        return
    tenant_id = int(tenant_id)
    subscription_id = session.get("subscription", "")
    customer_id = session.get("customer", "")

    update_subscription(
        tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status="active",
        plan="pro",
        max_contacts=50000,
        max_users=50,
    )
    print(f"[billing] Tenant {tenant_id} activated — subscription {subscription_id}")


def _handle_subscription_updated(subscription):
    """Subscription status changed."""
    tenant_id = subscription.get("metadata", {}).get("tenant_id")
    if not tenant_id:
        return
    tenant_id = int(tenant_id)
    status = subscription.get("status", "")  # active, past_due, canceled, unpaid

    update_subscription(tenant_id, subscription_status=status)
    print(f"[billing] Tenant {tenant_id} subscription status → {status}")


def _handle_subscription_deleted(subscription):
    """Subscription cancelled."""
    tenant_id = subscription.get("metadata", {}).get("tenant_id")
    if not tenant_id:
        return
    tenant_id = int(tenant_id)

    update_subscription(
        tenant_id,
        subscription_status="cancelled",
        plan="free",
        max_contacts=100,
        max_users=2,
    )
    print(f"[billing] Tenant {tenant_id} subscription cancelled")


def _handle_payment_failed(invoice):
    """Payment failed — give grace period."""
    customer_id = invoice.get("customer", "")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM tenants WHERE stripe_customer_id = ?", (customer_id,)
        ).fetchone()
        if row:
            update_subscription(row["id"], subscription_status="past_due")
            print(f"[billing] Tenant {row['id']} payment failed — past_due")
    finally:
        conn.close()


def _handle_invoice_paid(invoice):
    """Payment succeeded — ensure active status."""
    customer_id = invoice.get("customer", "")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM tenants WHERE stripe_customer_id = ?", (customer_id,)
        ).fetchone()
        if row:
            update_subscription(row["id"], subscription_status="active")
    finally:
        conn.close()
