"""
oauth.py  —  OAuth2 authorization code flow for Google and Microsoft SSO
"""

import json
import secrets
import urllib.request
import urllib.parse
from config import (
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
    MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET,
    OAUTH_REDIRECT_BASE,
)


def google_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def microsoft_enabled() -> bool:
    return bool(MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET)


# ── Google OAuth2 ─────────────────────────────────────────────────────────────

def get_google_auth_url(state: str) -> str:
    """Build Google OAuth2 authorization URL."""
    params = urllib.parse.urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  f"{OAUTH_REDIRECT_BASE}/auth/google/callback",
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "online",
        "prompt":        "select_account",
    })
    return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"


def handle_google_callback(code: str) -> dict:
    """Exchange authorization code for tokens, extract user info.
    Returns {"ok": True, "email": str, "name": str, "provider": "google"} or error."""
    try:
        # Exchange code for tokens
        data = urllib.parse.urlencode({
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  f"{OAUTH_REDIRECT_BASE}/auth/google/callback",
            "grant_type":    "authorization_code",
        }).encode()
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            tokens = json.loads(resp.read())

        # Get user info
        access_token = tokens["access_token"]
        req = urllib.request.Request("https://www.googleapis.com/oauth2/v3/userinfo")
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            user_info = json.loads(resp.read())

        email = user_info.get("email", "").lower().strip()
        name = user_info.get("name", email.split("@")[0])

        if not email:
            return {"ok": False, "error": "Could not retrieve email from Google."}

        return {"ok": True, "email": email, "name": name, "provider": "google"}
    except Exception as e:
        return {"ok": False, "error": f"Google authentication failed: {e}"}


# ── Microsoft OAuth2 ─────────────────────────────────────────────────────────

def get_microsoft_auth_url(state: str) -> str:
    """Build Microsoft OAuth2 authorization URL."""
    params = urllib.parse.urlencode({
        "client_id":     MICROSOFT_CLIENT_ID,
        "redirect_uri":  f"{OAUTH_REDIRECT_BASE}/auth/microsoft/callback",
        "response_type": "code",
        "scope":         "openid email profile User.Read",
        "state":         state,
        "response_mode": "query",
    })
    return f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{params}"


def handle_microsoft_callback(code: str) -> dict:
    """Exchange authorization code for tokens, extract user info."""
    try:
        data = urllib.parse.urlencode({
            "code":          code,
            "client_id":     MICROSOFT_CLIENT_ID,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "redirect_uri":  f"{OAUTH_REDIRECT_BASE}/auth/microsoft/callback",
            "grant_type":    "authorization_code",
            "scope":         "openid email profile User.Read",
        }).encode()
        req = urllib.request.Request(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data=data, method="POST"
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            tokens = json.loads(resp.read())

        access_token = tokens["access_token"]
        req = urllib.request.Request("https://graph.microsoft.com/v1.0/me")
        req.add_header("Authorization", f"Bearer {access_token}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            user_info = json.loads(resp.read())

        email = (user_info.get("mail") or user_info.get("userPrincipalName", "")).lower().strip()
        name = user_info.get("displayName", email.split("@")[0])

        if not email:
            return {"ok": False, "error": "Could not retrieve email from Microsoft."}

        return {"ok": True, "email": email, "name": name, "provider": "microsoft"}
    except Exception as e:
        return {"ok": False, "error": f"Microsoft authentication failed: {e}"}


# ── Shared: link or create user ───────────────────────────────────────────────

def oauth_login_or_register(email: str, name: str, provider: str, ip: str = "") -> dict:
    """Find existing user by email or create a new one. Returns auth result."""
    from database import get_db
    from datetime import datetime

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, tenant_id, name, email, role, "
            "COALESCE(mfa_enabled, 0) as mfa_enabled FROM users WHERE email = ?",
            (email,)
        ).fetchone()

        if row:
            # Existing user — log them in (OAuth = trusted identity, skip MFA)
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

            from audit import log_event
            log_event(row["tenant_id"], row["id"], "oauth_login",
                      details=f"provider={provider}", ip=ip)

            return {
                "ok": True,
                "user": {
                    "id": row["id"],
                    "tenant_id": row["tenant_id"] or 1,
                    "name": row["name"],
                    "email": row["email"],
                    "role": row["role"],
                },
            }
        else:
            # New user — register via OAuth
            import auth as _auth
            result = _auth.register_user(
                name=name, email=email,
                password=secrets.token_urlsafe(32),  # Random password (they'll use OAuth)
                role="customer", company_name="",
            )
            if result["ok"]:
                from audit import log_event
                log_event(result.get("tenant_id"), result.get("user_id"),
                          "oauth_register", details=f"provider={provider}", ip=ip)

                user_row = conn.execute(
                    "SELECT id, tenant_id, name, email, role FROM users WHERE id = ?",
                    (result["user_id"],)
                ).fetchone()
                return {
                    "ok": True,
                    "user": dict(user_row) if user_row else {
                        "id": result["user_id"],
                        "tenant_id": result.get("tenant_id", 1),
                        "name": name,
                        "email": email,
                        "role": result.get("role", "customer"),
                    },
                    "new_user": True,
                }
            return result
    finally:
        conn.close()
