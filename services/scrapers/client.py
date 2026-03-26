"""
scrapers/client.py — Client for other services to call the Scraper service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("scrapers")

def trigger_import(source=None):
    return _client.post("/api/internal/scrapers/import", {"source": source})

def trigger_schedule_sync():
    return _client.post("/api/internal/scrapers/sync-schedules", {})
