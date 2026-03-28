"""
audit.py  —  Security audit logging for all critical events
"""

import json
from datetime import datetime
from database import get_db


def log_event(tenant_id: int = None, user_id: int = None, action: str = "",
              resource: str = "", details: str = "", ip: str = "", user_agent: str = ""):
    """Log a security/audit event to the audit_log table."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_log (tenant_id, user_id, action, resource, details, ip_address, user_agent, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tenant_id, user_id, action, resource,
             details if isinstance(details, str) else json.dumps(details),
             ip or "", user_agent or "", datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        # Audit logging must never crash the app
        print(f"[audit] Failed to log event: {e}")


def get_audit_log(tenant_id: int, page: int = 1, per_page: int = 50,
                  action_filter: str = None, user_id_filter: int = None,
                  date_from: str = None, date_to: str = None) -> dict:
    """Query audit log with pagination and filters."""
    conn = get_db()
    try:
        conditions = ["tenant_id = ?"]
        params = [tenant_id]

        if action_filter:
            conditions.append("action = ?")
            params.append(action_filter)
        if user_id_filter:
            conditions.append("user_id = ?")
            params.append(user_id_filter)
        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to)

        where = " AND ".join(conditions)

        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_log WHERE {where}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT id, tenant_id, user_id, action, resource, details, ip_address, user_agent, created_at "
            f"FROM audit_log WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()

        return {
            "events": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }
    finally:
        conn.close()


def get_user_audit(user_id: int, tenant_id: int, limit: int = 100) -> list:
    """Get all audit events for a specific user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, action, resource, details, ip_address, created_at "
            "FROM audit_log WHERE user_id = ? AND tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, tenant_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
