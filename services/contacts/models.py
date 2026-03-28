"""
contacts/models.py — Database initialization for contact-related tables.
Tables: contacts, contact_profiles, contact_interactions, contact_timing_profile
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import init_db, init_contact_intelligence_db

def init_contacts_db():
    """Initialize all contact-related database tables."""
    init_db()
    init_contact_intelligence_db()
