import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g
from werkzeug.security import check_password_hash, generate_password_hash

from .enterprise import (
    LOCKOUT_THRESHOLD,
    is_locked_until,
    next_lockout_timestamp,
    normalize_tenant_id,
    parse_ip_rules,
    validate_password_complexity,
)


ROLE_CHOICES = ("admin", "dispatcher", "viewer")
PLAN_CHOICES = ("starter", "pro", "enterprise")
TENANT_STATUS_CHOICES = ("active", "suspended", "deleted")
DEFAULT_TENANT_ID = "tenant-default"
SUPPORTED_PASSWORD_HASH_PREFIXES = ("pbkdf2:", "scrypt:")


def _looks_like_password_hash(value):
    normalized = str(value or "").strip().lower()
    return normalized.startswith(SUPPORTED_PASSWORD_HASH_PREFIXES)


def get_db():
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE_PATH"])
        db_path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()


def init_db():
    db = get_db()
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'starter',
            max_users INTEGER NOT NULL DEFAULT 5,
            data_region TEXT NOT NULL DEFAULT 'ca-central',
            allowed_ip_cidrs TEXT NOT NULL DEFAULT '[]',
            session_timeout_minutes INTEGER NOT NULL DEFAULT 30,
            saml_entity_id TEXT DEFAULT '',
            saml_sso_url TEXT DEFAULT '',
            saml_x509_cert TEXT DEFAULT '',
            saml_metadata_url TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _migrate_users_table(db)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            action TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id TEXT,
            changes_json TEXT NOT NULL DEFAULT '{}',
            ip TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant_email ON users(tenant_id, email)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_lookup ON audit_log(tenant_id, created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(user_id, action)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status)")
    db.commit()
    seed_tenants()
    seed_users()


def _migrate_users_table(db):
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users' LIMIT 1"
    ).fetchone()
    if row:
        columns = {item["name"] for item in db.execute("PRAGMA table_info(users)").fetchall()}
        if "tenant_id" not in columns:
            db.execute("ALTER TABLE users RENAME TO users_legacy")
            row = None

    if not row:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'dispatcher', 'viewer')),
                totp_secret TEXT DEFAULT '',
                totp_enabled INTEGER NOT NULL DEFAULT 0,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT DEFAULT '',
                password_change_required INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TEXT DEFAULT '',
                password_updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (tenant_id, email)
            )
            """
        )
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users_legacy' LIMIT 1"
        ).fetchone():
            db.execute(
                """
                INSERT INTO users (
                    tenant_id, full_name, email, password_hash, role,
                    totp_secret, totp_enabled, failed_login_attempts,
                    locked_until, password_change_required, created_at,
                    last_login_at, password_updated_at
                )
                SELECT
                    ?, full_name, email, password_hash, role,
                    COALESCE(totp_secret, ''), COALESCE(totp_enabled, 0), 0,
                    '', 1, COALESCE(created_at, CURRENT_TIMESTAMP),
                    COALESCE(last_login_at, ''), CURRENT_TIMESTAMP
                FROM users_legacy
                """,
                (DEFAULT_TENANT_ID,),
            )
            db.execute("DROP TABLE users_legacy")

    columns = {item["name"] for item in db.execute("PRAGMA table_info(users)").fetchall()}
    for column, definition in [
        ("tenant_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"),
        ("failed_login_attempts", "INTEGER NOT NULL DEFAULT 0"),
        ("locked_until", "TEXT DEFAULT ''"),
        ("password_change_required", "INTEGER NOT NULL DEFAULT 1"),
        ("password_updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")


def seed_tenants():
    db = get_db()
    db.execute(
        """
        INSERT OR IGNORE INTO tenants
            (tenant_id, company_name, plan, max_users, data_region, allowed_ip_cidrs, session_timeout_minutes, status)
        VALUES (?, ?, 'enterprise', 25, 'ca-central', '[]', 30, 'active')
        """,
        (
            current_app.config.get("TMS_DEFAULT_TENANT_ID", DEFAULT_TENANT_ID),
            current_app.config.get("TMS_DEFAULT_TENANT_NAME", "Sandbox Tenant"),
        ),
    )
    db.commit()


def seed_users():
    db = get_db()
    default_tenant_id = current_app.config.get("TMS_DEFAULT_TENANT_ID", DEFAULT_TENANT_ID)
    definitions = (
        (
            current_app.config["TMS_ADMIN_EMAIL"],
            current_app.config["TMS_ADMIN_PASSWORD"],
            current_app.config.get("TMS_ADMIN_PASSWORD_HASH", ""),
            current_app.config["TMS_ADMIN_NAME"],
            "admin",
        ),
        (
            current_app.config["TMS_DISPATCHER_EMAIL"],
            current_app.config["TMS_DISPATCHER_PASSWORD"],
            current_app.config.get("TMS_DISPATCHER_PASSWORD_HASH", ""),
            current_app.config["TMS_DISPATCHER_NAME"],
            "dispatcher",
        ),
        (
            current_app.config["TMS_VIEWER_EMAIL"],
            current_app.config["TMS_VIEWER_PASSWORD"],
            current_app.config.get("TMS_VIEWER_PASSWORD_HASH", ""),
            current_app.config["TMS_VIEWER_NAME"],
            "viewer",
        ),
    )

    for email, password, password_hash, full_name, role in definitions:
        if not email or not (password or password_hash):
            continue
        if password_hash:
            if not _looks_like_password_hash(password_hash):
                raise ValueError(f"Seed password hash for {email} uses an unsupported format.")
            stored_password_hash = str(password_hash).strip()
        else:
            policy_error = validate_password_complexity(password)
            if policy_error:
                raise ValueError(f"Seed password for {email} does not meet policy: {policy_error}")
            stored_password_hash = generate_password_hash(password)
        existing = db.execute(
            "SELECT id, role FROM users WHERE tenant_id = ? AND email = ?",
            (default_tenant_id, email.lower()),
        ).fetchone()
        if existing:
            if existing["role"] != role:
                db.execute(
                    "UPDATE users SET role = ? WHERE id = ?",
                    (role, existing["id"]),
                )
            continue
        db.execute(
            """
            INSERT INTO users (
                tenant_id, full_name, email, password_hash, role, password_change_required
            )
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                default_tenant_id,
                full_name,
                email.lower(),
                stored_password_hash,
                role,
            ),
        )
    db.commit()


def _tenant_payload(row):
    if not row:
        return None
    tenant = dict(row)
    raw_rules = tenant.get("allowed_ip_cidrs")
    try:
        raw_rules = json.loads(raw_rules) if isinstance(raw_rules, str) else raw_rules
    except (TypeError, ValueError):
        raw_rules = raw_rules
    tenant["allowed_ip_cidrs"] = parse_ip_rules(raw_rules)
    return tenant


def note_audit(tenant_id, user_id, action, table_name, record_id="", changes=None, ip=""):
    db = get_db()
    db.execute(
        """
        INSERT INTO audit_log (tenant_id, user_id, action, table_name, record_id, changes_json, ip)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            normalize_tenant_id(tenant_id),
            str(user_id or ""),
            action,
            table_name,
            str(record_id or ""),
            json.dumps(changes or {}, sort_keys=True),
            ip or "",
        ),
    )
    db.commit()


def list_audit_entries(*, tenant_id=None, user_id="", action="", start_date="", end_date=""):
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if tenant_id:
        query += " AND tenant_id = ?"
        params.append(normalize_tenant_id(tenant_id))
    if user_id:
        query += " AND user_id = ?"
        params.append(str(user_id))
    if action:
        query += " AND action = ?"
        params.append(action)
    if start_date:
        query += " AND date(created_at) >= date(?)"
        params.append(start_date)
    if end_date:
        query += " AND date(created_at) <= date(?)"
        params.append(end_date)
    query += " ORDER BY datetime(created_at) DESC, id DESC"
    rows = get_db().execute(query, params).fetchall()
    entries = []
    for row in rows:
        payload = dict(row)
        try:
            payload["changes"] = json.loads(payload.get("changes_json") or "{}")
        except (TypeError, ValueError):
            payload["changes"] = {}
        entries.append(payload)
    return entries


def list_tenants(include_deleted=False):
    query = "SELECT * FROM tenants"
    params = []
    if not include_deleted:
        query += " WHERE status != ?"
        params.append("deleted")
    query += " ORDER BY company_name"
    return [_tenant_payload(row) for row in get_db().execute(query, params).fetchall()]


def get_tenant_by_id(tenant_id):
    row = get_db().execute(
        "SELECT * FROM tenants WHERE tenant_id = ?",
        (normalize_tenant_id(tenant_id),),
    ).fetchone()
    return _tenant_payload(row)


def create_tenant(*, company_name, plan, max_users, data_region, allowed_ip_cidrs="", session_timeout_minutes=30, saml_entity_id="", saml_sso_url="", saml_x509_cert="", saml_metadata_url="", actor="", ip=""):
    clean_company_name = str(company_name or "").strip()
    clean_plan = str(plan or "").strip().lower()
    clean_region = str(data_region or "").strip()
    clean_rules = parse_ip_rules(allowed_ip_cidrs)
    try:
        clean_max_users = max(int(max_users or 0), 1)
        clean_timeout = max(int(session_timeout_minutes or 0), 5)
    except ValueError as exc:
        raise ValueError("Numeric tenant settings are invalid.") from exc
    if not clean_company_name:
        raise ValueError("Company name is required.")
    if clean_plan not in PLAN_CHOICES:
        raise ValueError("Plan must be starter, pro, or enterprise.")
    if not clean_region:
        raise ValueError("Data region is required.")

    db = get_db()
    tenant_id = normalize_tenant_id(clean_company_name)
    suffix = 2
    while db.execute("SELECT 1 FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone():
        tenant_id = f"{normalize_tenant_id(clean_company_name)}-{suffix}"
        suffix += 1

    db.execute(
        """
        INSERT INTO tenants (
            tenant_id, company_name, plan, max_users, data_region,
            allowed_ip_cidrs, session_timeout_minutes, saml_entity_id,
            saml_sso_url, saml_x509_cert, saml_metadata_url, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        """,
        (
            tenant_id,
            clean_company_name,
            clean_plan,
            clean_max_users,
            clean_region,
            json.dumps(clean_rules),
            clean_timeout,
            str(saml_entity_id or "").strip(),
            str(saml_sso_url or "").strip(),
            str(saml_x509_cert or "").strip(),
            str(saml_metadata_url or "").strip(),
        ),
    )
    db.commit()
    note_audit(tenant_id, actor, "CREATE_TENANT", "tenants", tenant_id, {"company_name": clean_company_name}, ip=ip)
    return get_tenant_by_id(tenant_id)


def update_tenant_status(tenant_id, status, *, actor="", ip=""):
    clean_tenant_id = normalize_tenant_id(tenant_id)
    clean_status = str(status or "").strip().lower()
    if clean_status not in TENANT_STATUS_CHOICES:
        raise ValueError("Tenant status is invalid.")
    db = get_db()
    row = db.execute("SELECT * FROM tenants WHERE tenant_id = ?", (clean_tenant_id,)).fetchone()
    if not row:
        raise ValueError("Tenant not found.")
    if clean_tenant_id == DEFAULT_TENANT_ID and clean_status != "active":
        raise ValueError("The default tenant cannot be disabled.")
    db.execute(
        "UPDATE tenants SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE tenant_id = ?",
        (clean_status, clean_tenant_id),
    )
    db.commit()
    note_audit(clean_tenant_id, actor, "UPDATE_TENANT_STATUS", "tenants", clean_tenant_id, {"status": clean_status}, ip=ip)
    return get_tenant_by_id(clean_tenant_id)


def get_user_by_email(email, tenant_id=DEFAULT_TENANT_ID):
    return get_db().execute(
        """
        SELECT id, tenant_id, full_name, email, password_hash, role, totp_secret,
               totp_enabled, failed_login_attempts, locked_until, password_change_required,
               created_at, last_login_at, password_updated_at
        FROM users
        WHERE tenant_id = ? AND email = ?
        """,
        (normalize_tenant_id(tenant_id), email.lower()),
    ).fetchone()


def get_user_by_id(user_id):
    return get_db().execute(
        """
        SELECT id, tenant_id, full_name, email, password_hash, role, totp_secret,
               totp_enabled, failed_login_attempts, locked_until, password_change_required,
               created_at, last_login_at, password_updated_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()


def list_users(tenant_id=DEFAULT_TENANT_ID):
    return get_db().execute(
        """
        SELECT id, tenant_id, full_name, email, role, totp_enabled, failed_login_attempts,
               locked_until, password_change_required, created_at, last_login_at
        FROM users
        WHERE tenant_id = ?
        ORDER BY CASE role
            WHEN 'admin' THEN 1
            WHEN 'dispatcher' THEN 2
            ELSE 3
        END, email
        """,
        (normalize_tenant_id(tenant_id),),
    ).fetchall()


def authenticate_user(email, password, tenant_id=DEFAULT_TENANT_ID):
    result = attempt_password_login(email, password, tenant_id)
    return result["user"]


def attempt_password_login(email, password, tenant_id=DEFAULT_TENANT_ID, ip=""):
    clean_tenant_id = normalize_tenant_id(tenant_id)
    tenant = get_tenant_by_id(clean_tenant_id)
    if not tenant or tenant["status"] != "active":
        return {"user": None, "tenant": tenant, "error": "tenant_inactive"}

    user = get_user_by_email(email, clean_tenant_id)
    if not user:
        note_audit(clean_tenant_id, email, "FAILED_LOGIN", "users", "", {"reason": "missing_user"}, ip=ip)
        return {"user": None, "tenant": tenant, "error": "invalid_credentials"}

    if is_locked_until(user["locked_until"]):
        note_audit(clean_tenant_id, user["id"], "LOGIN_LOCKED", "users", user["id"], {"locked_until": user["locked_until"]}, ip=ip)
        return {"user": user, "tenant": tenant, "error": "locked"}

    if not check_password_hash(user["password_hash"], password):
        outcome = record_failed_login(user["id"], ip=ip)
        return {"user": None, "tenant": tenant, "error": "locked" if outcome["locked_until"] else "invalid_credentials"}

    reset_failed_logins(user["id"])
    return {"user": get_user_by_id(user["id"]), "tenant": tenant, "error": None}


def record_failed_login(user_id, ip=""):
    db = get_db()
    user = get_user_by_id(user_id)
    attempts = int(user["failed_login_attempts"] or 0) + 1
    locked_until = next_lockout_timestamp() if attempts >= LOCKOUT_THRESHOLD else ""
    db.execute(
        """
        UPDATE users
        SET failed_login_attempts = ?, locked_until = ?
        WHERE id = ?
        """,
        (attempts, locked_until, user_id),
    )
    db.commit()
    note_audit(
        user["tenant_id"],
        user_id,
        "FAILED_LOGIN",
        "users",
        user_id,
        {"failed_login_attempts": attempts, "locked_until": locked_until},
        ip=ip,
    )
    return {"failed_login_attempts": attempts, "locked_until": locked_until}


def reset_failed_logins(user_id):
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET failed_login_attempts = 0, locked_until = ''
        WHERE id = ?
        """,
        (user_id,),
    )
    db.commit()


def enable_totp(user_id, secret, *, ip=""):
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET totp_secret = ?, totp_enabled = 1
        WHERE id = ?
        """,
        (secret, user_id),
    )
    db.commit()
    user = get_user_by_id(user_id)
    note_audit(user["tenant_id"], user_id, "ENABLE_TOTP", "users", user_id, {"totp_enabled": True}, ip=ip)


def reset_totp(user_id, *, actor="", ip=""):
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET totp_secret = '', totp_enabled = 0
        WHERE id = ?
        """,
        (user_id,),
    )
    db.commit()
    user = get_user_by_id(user_id)
    note_audit(user["tenant_id"], actor or user_id, "RESET_TOTP", "users", user_id, {"totp_enabled": False}, ip=ip)


def record_login(user_id, ip=""):
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET last_login_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (user_id,),
    )
    db.commit()
    user = get_user_by_id(user_id)
    note_audit(user["tenant_id"], user_id, "LOGIN_SUCCESS", "users", user_id, {"last_login_at": user["last_login_at"]}, ip=ip)


def update_role(user_id, role, *, actor="", ip=""):
    if role not in ROLE_CHOICES:
        raise ValueError(f"Unsupported role: {role}")
    db = get_db()
    db.execute(
        "UPDATE users SET role = ? WHERE id = ?",
        (role, user_id),
    )
    db.commit()
    user = get_user_by_id(user_id)
    note_audit(user["tenant_id"], actor or user_id, "UPDATE_ROLE", "users", user_id, {"role": role}, ip=ip)


def change_password(user_id, new_password, *, ip=""):
    policy_error = validate_password_complexity(new_password)
    if policy_error:
        raise ValueError(policy_error)
    db = get_db()
    db.execute(
        """
        UPDATE users
        SET password_hash = ?, password_change_required = 0,
            password_updated_at = CURRENT_TIMESTAMP,
            failed_login_attempts = 0,
            locked_until = ''
        WHERE id = ?
        """,
        (generate_password_hash(new_password), user_id),
    )
    db.commit()
    user = get_user_by_id(user_id)
    note_audit(user["tenant_id"], user_id, "CHANGE_PASSWORD", "users", user_id, {"password_change_required": False}, ip=ip)
