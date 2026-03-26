"""
carriers/models.py — Database initialization for carrier-related tables.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

def init_carrier_db():
    """Initialize carrier-related database tables."""
    try:
        from reliability import init_reliability_db
        init_reliability_db()
    except ImportError:
        pass
    try:
        from predictive_eta import init_predictive_db
        init_predictive_db()
    except ImportError:
        pass
    try:
        from schedule_sync_api import ensure_schedule_schema
        ensure_schedule_schema()
    except ImportError:
        pass
