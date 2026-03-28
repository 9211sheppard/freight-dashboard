"""
contacts/service.py — Re-exports contact business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from contact_engine import (
    get_lanes_for_country, get_psych_elements, get_country_motto,
    record_send_analytics,
)
try:
    from verify_contacts import verify_email_address
except ImportError:
    verify_email_address = None
try:
    from fast_verify import fast_verify_contacts
except ImportError:
    fast_verify_contacts = None
try:
    from mx_check import check_mx
except ImportError:
    check_mx = None
try:
    from email_inspectors import init_inspection_log_db
except ImportError:
    init_inspection_log_db = None
