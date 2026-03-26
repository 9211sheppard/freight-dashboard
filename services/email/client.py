"""
email/client.py — Client for other services to call the Email service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("email")

def send_intro(contact_id, tenant_id=None):
    return _client.post("/api/internal/email/intro", {"contact_id": contact_id, "tenant_id": tenant_id})

def check_bounce_status(email_address):
    return _client.get(f"/api/internal/email/bounce-check?email={email_address}")
