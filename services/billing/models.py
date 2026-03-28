"""
billing/models.py — Database initialization for billing-related tables.
Tables: subscriptions (in tenants), quotes
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from quotes import init_quotes_db

def init_billing_db():
    """Initialize all billing-related database tables."""
    init_quotes_db()
