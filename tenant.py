"""
tenant.py  —  Multi-tenancy layer for the Freight Intelligence Dashboard

Every customer (company) gets a tenant. All data queries are scoped by tenant_id.
This module provides:
  - Tenant creation (on signup)
  - Tenant resolution (from session)
  - Scoped query helpers
  - Subscription/trial checks
"""

from datetime import datetime, timedelta
from database import get_db


# ─────────────────────────────────────────────────────────────────────────────
#  Tenant CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_tenant(name: str, slug: str = "") -> dict:
    """Create a new tenant (company workspace). Returns {"ok": True, "tenant_id": int}."""
    name = name.strip()
    if not name:
        return {"ok": False, "error": "Company name is required."}

    # Auto-generate slug from name
    if not slug:
        slug = name.lower().replace(" ", "-").replace(".", "")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")

    now = datetime.now().isoformat()
    trial_end = (datetime.now() + timedelta(days=14)).isoformat()

    conn = get_db()
    try:
        # Check for duplicate slug
        existing = conn.execute("SELECT id FROM tenants WHERE slug = ?", (slug,)).fetchone()
        if existing:
            # Append a number to make it unique
            for i in range(2, 100):
                test_slug = f"{slug}-{i}"
                ex2 = conn.execute("SELECT id FROM tenants WHERE slug = ?", (test_slug,)).fetchone()
                if not ex2:
                    slug = test_slug
                    break

        cur = conn.execute(
            """INSERT INTO tenants (name, slug, plan, trial_ends_at, subscription_status, created_at, updated_at)
               VALUES (?, ?, 'trial', ?, 'trialing', ?, ?)""",
            (name, slug, trial_end, now, now)
        )
        conn.commit()
        return {"ok": True, "tenant_id": cur.lastrowid, "slug": slug}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def get_tenant(tenant_id: int) -> dict:
    """Fetch tenant details."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def get_tenant_for_user(user_id: int) -> dict:
    """Get the tenant associated with a user."""
    conn = get_db()
    try:
        row = conn.execute("SELECT tenant_id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not row["tenant_id"]:
            return None
        return get_tenant(row["tenant_id"])
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Subscription & Trial Checks
# ─────────────────────────────────────────────────────────────────────────────

def check_subscription(tenant_id: int) -> dict:
    """Check if tenant has active subscription or valid trial.
    Returns {"active": True/False, "reason": str, "days_left": int}."""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return {"active": False, "reason": "tenant_not_found", "days_left": 0}

    status = tenant.get("subscription_status", "")

    # Active paid subscription
    if status == "active":
        return {"active": True, "reason": "paid", "days_left": -1}

    # Trial period
    if status == "trialing":
        trial_end = tenant.get("trial_ends_at", "")
        if trial_end:
            try:
                end_dt = datetime.fromisoformat(trial_end)
                now = datetime.now()
                if now < end_dt:
                    days_left = (end_dt - now).days
                    return {"active": True, "reason": "trial", "days_left": days_left}
                else:
                    return {"active": False, "reason": "trial_expired", "days_left": 0}
            except Exception:
                pass
        return {"active": False, "reason": "trial_expired", "days_left": 0}

    # Cancelled, past_due, etc.
    if status in ("past_due", "unpaid"):
        return {"active": True, "reason": "grace_period", "days_left": 7}

    return {"active": False, "reason": status or "inactive", "days_left": 0}


def update_subscription(tenant_id: int, **kwargs) -> bool:
    """Update tenant subscription fields (plan, stripe_customer_id, status, etc.)."""
    conn = get_db()
    try:
        allowed = {"plan", "stripe_customer_id", "stripe_subscription_id",
                   "subscription_status", "trial_ends_at", "max_users", "max_contacts"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = datetime.now().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [tenant_id]
        conn.execute(f"UPDATE tenants SET {set_clause} WHERE id = ?", values)
        conn.commit()
        return True
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Tenant-Scoped Queries (the core of data isolation)
# ─────────────────────────────────────────────────────────────────────────────

def scoped_count(table: str, tenant_id: int) -> int:
    """Count rows in a table for a specific tenant."""
    conn = get_db()
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = ?", (tenant_id,)).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Usage Limits
# ─────────────────────────────────────────────────────────────────────────────

def check_limits(tenant_id: int) -> dict:
    """Check if tenant is within their plan limits."""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Tenant not found"}

    max_contacts = tenant.get("max_contacts", 5000)
    max_users = tenant.get("max_users", 10)

    current_contacts = scoped_count("contacts", tenant_id)
    current_users = scoped_count("users", tenant_id)

    return {
        "ok": True,
        "contacts": {"current": current_contacts, "max": max_contacts, "remaining": max_contacts - current_contacts},
        "users": {"current": current_users, "max": max_users, "remaining": max_users - current_users},
        "can_add_contact": current_contacts < max_contacts,
        "can_add_user": current_users < max_users,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Support Tickets (self-service issue tracking)
# ─────────────────────────────────────────────────────────────────────────────

TICKET_CATEGORIES = {
    "password":  "Password & Login",
    "billing":   "Billing & Subscription",
    "import":    "Data Import",
    "email":     "Email & Outreach",
    "rates":     "Rate Engine",
    "schedules": "Vessel Schedules",
    "general":   "General Question",
    "bug":       "Bug Report",
}

# Auto-resolvable categories with resolution instructions
AUTO_RESOLVE = {
    "password": "You can reset your password from the login page using the 'Forgot Password' link. A reset email will be sent within 1 minute.",
    "billing": "Visit the Billing page in your dashboard to update payment info, view invoices, or manage your subscription.",
}


def create_ticket(tenant_id: int, user_id: int, category: str, subject: str, description: str = "") -> dict:
    """Create a support ticket. Auto-resolves common issues."""
    now = datetime.now().isoformat()
    auto = 0
    resolution = ""
    status = "open"

    # Try auto-resolution first
    if category in AUTO_RESOLVE:
        auto = 1
        resolution = AUTO_RESOLVE[category]
        status = "auto_resolved"

    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO support_tickets
               (tenant_id, user_id, category, subject, description, status, priority, auto_resolved, resolution_note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'normal', ?, ?, ?)""",
            (tenant_id, user_id, category, subject, description, status, auto, resolution, now)
        )
        conn.commit()
        return {
            "ok": True,
            "ticket_id": cur.lastrowid,
            "auto_resolved": bool(auto),
            "resolution": resolution,
            "status": status,
        }
    finally:
        conn.close()


def get_tickets(tenant_id: int, status: str = None) -> list:
    """Get support tickets for a tenant."""
    conn = get_db()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM support_tickets WHERE tenant_id = ? AND status = ? ORDER BY created_at DESC",
                (tenant_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM support_tickets WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
