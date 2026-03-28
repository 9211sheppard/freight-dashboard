"""
email/models.py — Database initialization for email-related tables.
Tables: intro_outreach, email_send_analytics, bounced_emails
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import init_email_outreach_db

def init_email_db():
    """Initialize all email-related database tables."""
    init_email_outreach_db()
