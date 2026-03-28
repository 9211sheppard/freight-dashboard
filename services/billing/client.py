"""
billing/client.py — Client for other services to call the Billing service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("billing")

def get_subscription_status(tenant_id):
    return _client.get(f"/api/internal/billing/subscription/{tenant_id}")

def create_invoice(data):
    return _client.post("/api/internal/billing/invoice", data)
