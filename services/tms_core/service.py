"""
tms_core/service.py — Re-exports TMS business logic.
The TMS module already runs semi-independently with its own DB.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

# TMS blueprints
try:
    from tms import tms as tms_blueprint, portal as portal_blueprint, public as public_blueprint
except ImportError:
    tms_blueprint = None
    portal_blueprint = None
    public_blueprint = None

# TMS database
try:
    from tms.tms_db import init_tms_db, get_tracking_page_context
except ImportError:
    init_tms_db = None
    get_tracking_page_context = None

# TMS tenanting
try:
    from tms.tenanting import tenant_context, get_current_tenant
except ImportError:
    tenant_context = None
    get_current_tenant = None
