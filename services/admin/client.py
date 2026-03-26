"""
admin/client.py — Client for other services to call the Admin service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("admin")

def get_tenant_info(tenant_id):
    return _client.get(f"/api/internal/admin/tenant/{tenant_id}")

def check_health():
    return _client.get("/api/internal/admin/health")

def check_rate_limit(key, limit_type="api"):
    return _client.post("/api/internal/admin/rate-limit", {"key": key, "type": limit_type})
