"""
documents/client.py — Client for other services to call the Document service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("documents")

def extract_from_upload(file_data):
    return _client.post("/api/internal/documents/extract", {"file": file_data})

def generate_bol(shipment_data):
    return _client.post("/api/internal/documents/bol", shipment_data)
