"""
tms_core/client.py — Client for other services to call the TMS service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("tms")

def get_shipment(ref):
    return _client.get(f"/api/internal/tms/shipment/{ref}")

def get_tracking(ref):
    return _client.get(f"/api/internal/tms/tracking/{ref}")
