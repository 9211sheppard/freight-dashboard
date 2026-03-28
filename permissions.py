"""
permissions.py  —  Granular feature-level access control
Master user (tenant admin) controls who can read/write/delete/export each feature.
"""

import json
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for, jsonify, request, g, render_template_string
from database import get_db


# ── Feature registry ─────────────────────────────────────────────────────────
FEATURES = [
    "contacts", "rates", "lanes", "schedules", "outreach",
    "carriers", "billing", "admin", "agents", "learning",
    "reports", "quotes", "helpbot",
]

ACTIONS = ["read", "write", "delete", "export"]

# ── Role-based defaults ─────────────────────────────────────────────────────
_ROLE_DEFAULTS = {
    "admin": {f: {a: True for a in ACTIONS} for f in FEATURES},
    "internal": {f: {a: True for a in ACTIONS} for f in FEATURES},
    "user": {
        "contacts":  {"read": True,  "write": True,  "delete": False, "export": True},
        "rates":     {"read": True,  "write": True,  "delete": False, "export": True},
        "lanes":     {"read": True,  "write": False, "delete": False, "export": False},
        "schedules": {"read": True,  "write": False, "delete": False, "export": False},
        "outreach":  {"read": True,  "write": True,  "delete": False, "export": False},
        "carriers":  {"read": True,  "write": False, "delete": False, "export": False},
        "billing":   {"read": True,  "write": False, "delete": False, "export": False},
        "admin":     {"read": False, "write": False, "delete": False, "export": False},
        "agents":    {"read": True,  "write": False, "delete": False, "export": False},
        "learning":  {"read": True,  "write": True,  "delete": False, "export": False},
        "reports":   {"read": True,  "write": False, "delete": False, "export": True},
        "quotes":    {"read": True,  "write": True,  "delete": False, "export": True},
        "helpbot":   {"read": True,  "write": False, "delete": False, "export": False},
    },
    "customer": {
        "contacts":  {"read": True,  "write": False, "delete": False, "export": False},
        "rates":     {"read": True,  "write": True,  "delete": False, "export": False},
        "lanes":     {"read": True,  "write": False, "delete": False, "export": False},
        "schedules": {"read": True,  "write": False, "delete": False, "export": False},
        "outreach":  {"read": False, "write": False, "delete": False, "export": False},
        "carriers":  {"read": True,  "write": False, "delete": False, "export": False},
        "billing":   {"read": True,  "write": True,  "delete": False, "export": False},
        "admin":     {"read": False, "write": False, "delete": False, "export": False},
        "agents":    {"read": False, "write": False, "delete": False, "export": False},
        "learning":  {"read": True,  "write": True,  "delete": False, "export": False},
        "reports":   {"read": False, "write": False, "delete": False, "export": False},
        "quotes":    {"read": True,  "write": True,  "delete": False, "export": False},
        "helpbot":   {"read": True,  "write": False, "delete": False, "export": False},
    },
}


def get_default_permissions(role: str) -> dict:
    """Return default permission map for a given role."""
    return _ROLE_DEFAULTS.get(role, _ROLE_DEFAULTS["customer"])


# ── Database operations ──────────────────────────────────────────────────────

def get_user_permissions(user_id: int, tenant_id: int) -> dict:
    """Return full permission map for a user, merging DB overrides with role defaults."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT role FROM users WHERE id = ? AND tenant_id = ?",
            (user_id, tenant_id)
        ).fetchone()
        role = row["role"] if row else "customer"
        defaults = get_default_permissions(role)

        # Admin always gets everything — no overrides possible
        if role == "admin":
            return defaults

        rows = conn.execute(
            "SELECT feature, can_read, can_write, can_delete, can_export "
            "FROM user_permissions WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id)
        ).fetchall()

        if not rows:
            return defaults

        perms = {}
        for f in FEATURES:
            perms[f] = dict(defaults.get(f, {a: False for a in ACTIONS}))

        for r in rows:
            feat = r["feature"]
            if feat in perms:
                perms[feat] = {
                    "read":   bool(r["can_read"]),
                    "write":  bool(r["can_write"]),
                    "delete": bool(r["can_delete"]),
                    "export": bool(r["can_export"]),
                }
        return perms
    finally:
        conn.close()


def check_permission(user_id: int, tenant_id: int, feature: str, action: str = "read") -> bool:
    """Check if a user has a specific permission. Admins always pass."""
    # Fast path: check session cache
    cached = session.get("_permissions")
    if cached and isinstance(cached, dict):
        feat_perms = cached.get(feature, {})
        return bool(feat_perms.get(action, False))

    perms = get_user_permissions(user_id, tenant_id)
    feat_perms = perms.get(feature, {})
    return bool(feat_perms.get(action, False))


def set_permission(admin_user_id: int, target_user_id: int, tenant_id: int,
                   feature: str, permissions: dict) -> dict:
    """Master user sets permissions for a specific feature on a target user."""
    if feature not in FEATURES:
        return {"ok": False, "error": f"Unknown feature: {feature}"}

    conn = get_db()
    try:
        # Verify admin is actually admin of this tenant
        admin_row = conn.execute(
            "SELECT role FROM users WHERE id = ? AND tenant_id = ?",
            (admin_user_id, tenant_id)
        ).fetchone()
        if not admin_row or admin_row["role"] != "admin":
            return {"ok": False, "error": "Only tenant admins can modify permissions."}

        # Cannot modify another admin's permissions
        target_row = conn.execute(
            "SELECT role FROM users WHERE id = ? AND tenant_id = ?",
            (target_user_id, tenant_id)
        ).fetchone()
        if not target_row:
            return {"ok": False, "error": "User not found in this tenant."}
        if target_row["role"] == "admin" and target_user_id != admin_user_id:
            return {"ok": False, "error": "Cannot modify another admin's permissions."}

        now = datetime.now().isoformat()
        can_read   = 1 if permissions.get("read",   False) else 0
        can_write  = 1 if permissions.get("write",  False) else 0
        can_delete = 1 if permissions.get("delete", False) else 0
        can_export = 1 if permissions.get("export", False) else 0

        # Upsert
        existing = conn.execute(
            "SELECT id FROM user_permissions WHERE user_id = ? AND tenant_id = ? AND feature = ?",
            (target_user_id, tenant_id, feature)
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE user_permissions SET can_read=?, can_write=?, can_delete=?, can_export=?, "
                "granted_by=?, granted_at=? WHERE id=?",
                (can_read, can_write, can_delete, can_export, admin_user_id, now, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO user_permissions "
                "(user_id, tenant_id, feature, can_read, can_write, can_delete, can_export, granted_by, granted_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (target_user_id, tenant_id, feature, can_read, can_write, can_delete, can_export,
                 admin_user_id, now)
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def bulk_set_permissions(admin_user_id: int, target_user_id: int, tenant_id: int,
                         permissions_map: dict) -> dict:
    """Set permissions for multiple features at once."""
    errors = []
    for feature, perms in permissions_map.items():
        result = set_permission(admin_user_id, target_user_id, tenant_id, feature, perms)
        if not result["ok"]:
            errors.append(f"{feature}: {result['error']}")
    if errors:
        return {"ok": False, "errors": errors}
    return {"ok": True}


def initialize_defaults(user_id: int, tenant_id: int, role: str):
    """Populate user_permissions rows with role-based defaults for a new user."""
    defaults = get_default_permissions(role)
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        for feature, perms in defaults.items():
            conn.execute(
                "INSERT INTO user_permissions "
                "(user_id, tenant_id, feature, can_read, can_write, can_delete, can_export, granted_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (user_id, tenant_id, feature,
                 1 if perms["read"] else 0,
                 1 if perms["write"] else 0,
                 1 if perms["delete"] else 0,
                 1 if perms["export"] else 0,
                 now)
            )
        conn.commit()
    finally:
        conn.close()


def revoke_all(admin_user_id: int, target_user_id: int, tenant_id: int) -> dict:
    """Revoke all permissions for a user (nuclear option)."""
    conn = get_db()
    try:
        admin_row = conn.execute(
            "SELECT role FROM users WHERE id = ? AND tenant_id = ?",
            (admin_user_id, tenant_id)
        ).fetchone()
        if not admin_row or admin_row["role"] != "admin":
            return {"ok": False, "error": "Only tenant admins can revoke permissions."}

        conn.execute(
            "UPDATE user_permissions SET can_read=0, can_write=0, can_delete=0, can_export=0, "
            "granted_by=?, granted_at=? WHERE user_id=? AND tenant_id=?",
            (admin_user_id, datetime.now().isoformat(), target_user_id, tenant_id)
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# ── Permission templates ─────────────────────────────────────────────────────

def save_template(tenant_id: int, name: str, permissions: dict, created_by: int) -> dict:
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO permission_templates (tenant_id, template_name, permissions, created_by, created_at) "
            "VALUES (?,?,?,?,?)",
            (tenant_id, name, json.dumps(permissions), created_by, datetime.now().isoformat())
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def list_templates(tenant_id: int) -> list:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, template_name, permissions, created_at FROM permission_templates "
            "WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,)
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["permissions"] = json.loads(d["permissions"])
            except Exception:
                pass
            results.append(d)
        return results
    finally:
        conn.close()


# ── Decorator ─────────────────────────────────────────────────────────────────

def feature_required(feature: str, action: str = "read"):
    """Decorator: require a specific permission to access a route.
    Works with both session auth and API key auth (via g.api_user)."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # API key auth path
            api_user = getattr(g, "api_user", None)
            if api_user:
                api_perms = api_user.get("permissions", {})
                feat_perms = api_perms.get(feature, {})
                if not feat_perms.get(action, False):
                    return jsonify({"ok": False, "error": "Insufficient API key permissions."}), 403
                return f(*args, **kwargs)

            # Session auth path
            if not session.get("logged_in"):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Authentication required."}), 401
                return redirect(url_for("login"))

            user_id   = session.get("user_id")
            tenant_id = session.get("tenant_id", 1)

            if not check_permission(user_id, tenant_id, feature, action):
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Access denied."}), 403
                return render_template_string(
                    "<h2>Access Denied</h2><p>You don't have permission to access this feature. "
                    "Contact your administrator.</p>"
                ), 403

            return f(*args, **kwargs)
        return decorated
    return decorator
