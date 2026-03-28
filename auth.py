"""
auth.py  —  Per-user authentication for the Freight Intelligence Dashboard
Provides:
  - User registration with password policy enforcement
  - Email/password login with bcrypt + account lockout
  - MFA (TOTP) support
  - Password reset via email token
  - Password history (prevent reuse)
  - Session hardening
  - Audit logging integration
"""

import hashlib
import bcrypt
import secrets
import string
from datetime import datetime, timedelta
from database import get_db
from config import (
    EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASS, EMAIL_FROM,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES, MFA_ISSUER_NAME,
)

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
    """Send an email via Microsoft Graph API."""
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


def _audit(tenant_id, user_id, action, resource="", details="", ip="", user_agent=""):
    """Log an audit event (fail-safe — never crashes)."""
    try:
        from audit import log_event
        log_event(tenant_id=tenant_id, user_id=user_id, action=action,
                  resource=resource, details=details, ip=ip, user_agent=user_agent)
    except Exception:
        pass


def _check_password_history(user_id: int, new_password: str, limit: int = 5) -> bool:
    """Return True if password was used in the last `limit` passwords."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT password_hash FROM password_history WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        for r in rows:
            if _check(new_password, r["password_hash"]):
                return True
        return False
    finally:
        conn.close()


def _save_password_history(user_id: int, password_hash: str):
    """Store old password hash in history."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO password_history (user_id, password_hash, created_at) VALUES (?,?,?)",
            (user_id, password_hash, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────────────────────────────────────

def register_user(name: str, email: str, password: str, role: str = "user",
                   company_name: str = "", tenant_id: int = None) -> dict:
    """
    Create a new user + tenant with password policy enforcement.
    """
    from validators import validate_password, sanitize_string, validate_email_format

    email = email.strip().lower()
    name  = sanitize_string(name, max_length=100)

    if not name or not email or not password:
        return {"ok": False, "error": "Name, email, and password are required."}
    if not validate_email_format(email):
        return {"ok": False, "error": "Please enter a valid email address."}

    # Password policy
    valid, err = validate_password(password, email=email)
    if not valid:
        return {"ok": False, "error": err}

    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            return {"ok": False, "error": "Registration failed. Please try again or reset your password."}

        # Create or join tenant
        if tenant_id is None:
            from tenant import create_tenant
            t_name = sanitize_string(company_name, max_length=200) or f"{name}'s Workspace"
            t_result = create_tenant(t_name)
            if not t_result["ok"]:
                return {"ok": False, "error": f"Could not create workspace: {t_result['error']}"}
            tenant_id = t_result["tenant_id"]
            role = "admin"
        else:
            count = conn.execute("SELECT COUNT(*) FROM users WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
            if count == 0:
                role = "admin"

        if email in ADMIN_EMAILS:
            role = "admin"

        hashed = _hash(password)
        now    = datetime.now().isoformat()
        cur    = conn.execute(
            "INSERT INTO users (tenant_id, name, email, password_hash, role, created_at) VALUES (?,?,?,?,?,?)",
            (tenant_id, name, email, hashed, role, now)
        )
        conn.commit()

        user_id = cur.lastrowid

        # Initialize password history
        _save_password_history(user_id, hashed)

        # Initialize default permissions
        try:
            from permissions import initialize_defaults
            initialize_defaults(user_id, tenant_id, role)
        except Exception:
            pass

        _audit(tenant_id, user_id, "user_registered", resource=f"user:{user_id}",
               details=f"role={role}")

        return {"ok": True, "user_id": user_id, "role": role, "tenant_id": tenant_id}
    except Exception as e:
        return {"ok": False, "error": "Registration failed. Please try again."}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Login (with account lockout)
# ─────────────────────────────────────────────────────────────────────────────

def login_user(email: str, password: str, ip: str = "") -> dict:
    """
    Validate credentials with account lockout protection.
    Returns {"ok": True, "user": {...}, "mfa_required": bool}
    """
    email = email.strip().lower()
    conn  = get_db()
    try:
        row = conn.execute(
            "SELECT id, tenant_id, name, email, password_hash, role, "
            "COALESCE(failed_login_attempts, 0) as failed_login_attempts, "
            "locked_until, COALESCE(mfa_enabled, 0) as mfa_enabled "
            "FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if not row:
            # Generic error to prevent user enumeration
            _audit(None, None, "login_failed", details="unknown_email", ip=ip)
            return {"ok": False, "error": "Invalid email or password."}

        user_id   = row["id"]
        tenant_id = row["tenant_id"] or 1

        # Check account lockout
        locked_until = row["locked_until"] or ""
        if locked_until:
            try:
                lock_time = datetime.fromisoformat(locked_until)
                if datetime.now() < lock_time:
                    remaining = int((lock_time - datetime.now()).total_seconds() / 60) + 1
                    _audit(tenant_id, user_id, "login_blocked_locked",
                           details=f"locked for {remaining} more minutes", ip=ip)
                    return {"ok": False, "error": f"Account locked. Try again in {remaining} minute(s)."}
                else:
                    # Lock expired — reset
                    conn.execute(
                        "UPDATE users SET failed_login_attempts = 0, locked_until = '' WHERE id = ?",
                        (user_id,)
                    )
            except (ValueError, TypeError):
                pass

        # Check password
        if not _check(password, row["password_hash"]):
            attempts = row["failed_login_attempts"] + 1
            if attempts >= MAX_LOGIN_ATTEMPTS:
                lock_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
                conn.execute(
                    "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
                    (attempts, lock_until, user_id)
                )
                conn.commit()
                _audit(tenant_id, user_id, "account_locked",
                       details=f"locked after {attempts} failed attempts", ip=ip)
                return {"ok": False, "error": f"Account locked for {LOCKOUT_MINUTES} minutes after too many failed attempts."}
            else:
                conn.execute(
                    "UPDATE users SET failed_login_attempts = ? WHERE id = ?",
                    (attempts, user_id)
                )
                conn.commit()
                _audit(tenant_id, user_id, "login_failed",
                       details=f"attempt {attempts}/{MAX_LOGIN_ATTEMPTS}", ip=ip)
                return {"ok": False, "error": "Invalid email or password."}

        # Check subscription
        from tenant import check_subscription
        sub = check_subscription(tenant_id)
        if not sub["active"]:
            reason = sub.get("reason", "inactive")
            if reason == "trial_expired":
                return {"ok": False, "error": "Your free trial has expired. Please upgrade to continue.", "paywall": True}
            elif reason in ("cancelled", "inactive"):
                return {"ok": False, "error": "Your subscription is inactive. Please reactivate to continue.", "paywall": True}

        # Success — reset failed attempts
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE users SET last_login = ?, login_count = COALESCE(login_count, 0) + 1, "
            "failed_login_attempts = 0, locked_until = '' WHERE id = ?",
            (now, user_id)
        )
        conn.execute(
            "INSERT INTO user_logins (user_id, login_at, ip_address) VALUES (?, ?, ?)",
            (user_id, now, ip)
        )
        conn.commit()

        user_data = {
            "id":        user_id,
            "tenant_id": tenant_id,
            "name":      row["name"],
            "email":     row["email"],
            "role":      row["role"],
        }

        # Check if MFA is required
        if row["mfa_enabled"]:
            _audit(tenant_id, user_id, "login_mfa_pending", ip=ip)
            return {"ok": True, "user": user_data, "mfa_required": True}

        _audit(tenant_id, user_id, "login_success", ip=ip)
        return {"ok": True, "user": user_data, "mfa_required": False}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  MFA (TOTP)
# ─────────────────────────────────────────────────────────────────────────────

def setup_mfa(user_id: int) -> dict:
    """Generate MFA secret and QR code for setup."""
    import pyotp
    import qrcode
    import qrcode.image.svg
    import base64
    import io

    conn = get_db()
    try:
        row = conn.execute("SELECT email, mfa_enabled FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "User not found."}
        if row["mfa_enabled"]:
            return {"ok": False, "error": "MFA is already enabled."}

        secret = pyotp.random_base32()
        uri = pyotp.TOTP(secret).provisioning_uri(name=row["email"], issuer_name=MFA_ISSUER_NAME)

        # Generate QR code as SVG data URI
        image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
        buffer = io.BytesIO()
        image.save(buffer)
        qr_data_uri = f"data:image/svg+xml;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"

        # Generate backup codes
        backup_codes = [_gen_token(8) for _ in range(10)]
        backup_hashes = [_hash(code) for code in backup_codes]

        # Store secret (encrypted) temporarily — not enabled until verified
        try:
            from crypto import encrypt_field
            encrypted_secret = encrypt_field(secret)
        except Exception:
            encrypted_secret = secret

        conn.execute(
            "UPDATE users SET mfa_secret = ?, mfa_backup_codes = ? WHERE id = ?",
            (encrypted_secret, ",".join(backup_hashes), user_id)
        )
        conn.commit()

        return {
            "ok": True,
            "secret": secret,
            "qr_code": qr_data_uri,
            "backup_codes": backup_codes,
        }
    finally:
        conn.close()


def enable_mfa(user_id: int, code: str) -> dict:
    """Verify TOTP code and enable MFA."""
    import pyotp

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT mfa_secret, mfa_enabled FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not row["mfa_secret"]:
            return {"ok": False, "error": "MFA setup not started. Please start setup first."}
        if row["mfa_enabled"]:
            return {"ok": False, "error": "MFA is already enabled."}

        try:
            from crypto import decrypt_field
            secret = decrypt_field(row["mfa_secret"])
        except Exception:
            secret = row["mfa_secret"]

        if not secret:
            return {"ok": False, "error": "MFA secret not found."}

        token = code.replace(" ", "")
        if not pyotp.TOTP(secret).verify(token, valid_window=1):
            return {"ok": False, "error": "Invalid verification code. Please try again."}

        conn.execute("UPDATE users SET mfa_enabled = 1 WHERE id = ?", (user_id,))
        conn.commit()

        _audit(None, user_id, "mfa_enabled")
        return {"ok": True}
    finally:
        conn.close()


def disable_mfa(user_id: int, password: str) -> dict:
    """Disable MFA (requires password confirmation)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not _check(password, row["password_hash"]):
            return {"ok": False, "error": "Incorrect password."}

        conn.execute(
            "UPDATE users SET mfa_enabled = 0, mfa_secret = '', mfa_backup_codes = '' WHERE id = ?",
            (user_id,)
        )
        conn.commit()

        _audit(None, user_id, "mfa_disabled")
        return {"ok": True}
    finally:
        conn.close()


def verify_mfa(user_id: int, code: str) -> dict:
    """Verify a TOTP code or backup code during login.
    Rate-limited: 5 failures = 15-minute lockout (same as password)."""
    import pyotp

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT mfa_secret, mfa_backup_codes, "
            "COALESCE(failed_login_attempts, 0) as failed_login_attempts, "
            "locked_until FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row or not row["mfa_secret"]:
            return {"ok": False, "error": "MFA not configured."}

        # Check MFA lockout (reuses account lockout fields)
        locked_until = row["locked_until"] or ""
        if locked_until:
            try:
                lock_time = datetime.fromisoformat(locked_until)
                if datetime.now() < lock_time:
                    remaining = int((lock_time - datetime.now()).total_seconds() / 60) + 1
                    return {"ok": False, "error": f"Too many failed attempts. Try again in {remaining} minute(s)."}
            except (ValueError, TypeError):
                pass

        try:
            from crypto import decrypt_field
            secret = decrypt_field(row["mfa_secret"])
        except Exception:
            secret = row["mfa_secret"]

        token = code.replace(" ", "")

        # Try TOTP first
        if pyotp.TOTP(secret).verify(token, valid_window=1):
            # Reset failed attempts on success
            conn.execute(
                "UPDATE users SET failed_login_attempts = 0, locked_until = '' WHERE id = ?",
                (user_id,)
            )
            conn.commit()
            _audit(None, user_id, "mfa_verified", details="totp")
            return {"ok": True}

        # Try backup codes
        backup_hashes = (row["mfa_backup_codes"] or "").split(",")
        for i, bh in enumerate(backup_hashes):
            if bh and _check(token, bh):
                backup_hashes[i] = ""
                conn.execute(
                    "UPDATE users SET mfa_backup_codes = ?, failed_login_attempts = 0, locked_until = '' WHERE id = ?",
                    (",".join(backup_hashes), user_id)
                )
                conn.commit()
                _audit(None, user_id, "mfa_verified", details="backup_code")
                return {"ok": True}

        # Failed — increment counter and potentially lock
        attempts = row["failed_login_attempts"] + 1
        if attempts >= MAX_LOGIN_ATTEMPTS:
            lock_until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            conn.execute(
                "UPDATE users SET failed_login_attempts = ?, locked_until = ? WHERE id = ?",
                (attempts, lock_until, user_id)
            )
            conn.commit()
            _audit(None, user_id, "mfa_lockout", details=f"locked after {attempts} failed MFA attempts")
            return {"ok": False, "error": f"Account locked for {LOCKOUT_MINUTES} minutes after too many failed attempts."}
        else:
            conn.execute(
                "UPDATE users SET failed_login_attempts = ? WHERE id = ?",
                (attempts, user_id)
            )
            conn.commit()

        _audit(None, user_id, "mfa_failed", details=f"attempt {attempts}/{MAX_LOGIN_ATTEMPTS}")
        return {"ok": False, "error": "Invalid verification code."}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Password Reset (with password policy)
# ─────────────────────────────────────────────────────────────────────────────

def request_password_reset(email: str, base_url: str = "http://localhost:5000") -> dict:
    """Generate a reset token, store it, and email the link.
    Rate-limited: max 1 reset per email per 5 minutes."""
    email = email.strip().lower()
    conn  = get_db()
    try:
        # Rate limit: check for recent reset requests
        recent = conn.execute(
            "SELECT COUNT(*) FROM password_resets WHERE email = ? AND used = 0 AND expires_at > ?",
            (email, (datetime.now() - timedelta(minutes=5)).isoformat())
        ).fetchone()[0]
        if recent >= 1:
            return {"ok": True}  # Silent — don't reveal rate limiting

        user = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            return {"ok": True}

        token      = _gen_token()
        expires_at = (datetime.now() + timedelta(hours=2)).isoformat()

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

        _audit(None, user["id"], "password_reset_requested", ip="")
        return {"ok": True, "token": token}
    except Exception as e:
        print(f"[auth] request_password_reset error: {e}")
        return {"ok": True}
    finally:
        conn.close()


def reset_password(token: str, new_password: str) -> dict:
    """Validate token and set new password with policy enforcement."""
    from validators import validate_password

    valid, err = validate_password(new_password)
    if not valid:
        return {"ok": False, "error": err}

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

        # Get user to check password history
        user = conn.execute("SELECT id, password_hash FROM users WHERE email = ?", (row["email"],)).fetchone()
        if user and _check_password_history(user["id"], new_password):
            return {"ok": False, "error": "Cannot reuse a recent password. Please choose a different one."}

        # Save old hash to history
        if user:
            _save_password_history(user["id"], user["password_hash"])

        hashed = _hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ?",
            (hashed, row["email"])
        )
        conn.execute("UPDATE password_resets SET used = 1 WHERE token = ?", (token,))
        conn.commit()

        if user:
            _audit(None, user["id"], "password_reset_completed")

        return {"ok": True}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Session helpers (hardened)
# ─────────────────────────────────────────────────────────────────────────────

def set_session(session, user: dict, ip: str = "", user_agent: str = ""):
    """Store user info in Flask session with security metadata.
    Enforces single active session per user — kills all previous sessions."""
    user_id   = user["id"]
    tenant_id = user.get("tenant_id", 1)

    # Generate unique session token
    session_token = secrets.token_urlsafe(32)

    # Kill previous sessions for this user (single-session enforcement)
    _invalidate_user_sessions(user_id, new_ip=ip, new_ua=user_agent)

    # Register new session
    _register_session(user_id, session_token, ip, user_agent)

    # Clear existing session data to prevent session fixation
    session.clear()
    session["logged_in"]      = True
    session["user_id"]        = user_id
    session["user_name"]      = user["name"]
    session["user_email"]     = user["email"]
    session["user_role"]      = user["role"]
    session["tenant_id"]      = tenant_id
    session["_created_at"]    = datetime.now().isoformat()
    session["_session_token"] = session_token
    session["_ua_hash"]       = ""
    session.permanent         = True

    # Cache permissions in session
    try:
        from permissions import get_user_permissions
        session["_permissions"] = get_user_permissions(user_id, tenant_id)
    except Exception:
        pass


def clear_session(session):
    # Remove active session record before clearing
    token = session.get("_session_token")
    if token:
        try:
            conn = get_db()
            conn.execute("DELETE FROM active_sessions WHERE session_token = ?", (token,))
            conn.commit()
            conn.close()
        except Exception:
            pass
    session.clear()


def _invalidate_user_sessions(user_id: int, new_ip: str = "", new_ua: str = ""):
    """Kill all active sessions for a user. Detect and log password sharing."""
    conn = get_db()
    try:
        # Check if there's an active session from a DIFFERENT IP (password sharing indicator)
        existing = conn.execute(
            "SELECT ip_address, user_agent, created_at FROM active_sessions WHERE user_id = ?",
            (user_id,)
        ).fetchall()

        if existing and new_ip:
            for old in existing:
                old_ip = old["ip_address"] or ""
                if old_ip and old_ip != new_ip:
                    # Different IP = possible password sharing
                    _audit(None, user_id, "concurrent_session_detected",
                           details=f"old_ip={old_ip}, new_ip={new_ip}, old_ua={old['user_agent'][:80]}",
                           ip=new_ip)

                    # Notify admin
                    _notify_admin_sharing(user_id, old_ip, new_ip)

        # Kill all existing sessions
        conn.execute("DELETE FROM active_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _register_session(user_id: int, session_token: str, ip: str = "", user_agent: str = ""):
    """Register a new active session in the database."""
    try:
        conn = get_db()
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO active_sessions (user_id, session_token, ip_address, user_agent, created_at, last_seen) "
            "VALUES (?,?,?,?,?,?)",
            (user_id, session_token, ip, user_agent[:200], now, now)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def validate_session_token(session) -> bool:
    """Check if the session token is still valid (not killed by a new login).
    Returns False if session was invalidated = someone else logged in as this user."""
    token = session.get("_session_token")
    if not token:
        return True  # Legacy session without token — allow

    try:
        conn = get_db()
        row = conn.execute(
            "SELECT id FROM active_sessions WHERE session_token = ?", (token,)
        ).fetchone()

        if row:
            # Update last_seen
            conn.execute(
                "UPDATE active_sessions SET last_seen = ? WHERE session_token = ?",
                (datetime.now().isoformat(), token)
            )
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False  # Session was killed — another login happened
    except Exception:
        return True  # Fail open


def _notify_admin_sharing(user_id: int, old_ip: str, new_ip: str):
    """Notify tenant admin when password sharing is detected."""
    try:
        conn = get_db()
        user = conn.execute(
            "SELECT name, email, tenant_id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user:
            conn.close()
            return

        # Find admin of the tenant
        admin = conn.execute(
            "SELECT email, name FROM users WHERE tenant_id = ? AND role = 'admin' LIMIT 1",
            (user["tenant_id"],)
        ).fetchone()
        conn.close()

        if admin and admin["email"] != user["email"]:
            _send_email(
                to=admin["email"],
                subject="Security Alert: Possible Password Sharing Detected",
                body=(
                    f"Hi {admin['name']},\n\n"
                    f"We detected a potential password sharing incident:\n\n"
                    f"User: {user['name']} ({user['email']})\n"
                    f"Previous session IP: {old_ip}\n"
                    f"New login IP: {new_ip}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"The same account was accessed from two different locations. "
                    f"The previous session has been terminated.\n\n"
                    f"If this is unexpected, consider:\n"
                    f"- Resetting the user's password\n"
                    f"- Enforcing MFA for all users\n"
                    f"- Reviewing the audit log\n\n"
                    f"— Freight Intelligence Security"
                ),
            )
    except Exception:
        pass


def check_mfa_enforced(tenant_id: int) -> bool:
    """Check if the tenant requires MFA for all users."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COALESCE(mfa_enforced, 0) as mfa_enforced FROM tenants WHERE id = ?",
            (tenant_id,)
        ).fetchone()
        conn.close()
        return bool(row and row["mfa_enforced"])
    except Exception:
        return False


def is_user_mfa_enabled(user_id: int) -> bool:
    """Check if a specific user has MFA enabled."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COALESCE(mfa_enabled, 0) as mfa_enabled FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        conn.close()
        return bool(row and row["mfa_enabled"])
    except Exception:
        return False


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
#  Change password (with policy + history)
# ─────────────────────────────────────────────────────────────────────────────

def change_password(user_id: int, old_password: str, new_password: str) -> dict:
    from validators import validate_password

    valid, err = validate_password(new_password)
    if not valid:
        return {"ok": False, "error": err}

    conn = get_db()
    try:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not _check(old_password, row["password_hash"]):
            return {"ok": False, "error": "Current password is incorrect."}

        if _check_password_history(user_id, new_password):
            return {"ok": False, "error": "Cannot reuse a recent password. Please choose a different one."}

        _save_password_history(user_id, row["password_hash"])

        new_hash = _hash(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, user_id)
        )
        conn.commit()

        _audit(None, user_id, "password_changed")
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
            "SELECT id, name, email, role, created_at, last_login, "
            "COALESCE(login_count, 0) as login_count, "
            "COALESCE(mfa_enabled, 0) as mfa_enabled "
            "FROM users ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_user_role(user_id: int, role: str) -> dict:
    if role not in ("admin", "internal", "user", "customer"):
        return {"ok": False, "error": "Role must be 'admin', 'internal', 'user', or 'customer'."}
    conn = get_db()
    try:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
        _audit(None, user_id, "role_changed", details=f"new_role={role}")
        return {"ok": True}
    finally:
        conn.close()


def is_internal(session) -> bool:
    """Check if current user is an internal team member."""
    return session.get("user_role") in ("admin", "internal")


def is_customer(session) -> bool:
    """Check if current user is an external paying customer."""
    return session.get("user_role") in ("customer", "user")
