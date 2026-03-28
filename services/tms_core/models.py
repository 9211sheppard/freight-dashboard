"""
tms_core/models.py — Database initialization for TMS tables.
TMS uses its own separate SQLite database (tms.db).
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

def init_tms_core_db():
    """Initialize TMS database."""
    try:
        from tms.tms_db import init_tms_db
        init_tms_db()
    except ImportError:
        pass
