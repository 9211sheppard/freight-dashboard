"""
email/service.py — Re-exports email business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from mailer import send_email, SIGNATURE, signature_for
from intro_mailer import (
    send_intro_email, get_intro_stats, get_intro_outreach_list,
)
try:
    from reply_parser import poll_inbox
except ImportError:
    poll_inbox = None
try:
    from bounce_monitor import check_bounces, is_bounced, get_all_bounces
except ImportError:
    check_bounces = None
    is_bounced = None
    get_all_bounces = None
