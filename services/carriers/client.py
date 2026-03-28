"""
carriers/client.py — Client for other services to call the Carrier service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("carriers")

def get_schedules(origin, destination):
    return _client.get(f"/api/internal/carriers/schedules?origin={origin}&dest={destination}")

def get_reliability(carrier_name):
    return _client.get(f"/api/internal/carriers/reliability?carrier={carrier_name}")
