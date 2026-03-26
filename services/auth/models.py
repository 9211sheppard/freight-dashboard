"""
auth/models.py — Database initialization for auth-related tables.
Tables: users, password_resets, user_logins, active_sessions, trusted_devices,
        password_history, api_keys, user_permissions, permission_templates, ip_allowlist
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import init_users_db

def init_auth_db():
    """Initialize all auth-related database tables."""
    init_users_db()
