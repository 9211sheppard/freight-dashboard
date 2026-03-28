"""
api_auth.py  —  API key authentication for programmatic access
Key format: fid_ + 40 random alphanumeric chars
"""

import secrets
import string
from datetime import datetime, timedelta
from database import get_db
from crypto import hash_token
import json


def _constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    return secrets.compare_digest(a.encode(), b.encode())


def _gen_api_key() -> str:
    """Generate a new API key with fid_ prefix."""
    chars = string.ascii_letters + string.digits
    body = "".join(secrets.choice(chars) for _ in range(40))
    return f"fid_{body}"


def create_api_key(user_id: int, tenant_id: int, name: str = "",
                   permissions: dict = None, expires_days: int = None) -> dict:
    """Create a new API key. Returns the plaintext key ONCE — it cannot be retrieved again."""
    key = _gen_api_key()
    prefix = key[:12]
    key_hash = hash_token(key)
    now = datetime.now().isoformat()

    expires_at = ""
    if expires_days:
        expires_at = (datetime.now() + timedelta(days=expires_days)).isoformat()

    perms_json = json.dumps(permissions or {})

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO api_keys "
            "(tenant_id, user_id, key_hash, key_prefix, name, permissions, last_used, expires_at, revoked, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,0,?)",
            (tenant_id, user_id, key_hash, prefix, name or "Unnamed Key",
             perms_json, "", expires_at, now)
        )
        conn.commit()
        return {
            "ok": True,
            "key": key,  # Plaintext — shown once
            "key_id": cur.lastrowid,
            "prefix": prefix,
            "name": name,
            "expires_at": expires_at,
        }
    finally:
        conn.close()


def validate_api_key(key: str) -> dict:
    """Validate an API key. Returns user context dict or None."""
    if not key or not key.startswith("fid_"):
        return None

    prefix = key[:12]
    key_hash = hash_token(key)

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT ak.id, ak.tenant_id, ak.user_id, ak.key_hash, ak.permissions, ak.expires_at, ak.revoked, "
            "u.name, u.email, u.role "
            "FROM api_keys ak JOIN users u ON ak.user_id = u.id "
            "WHERE ak.key_prefix = ?",
            (prefix,)
        ).fetchone()

        if not row:
            return None
        # Constant-time hash comparison to prevent timing attacks
        if not _constant_time_compare(key_hash, row["key_hash"]):
            return None
        if row["revoked"]:
            return None
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) < datetime.now():
            return None

        # Update last_used
        conn.execute(
            "UPDATE api_keys SET last_used = ? WHERE id = ?",
            (datetime.now().isoformat(), row["id"])
        )
        conn.commit()

        try:
            perms = json.loads(row["permissions"])
        except Exception:
            perms = {}

        return {
            "api_key_id": row["id"],
            "user_id":    row["user_id"],
            "tenant_id":  row["tenant_id"],
            "name":       row["name"],
            "email":      row["email"],
            "role":       row["role"],
            "permissions": perms,
        }
    finally:
        conn.close()


def revoke_api_key(key_id: int, user_id: int, tenant_id: int) -> dict:
    """Revoke an API key."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM api_keys WHERE id = ? AND user_id = ? AND tenant_id = ?",
            (key_id, user_id, tenant_id)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "API key not found."}
        conn.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def list_api_keys(user_id: int, tenant_id: int) -> list:
    """List all API keys for a user (metadata only, no hashes)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, key_prefix, name, last_used, expires_at, revoked, created_at "
            "FROM api_keys WHERE user_id = ? AND tenant_id = ? ORDER BY created_at DESC",
            (user_id, tenant_id)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
