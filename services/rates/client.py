"""
rates/client.py — Client for other services to call the Rate service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("rates")

def get_best_rate(origin, destination, container_type="20ft"):
    return _client.post("/api/internal/rates/best-match", {
        "origin": origin, "destination": destination, "container_type": container_type
    })

def get_rate_trend(origin, destination):
    return _client.get(f"/api/internal/rates/trend?origin={origin}&destination={destination}")
