"""
admin/models.py — Database initialization for admin-related tables.
Tables: tenants, system_health_log, referrals, spin_results, admin_activity_log
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import init_tenants_db

def init_admin_db():
    """Initialize all admin-related database tables."""
    init_tenants_db()
