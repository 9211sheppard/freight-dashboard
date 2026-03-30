"""SOC 2 Technical Controls — Security, Availability, Processing Integrity, Confidentiality, Privacy."""
import sqlite3, os, hashlib, secrets, json
from datetime import datetime, timedelta
from functools import wraps
from flask import request, session, g

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_soc2_tables():
    conn = get_db()
    try:
        conn.executescript("""
        -- CC6: SOC 2 Audit log — every significant action
        -- Named soc2_audit_log to avoid collision with existing audit_log table
        CREATE TABLE IF NOT EXISTS soc2_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT DEFAULT '',
            user_email TEXT DEFAULT '',
            ip_address TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            action TEXT NOT NULL,          -- CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT, etc.
            resource_type TEXT DEFAULT '', -- shipment, driver, invoice, user, etc.
            resource_id TEXT DEFAULT '',
            old_value TEXT DEFAULT '',     -- JSON of previous state
            new_value TEXT DEFAULT '',     -- JSON of new state
            result TEXT DEFAULT 'success', -- success, failure, denied
            session_id TEXT DEFAULT '',
            request_id TEXT DEFAULT ''
        );

        -- CC6: Failed login attempts + lockout tracking (extends existing table)
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip_address TEXT NOT NULL,
            username TEXT DEFAULT '',
            attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 0
        );

        -- A1: System health / availability monitoring (extends existing table)
        CREATE TABLE IF NOT EXISTS health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            component TEXT NOT NULL,  -- db, flask, storage, etc.
            status TEXT DEFAULT 'ok', -- ok, degraded, down
            response_ms REAL DEFAULT 0,
            details TEXT DEFAULT ''
        );

        -- PI1: Data processing integrity — track all data imports/exports
        CREATE TABLE IF NOT EXISTS data_operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            operation_type TEXT NOT NULL, -- import, export, bulk_update, delete
            performed_by TEXT DEFAULT '',
            record_count INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            destination TEXT DEFAULT '',
            checksum TEXT DEFAULT '',
            status TEXT DEFAULT 'completed',
            error TEXT DEFAULT ''
        );

        -- C1: Data classification (extends existing table)
        CREATE TABLE IF NOT EXISTS data_classification (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            classification TEXT DEFAULT 'internal', -- public, internal, confidential, restricted
            pii INTEGER DEFAULT 0,
            encrypted INTEGER DEFAULT 0,
            retention_days INTEGER DEFAULT 2555  -- 7 years default
        );

        -- P1: Privacy — data subject requests (GDPR/CCPA) — uses existing table
        CREATE TABLE IF NOT EXISTS privacy_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_type TEXT NOT NULL,   -- access, deletion, correction, portability
            requester_name TEXT DEFAULT '',
            requester_email TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',  -- Pending, In Progress, Completed, Denied
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            due_at TIMESTAMP DEFAULT NULL,  -- 30 days from submission
            completed_at TIMESTAMP DEFAULT NULL,
            notes TEXT DEFAULT '',
            response_notes TEXT DEFAULT ''
        );

        -- Security incidents (uses existing table)
        CREATE TABLE IF NOT EXISTS security_incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            incident_type TEXT NOT NULL,  -- brute_force, unauthorized_access, data_leak, etc.
            severity TEXT DEFAULT 'low',  -- low, medium, high, critical
            source_ip TEXT DEFAULT '',
            affected_resource TEXT DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'Open',   -- Open, Investigating, Resolved, Closed
            resolved_at TIMESTAMP DEFAULT NULL,
            resolution_notes TEXT DEFAULT ''
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_soc2_audit_log_time ON soc2_audit_log(event_time DESC);
        CREATE INDEX IF NOT EXISTS idx_soc2_audit_log_user ON soc2_audit_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_soc2_audit_log_resource ON soc2_audit_log(resource_type, resource_id);
        CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address, attempt_time);
        """)
        conn.commit()
        _seed_data_classification(conn)
    finally:
        conn.close()

def _seed_data_classification(conn):
    """Seed known PII/sensitive fields."""
    if conn.execute("SELECT COUNT(*) FROM data_classification").fetchone()[0] > 0:
        return
    classifications = [
        ('contacts', 'email', 'confidential', 1, 0, 2555),
        ('contacts', 'phone', 'confidential', 1, 0, 2555),
        ('contacts', 'first_name', 'internal', 1, 0, 2555),
        ('contacts', 'last_name', 'internal', 1, 0, 2555),
        ('drivers', 'name', 'internal', 1, 0, 2555),
        ('drivers', 'phone', 'confidential', 1, 0, 2555),
        ('drivers', 'email', 'confidential', 1, 0, 2555),
        ('drivers', 'license_number', 'restricted', 1, 1, 2555),
        ('auto_invoices', 'customer_email', 'confidential', 1, 0, 2555),
        ('auto_invoices', 'total', 'confidential', 0, 0, 2555),
        ('shipments', 'shipment_ref', 'internal', 0, 0, 2555),
        ('pod_submissions', 'signature_data', 'restricted', 1, 1, 2555),
        ('login_attempts', 'ip_address', 'restricted', 1, 0, 90),
        ('active_sessions', 'session_token', 'restricted', 0, 1, 1),
    ]
    conn.executemany(
        "INSERT INTO data_classification (table_name, column_name, classification, pii, encrypted, retention_days) VALUES (?,?,?,?,?,?)",
        classifications
    )
    conn.commit()

# Initialize on import
init_soc2_tables()

# ── Audit Logging ─────────────────────────────────────────────────

def audit(action: str, resource_type: str = '', resource_id: str = '',
          old_value: dict = None, new_value: dict = None, result: str = 'success'):
    """Log an auditable event. Call from any route that modifies data."""
    try:
        conn = get_db()
        try:
            # Get request context if available
            try:
                ip = request.remote_addr or ''
                ua = request.user_agent.string[:200] if request.user_agent else ''
                req_id = request.headers.get('X-Request-ID', secrets.token_hex(8))
            except RuntimeError:
                ip = ua = req_id = ''

            user_id = session.get('user_id', '') if hasattr(session, 'get') else ''
            user_email = session.get('user_email', session.get('username', '')) if hasattr(session, 'get') else ''
            sess_id = session.get('session_id', '') if hasattr(session, 'get') else ''

            conn.execute(
                """INSERT INTO soc2_audit_log
                   (user_id, user_email, ip_address, user_agent, action, resource_type,
                    resource_id, old_value, new_value, result, session_id, request_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(user_id), str(user_email), ip, ua, action, resource_type,
                 str(resource_id),
                 json.dumps(old_value) if old_value else '',
                 json.dumps(new_value) if new_value else '',
                 result, sess_id, req_id)
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # Never let audit logging break the application

# ── Brute Force Protection ────────────────────────────────────────

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

def record_login_attempt(ip: str, username: str, success: bool):
    conn = get_db()
    try:
        conn.execute("INSERT INTO login_attempts (ip_address, username, success) VALUES (?,?,?)",
                     (ip, username, 1 if success else 0))
        conn.commit()
        if success:
            return
        # Check if incident threshold reached
        cutoff = (datetime.now() - timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address=? AND success=0 AND attempt_time > ?",
            (ip, cutoff)
        ).fetchone()[0]
        if count >= MAX_ATTEMPTS:
            _flag_security_incident('brute_force', ip, f"{count} failed login attempts in {LOCKOUT_MINUTES} minutes")
    finally:
        conn.close()

def is_ip_locked(ip: str) -> bool:
    conn = get_db()
    try:
        cutoff = (datetime.now() - timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE ip_address=? AND success=0 AND attempt_time > ?",
            (ip, cutoff)
        ).fetchone()[0]
        return count >= MAX_ATTEMPTS
    finally:
        conn.close()

# ── Session Management ────────────────────────────────────────────
# Note: active_sessions table in this DB uses (session_token, last_seen) schema
# These helpers work with the existing schema where applicable.

SESSION_TIMEOUT_HOURS = 8

def create_session(user_id: str, user_email: str, ip: str) -> str:
    """Create a tracked session token. Returns token string."""
    session_token = secrets.token_urlsafe(32)
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO active_sessions (user_id, session_token, ip_address)
               VALUES (?,?,?)""",
            (user_id, session_token, ip)
        )
        conn.commit()
    finally:
        conn.close()
    return session_token

def validate_session(session_token: str) -> bool:
    """Validate a session token is still active."""
    if not session_token:
        return False
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM active_sessions WHERE session_token=?",
            (session_token,)
        ).fetchone()
        if not row:
            return False
        conn.execute("UPDATE active_sessions SET last_seen=CURRENT_TIMESTAMP WHERE session_token=?",
                     (session_token,))
        conn.commit()
        return True
    finally:
        conn.close()

def revoke_session(session_token: str):
    """Revoke (delete) a session."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM active_sessions WHERE session_token=?", (session_token,))
        conn.commit()
    finally:
        conn.close()

# ── Health Monitoring ─────────────────────────────────────────────

def run_health_check() -> dict:
    import time
    results = {}

    # DB health
    start = time.time()
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        results['database'] = {'status': 'ok', 'ms': round((time.time()-start)*1000, 1)}
    except Exception as e:
        results['database'] = {'status': 'down', 'error': str(e)}

    # Disk space
    try:
        stat = os.statvfs('/') if hasattr(os, 'statvfs') else None
        if stat:
            free_gb = stat.f_bavail * stat.f_frsize / (1024**3)
            results['disk'] = {'status': 'ok' if free_gb > 1 else 'low', 'free_gb': round(free_gb, 1)}
        else:
            import shutil
            usage = shutil.disk_usage('C:/')
            free_gb = usage.free / (1024**3)
            results['disk'] = {'status': 'ok' if free_gb > 1 else 'low', 'free_gb': round(free_gb, 1)}
    except Exception:
        results['disk'] = {'status': 'unknown'}

    # DB file size
    try:
        db_size = os.path.getsize(DB_PATH) / (1024*1024)
        results['db_size_mb'] = round(db_size, 1)
    except Exception:
        pass

    # Log to DB
    conn = get_db()
    try:
        for component, info in results.items():
            if isinstance(info, dict):
                conn.execute(
                    "INSERT INTO health_checks (component, status, response_ms, details) VALUES (?,?,?,?)",
                    (component, info.get('status', 'ok'), info.get('ms', 0), json.dumps(info))
                )
        conn.commit()
    finally:
        conn.close()

    return results

# ── Security Incidents ─────────────────────────────────────────────

def _flag_security_incident(incident_type: str, source_ip: str, description: str, severity: str = 'medium'):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO security_incidents (incident_type, severity, source_ip, description) VALUES (?,?,?,?)",
            (incident_type, severity, source_ip, description)
        )
        conn.commit()
    finally:
        conn.close()

# ── Audit Log Queries ─────────────────────────────────────────────

def get_audit_log(limit=100, user=None, resource_type=None, action=None):
    conn = get_db()
    try:
        q = "SELECT * FROM soc2_audit_log WHERE 1=1"
        params = []
        if user:
            q += " AND (user_id=? OR user_email=?)"; params += [user, user]
        if resource_type:
            q += " AND resource_type=?"; params.append(resource_type)
        if action:
            q += " AND action=?"; params.append(action)
        q += " ORDER BY event_time DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_security_incidents(status=None):
    conn = get_db()
    try:
        q = "SELECT * FROM security_incidents"
        params = []
        if status:
            q += " WHERE status=?"
            params.append(status)
        q += " ORDER BY detected_at DESC LIMIT 50"
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()

def get_privacy_requests():
    conn = get_db()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM privacy_requests ORDER BY submitted_at DESC").fetchall()]
    finally:
        conn.close()

def submit_privacy_request(request_type, name, email, notes=''):
    conn = get_db()
    try:
        due = (datetime.now() + timedelta(days=30)).isoformat()
        conn.execute(
            "INSERT INTO privacy_requests (request_type, requester_name, requester_email, notes, due_at) VALUES (?,?,?,?,?)",
            (request_type, name, email, notes, due)
        )
        conn.commit()
    finally:
        conn.close()

def get_soc2_summary():
    conn = get_db()
    try:
        audit_count = conn.execute("SELECT COUNT(*) FROM soc2_audit_log WHERE event_time > datetime('now','-7 days')").fetchone()[0]
        open_incidents = conn.execute("SELECT COUNT(*) FROM security_incidents WHERE status='Open'").fetchone()[0]
        failed_logins = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE success=0 AND attempt_time > datetime('now','-24 hours')").fetchone()[0]
        active_sessions = conn.execute("SELECT COUNT(*) FROM active_sessions").fetchone()[0]
        privacy_pending = conn.execute("SELECT COUNT(*) FROM privacy_requests WHERE status='Pending'").fetchone()[0]
        pii_fields = conn.execute("SELECT COUNT(*) FROM data_classification WHERE pii=1").fetchone()[0]
        return {
            "audit_events_7d": audit_count,
            "open_incidents": open_incidents,
            "failed_logins_24h": failed_logins,
            "active_sessions": active_sessions,
            "privacy_requests_pending": privacy_pending,
            "pii_fields_tracked": pii_fields,
        }
    finally:
        conn.close()
