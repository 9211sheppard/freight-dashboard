"""
ai_support/models.py — Database initialization for AI support tables.
Tables: helpbot knowledge base, support_tickets
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from helpbot import init_helpbot_db

def init_ai_support_db():
    """Initialize AI support database tables."""
    init_helpbot_db()
