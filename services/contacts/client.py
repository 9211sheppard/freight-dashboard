"""
contacts/client.py — Client for other services to call the Contact service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("contacts")

def search_contacts(query, tenant_id=None):
    return _client.post("/api/internal/contacts/search", {"query": query, "tenant_id": tenant_id})

def get_contact(contact_id):
    return _client.get(f"/api/internal/contacts/{contact_id}")
