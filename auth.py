"""
auth.py  —  Per-user authentication for the Freight Intelligence Dashboard
Provides:
  - User registration (name, email, password)
  - Email/password login with bcrypt
  - Password reset via email token
  - Admin role check
  - Session helpers
"""

import bcrypt
import secrets
import string
from datetime import datetime, timedelta
from database import get_db
from config import EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASS, EMAIL_FROM

# ── Admin email list — set in config.py if needed ─────────────────────────
try:
    from config import ADMIN_EMAILS
except ImportError:
    ADMIN_EMAILS = []


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def _gen_token(length=48) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _send_email(to: str, subject: str, body: str) -> bool:
    """Send an email via Microsoft Graph API. Falls back to SMTP if Graph fails."""
    try:
        from mailer import send_email as graph_send_email
        body_html = body.replace("\n", "<br>")
        graph_send_email(
            to_address=to,
            subject=subject,
            body_html=body_html,
            body_text=body,
            display_name="Flash Cargo Global",
        )
        return True
    except Exception as e:
        print(f"[auth] Graph email send failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────────────────────────────────────

def register_user(name: str, email: str, password: str, role: str = "user",
                   company_name: str = "", tenant_id: int = None) -> dict:
    """
    Create a new user + tenant. Returns {"ok": True, "user_id": int, "tenant_id": int}.
    If company_name is provided, creates a new tenant (company workspace).
    If tenant_id is provided, joins an existing tenant.
    First registered user automatically becomes admin of their tenant.
    """
    email = email.strip().lower()
    name  = name.strip()

    if not name or not email or not password:
        return {"ok": False, "error": "Name, email, and password are required."}
    if len(password) < 6:
        return {"ok": False, "error": "Password must be at least 6 characters."}

    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            return {"ok": False, "error": "An account with that email already exists."}

        # Create or join tenant
        if tenant_id is None:
            # New signup — create a new tenant for this company
            from tenant import create_tenant
            t_name = company_name or f"{name}'s Workspace"
            t_result = create_tenant(t_name)
            if not t_result["ok"]:
                return {"ok": False, "error": f"Could not create workspace: {t_result['error']}"}
            tenant_id = t_result["tenant_id"]
            role = "admin"  # First user of a new tenant is always admin
        else:
            # Joining existing tenant — check if first user for this tenant
            count = conn.execute("SELECT COUNT(*) FROM users WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
            if count == 0:
                role = "admin"

        # Global admin check
        if email in ADMIN_EMAILS:
            role = "admin"

        hashed = _hash(password)
        now    = datetime.now().isoformat()
        cur    = conn.execute(
            "INSERT INTO users (tenant_id, name, email, password_hash, role, created_at) VALUES (?,?,?,?,?,?)",
            (tenant_id, name, email, hashed, role, now)
        )
        conn.commit()
        return {"ok": True, "user_id": cur.lastrowid, "role": role, "tenant_id": tenant_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Login
# ─────────────────────────────────────────────────────────────────────────────

def login_user(email: str, password: str, ip: str = "") -> dict:
    """
    Validate credentials. Returns {"ok": True, "user": {...}} or {"ok": False, "error": str}.
    """
    email = email.strip().lower()
    conn  = get_db()
    try:
        row = conn.execute(
            "SELECT id, tenant_id, name, email, password_hash, role FROM users WHERE email = ?",
            (email,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "No account found with that email."}
        if not _check(password, row["password_hash"]):
            return {"ok": False, "error": "Incorrect password."}

        # Check subscription status
        from tenant import check_subscription
        tenant_id = row["tenant_id"] or 1
        sub = check_subscription(tenant_id)
        if not sub["active"]:
            reason = sub.get("reason", "inactive")
            if reason == "trial_expired":
                return {"ok": False, "error": "Your free trial has expired. Please upgrade to continue.", "paywall": True}
            elif reason in ("cancelled", "inactive"):
                return {"ok": False, "error": "Your subscription is inactive. Please reactivate to continue.", "paywall": True}

        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE users SET last_login = ?, login_count = COALESCE(login_count, 0) + 1 WHERE id = ?",
            (now, row["id"])
        )
        conn.execute(
            "INSERT INTO user_logins (user_id, login_at, ip_address) VALUES (?, ?, ?)",
            (row["id"], now, ip)
        )
        conn.commit()
        return {
            "ok": True,
            "user": {
                "id":        row["id"],
                "tenant_id": tenant_id,
                "name":      row["name"],
                "email":     row["email"],
                "role":      row["role"],
            }
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Password Reset
# ─────────────────────────────────────────────────────────────────────────────

def request_password_reset(email: str, base_url: str = "http://localhost:5000") -> dict:
    """
    Generate a reset token, store it, and email the link.
    Always returns {"ok": True} to avoid user enumeration.
    """
    email = email.strip().lower()
    conn  = get_db()
    try:
        user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            return {"ok": True}   # silent — don't reveal if email exists

        token      = _gen_token()
        expires_at = (datetime.now() + timedelta(hours=2)).isoformat()

        # Invalidate previous tokens for this email
        conn.execute("UPDATE password_resets SET used = 1 WHERE email = ?", (email,))
        conn.execute(
            "INSERT INTO password_resets (email, token, expires_at, used) VALUES (?,?,?,0)",
            (email, token, expires_at)
        )
        conn.commit()

        reset_link = f"{base_url}/reset-password?token={token}"
        _send_email(
            to      = email,
            subject = "Freight Dashboard — Password Reset",
            body    = (
                f"Hi,\n\nClick the link below to reset your password:\n\n"
                f"{reset_link}\n\n"
                f"This link expires in 2 hours.\n\n"
                f"If you didn't request this, ignore this email."
            )
        )
        return {"ok": True, "token": token}  # token returned for CLI/admin use
    except Exception as e:
        print(f"[auth] request_password_reset error: {e}")
        return {"ok": True}   # still return ok to avoid user enumeration
    finally:
        conn.close()


def reset_password(token: str, new_password: str) -> dict:
    """
    Validate token and set new password.
    """
    if len(new_password) < 6:
        return {"ok": False, "error": "Password must be at least 6 characters."}

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM password_resets WHERE token = ? AND used = 0",
            (token,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "Invalid or expired reset link."}
        if datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return {"ok": False, "error": "This reset link has expired. Please request a new one."}

        hashed = _hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (hashed, row["email"])
        )
        conn.execute("UPDATE password_resets SET used = 1 WHERE token = ?", (token,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Session helpers
# ─────────────────────────────────────────────────────────────────────────────

def set_session(session, user: dict):
    """Store user info in Flask session."""
    session["logged_in"]  = True
    session["user_id"]    = user["id"]
    session["user_name"]  = user["name"]
    session["user_email"] = user["email"]
    session["user_role"]  = user["role"]
    session["tenant_id"]  = user.get("tenant_id", 1)
    session.permanent     = False


def clear_session(session):
    session.clear()


def is_admin(session) -> bool:
    return session.get("user_role") == "admin"


def current_user(session) -> dict:
    """Return a safe dict of the current user from session."""
    return {
        "id":        session.get("user_id"),
        "name":      session.get("user_name", ""),
        "email":     session.get("user_email", ""),
        "role":      session.get("user_role",  "user"),
        "tenant_id": session.get("tenant_id", 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Change password (logged-in user)
# ─────────────────────────────────────────────────────────────────────────────

def change_password(user_id: int, old_password: str, new_password: str) -> dict:
    if len(new_password) < 6:
        return {"ok": False, "error": "New password must be at least 6 characters."}
    conn = get_db()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not _check(old_password, row["password_hash"]):
            return {"ok": False, "error": "Current password is incorrect."}
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash(new_password), user_id)
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Admin: list users
# ─────────────────────────────────────────────────────────────────────────────

def list_users() -> list:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, email, role, created_at, last_login, COALESCE(login_count, 0) as login_count FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_user_role(user_id: int, role: str) -> dict:
    if role not in ("admin", "user"):
        return {"ok": False, "error": "Role must be 'admin' or 'user'."}
    conn = get_db()
    try:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
