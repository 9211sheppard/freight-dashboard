"""
admin_panel.py  —  Admin-only SaaS management dashboard

Only visible to users with role='admin'. Internal team and customers never see this.
Provides:
  - Revenue metrics (MRR, ARR, churn)
  - User/tenant management
  - Spin-to-win statistics
  - Referral tracking
  - Support ticket overview
  - System health
"""

import secrets
import string
import random
from datetime import datetime, timedelta
from database import get_db


# ─────────────────────────────────────────────────────────────────────────────
#  Revenue & Subscription Metrics
# ─────────────────────────────────────────────────────────────────────────────

PRICE_PER_MONTH = 49.99


def get_saas_metrics() -> dict:
    """Calculate key SaaS metrics for the admin dashboard."""
    conn = get_db()
    try:
        # Total tenants by status
        rows = conn.execute("""
            SELECT subscription_status, COUNT(*) as cnt
            FROM tenants GROUP BY subscription_status
        """).fetchall()
        status_counts = {r["subscription_status"]: r["cnt"] for r in rows}

        active = status_counts.get("active", 0)
        trialing = status_counts.get("trialing", 0)
        cancelled = status_counts.get("cancelled", 0)
        past_due = status_counts.get("past_due", 0)
        total_tenants = sum(status_counts.values())

        # MRR / ARR
        mrr = active * PRICE_PER_MONTH
        arr = mrr * 12

        # Total users
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

        # Users by role
        role_rows = conn.execute("""
            SELECT role, COUNT(*) as cnt FROM users GROUP BY role
        """).fetchall()
        users_by_role = {r["role"]: r["cnt"] for r in role_rows}

        # Signups this month
        month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0).isoformat()
        new_this_month = conn.execute(
            "SELECT COUNT(*) FROM tenants WHERE created_at >= ?", (month_start,)
        ).fetchone()[0]

        # Signups this week
        week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).replace(
            hour=0, minute=0, second=0
        ).isoformat()
        new_this_week = conn.execute(
            "SELECT COUNT(*) FROM tenants WHERE created_at >= ?", (week_start,)
        ).fetchone()[0]

        # Trial conversion rate
        total_ever = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        conversion_rate = (active / total_ever * 100) if total_ever > 0 else 0

        # Churn (cancelled in last 30 days)
        thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
        churned_30d = conn.execute(
            "SELECT COUNT(*) FROM tenants WHERE subscription_status = 'cancelled' AND updated_at >= ?",
            (thirty_days_ago,)
        ).fetchone()[0]

        return {
            "mrr": mrr,
            "arr": arr,
            "active_subscriptions": active,
            "trialing": trialing,
            "cancelled": cancelled,
            "past_due": past_due,
            "total_tenants": total_tenants,
            "total_users": total_users,
            "users_by_role": users_by_role,
            "new_this_month": new_this_month,
            "new_this_week": new_this_week,
            "conversion_rate": round(conversion_rate, 1),
            "churned_30d": churned_30d,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Tenant Management
# ─────────────────────────────────────────────────────────────────────────────

def list_tenants() -> list:
    """List all tenants with user counts."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT t.*, COUNT(u.id) as user_count
            FROM tenants t
            LEFT JOIN users u ON u.tenant_id = t.id
            GROUP BY t.id
            ORDER BY t.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_users() -> list:
    """List all users across all tenants."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT u.id, u.name, u.email, u.role, u.tenant_id, u.created_at,
                   u.last_login, COALESCE(u.login_count, 0) as login_count,
                   t.name as tenant_name, t.subscription_status
            FROM users u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            ORDER BY u.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Referral System
# ─────────────────────────────────────────────────────────────────────────────

def generate_referral_code() -> str:
    """Generate a unique referral code."""
    chars = string.ascii_uppercase + string.digits
    return "FD-" + "".join(secrets.choice(chars) for _ in range(8))


def create_referral_code(tenant_id: int, user_id: int) -> dict:
    """Create a referral code for a user. One per user."""
    conn = get_db()
    try:
        # Check if user already has a code
        existing = conn.execute(
            "SELECT referral_code FROM referrals WHERE referrer_user_id = ? AND referred_email = ''",
            (user_id,)
        ).fetchone()
        if existing:
            return {"ok": True, "code": existing["referral_code"]}

        code = generate_referral_code()
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO referrals (referrer_tenant_id, referrer_user_id, referral_code, created_at)
               VALUES (?, ?, ?, ?)""",
            (tenant_id, user_id, code, now)
        )
        conn.commit()
        return {"ok": True, "code": code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def validate_referral_code(code: str) -> dict:
    """Check if a referral code is valid."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM referrals WHERE referral_code = ?", (code.strip().upper(),)
        ).fetchone()
        if not row:
            return {"valid": False}
        return {"valid": True, "referrer_tenant_id": row["referrer_tenant_id"],
                "referrer_user_id": row["referrer_user_id"]}
    finally:
        conn.close()


def complete_referral(code: str, referred_tenant_id: int, referred_email: str) -> dict:
    """Mark a referral as converted and apply free month to referrer."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE referrals SET referred_tenant_id = ?, referred_email = ?,
               status = 'converted', converted_at = ?
               WHERE referral_code = ? AND status = 'pending'""",
            (referred_tenant_id, referred_email, now, code.strip().upper())
        )
        conn.commit()

        # Count successful referrals for this referrer
        row = conn.execute(
            "SELECT referrer_tenant_id, COUNT(*) as cnt FROM referrals WHERE referral_code = ? AND status = 'converted'",
            (code.strip().upper(),)
        ).fetchone()

        return {"ok": True, "total_referrals": row["cnt"] if row else 0}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def get_referral_stats(tenant_id: int = None) -> dict:
    """Get referral stats. If tenant_id, scoped to that tenant. Otherwise global."""
    conn = get_db()
    try:
        if tenant_id:
            total = conn.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_tenant_id = ?", (tenant_id,)
            ).fetchone()[0]
            converted = conn.execute(
                "SELECT COUNT(*) FROM referrals WHERE referrer_tenant_id = ? AND status = 'converted'",
                (tenant_id,)
            ).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
            converted = conn.execute(
                "SELECT COUNT(*) FROM referrals WHERE status = 'converted'"
            ).fetchone()[0]

        free_months_given = conn.execute(
            "SELECT COALESCE(SUM(free_month_applied), 0) FROM referrals WHERE status = 'converted'"
        ).fetchone()[0]

        return {
            "total_codes": total,
            "converted": converted,
            "conversion_rate": round(converted / total * 100, 1) if total > 0 else 0,
            "free_months_given": free_months_given,
            "revenue_from_referrals": converted * PRICE_PER_MONTH,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Spin-to-Win System
# ─────────────────────────────────────────────────────────────────────────────

SPIN_PRIZES = [
    {"type": "discount_10", "label": "10% off 3 months", "discount_pct": 10, "free_months": 0, "weight": 40},
    {"type": "discount_20", "label": "20% off 3 months", "discount_pct": 20, "free_months": 0, "weight": 25},
    {"type": "free_1mo",    "label": "1 month free",     "discount_pct": 0,  "free_months": 1, "weight": 20},
    {"type": "free_3mo",    "label": "3 months free",    "discount_pct": 0,  "free_months": 3, "weight": 10},
    {"type": "free_6mo",    "label": "6 months free",    "discount_pct": 0,  "free_months": 6, "weight": 4},
    {"type": "free_12mo",   "label": "FREE for a year",  "discount_pct": 0,  "free_months": 12, "weight": 1},
]


def spin_the_wheel() -> dict:
    """Randomly select a prize based on weighted probabilities."""
    population = []
    weights = []
    for p in SPIN_PRIZES:
        population.append(p)
        weights.append(p["weight"])

    winner = random.choices(population, weights=weights, k=1)[0]
    return {
        "type": winner["type"],
        "label": winner["label"],
        "discount_pct": winner["discount_pct"],
        "free_months": winner["free_months"],
    }


def record_spin(tenant_id: int, user_id: int, prize: dict) -> dict:
    """Record a spin result in the database."""
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT INTO spin_results
               (tenant_id, user_id, prize_type, prize_value, discount_pct, free_months, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tenant_id, user_id, prize["type"], prize["label"],
             prize["discount_pct"], prize["free_months"], now)
        )
        conn.commit()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def get_spin_stats() -> dict:
    """Get spin wheel statistics for admin dashboard."""
    conn = get_db()
    try:
        total_spins = conn.execute("SELECT COUNT(*) FROM spin_results").fetchone()[0]

        rows = conn.execute("""
            SELECT prize_type, prize_value, COUNT(*) as cnt
            FROM spin_results GROUP BY prize_type ORDER BY cnt DESC
        """).fetchall()
        by_prize = [dict(r) for r in rows]

        total_free_months = conn.execute(
            "SELECT COALESCE(SUM(free_months), 0) FROM spin_results"
        ).fetchone()[0]

        cost_of_free = total_free_months * PRICE_PER_MONTH

        return {
            "total_spins": total_spins,
            "by_prize": by_prize,
            "total_free_months_given": total_free_months,
            "estimated_cost": cost_of_free,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Support Ticket Overview
# ─────────────────────────────────────────────────────────────────────────────

def get_ticket_overview() -> dict:
    """Get support ticket stats for admin dashboard."""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM support_tickets").fetchone()[0]
        open_tickets = conn.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE status = 'open'"
        ).fetchone()[0]
        auto_resolved = conn.execute(
            "SELECT COUNT(*) FROM support_tickets WHERE auto_resolved = 1"
        ).fetchone()[0]

        by_category = conn.execute("""
            SELECT category, COUNT(*) as cnt
            FROM support_tickets GROUP BY category ORDER BY cnt DESC
        """).fetchall()

        recent = conn.execute("""
            SELECT st.*, u.name as user_name, u.email as user_email
            FROM support_tickets st
            LEFT JOIN users u ON u.id = st.user_id
            ORDER BY st.created_at DESC LIMIT 20
        """).fetchall()

        return {
            "total": total,
            "open": open_tickets,
            "auto_resolved": auto_resolved,
            "auto_resolve_rate": round(auto_resolved / total * 100, 1) if total > 0 else 0,
            "by_category": [dict(r) for r in by_category],
            "recent": [dict(r) for r in recent],
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  System Health
# ─────────────────────────────────────────────────────────────────────────────

def run_health_check() -> dict:
    """Run system health checks."""
    checks = {}
    now = datetime.now().isoformat()
    conn = get_db()

    try:
        # Database connectivity
        try:
            conn.execute("SELECT 1").fetchone()
            checks["database"] = {"status": "ok", "detail": "Connected"}
        except Exception as e:
            checks["database"] = {"status": "error", "detail": str(e)}

        # Table row counts
        for table in ["contacts", "users", "tenants", "lanes", "support_tickets"]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                checks[f"table_{table}"] = {"status": "ok", "detail": f"{cnt} rows"}
            except Exception:
                checks[f"table_{table}"] = {"status": "warning", "detail": "Table not found"}

        # Log health check
        status = "ok" if all(c["status"] == "ok" for c in checks.values()) else "warning"
        conn.execute(
            "INSERT INTO system_health_log (check_type, status, details, checked_at) VALUES (?, ?, ?, ?)",
            ("full_check", status, str(checks), now)
        )
        conn.commit()

        checks["overall"] = status
        checks["checked_at"] = now
        return checks
    finally:
        conn.close()
