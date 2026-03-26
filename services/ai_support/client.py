"""
ai_support/client.py — Client for other services to call the AI Support service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("ai_support")

def ask_helpbot(question, tenant_id=None):
    return _client.post("/api/internal/ai/helpbot", {"question": question, "tenant_id": tenant_id})

def submit_ticket(data):
    return _client.post("/api/internal/ai/ticket", data)

def translate(text, target_lang):
    return _client.post("/api/internal/ai/translate", {"text": text, "target_lang": target_lang})
