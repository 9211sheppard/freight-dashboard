"""
compliance/client.py — Client for other services to call the Compliance service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("compliance")

def log_audit_event(tenant_id, user_id, action, resource="", details=""):
    return _client.post("/api/internal/compliance/audit", {
        "tenant_id": tenant_id, "user_id": user_id,
        "action": action, "resource": resource, "details": details
    })

def get_audit_trail(tenant_id, page=1, per_page=50):
    return _client.get(f"/api/internal/compliance/audit?tenant_id={tenant_id}&page={page}&per_page={per_page}")
