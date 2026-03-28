"""
compliance/service.py — Re-exports compliance and audit business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from audit import log_event, get_audit_log, get_user_audit
from compliance import *  # noqa: F401,F403

try:
    from tms.tms_compliance import (
        normalize_party_name, normalize_hs_code, parse_declared_value,
        default_customs_declaration, load_denied_party_blocklist,
        load_dual_use_rules,
    )
except ImportError:
    normalize_party_name = None
    normalize_hs_code = None
    parse_declared_value = None
    default_customs_declaration = None
    load_denied_party_blocklist = None
    load_dual_use_rules = None
