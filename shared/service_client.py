"""
shared/service_client.py — Base HTTP client for inter-service communication.
Services use this to call other services' APIs.
"""
import os
import json
import urllib.request
import urllib.error

# Service registry — maps service name to its base URL.
# In monolith mode, services are co-located so we use localhost.
# In distributed mode, set env vars like AUTH_SERVICE_URL, CONTACT_SERVICE_URL, etc.
_DEFAULT_BASE = "http://localhost:5000"

SERVICE_URLS = {
    "auth":       os.environ.get("AUTH_SERVICE_URL", _DEFAULT_BASE),
    "contacts":   os.environ.get("CONTACT_SERVICE_URL", _DEFAULT_BASE),
    "email":      os.environ.get("EMAIL_SERVICE_URL", _DEFAULT_BASE),
    "rates":      os.environ.get("RATE_SERVICE_URL", _DEFAULT_BASE),
    "tms":        os.environ.get("TMS_SERVICE_URL", _DEFAULT_BASE),
    "carriers":   os.environ.get("CARRIER_SERVICE_URL", _DEFAULT_BASE),
    "documents":  os.environ.get("DOCUMENT_SERVICE_URL", _DEFAULT_BASE),
    "billing":    os.environ.get("BILLING_SERVICE_URL", _DEFAULT_BASE),
    "compliance": os.environ.get("COMPLIANCE_SERVICE_URL", _DEFAULT_BASE),
    "scrapers":   os.environ.get("SCRAPER_SERVICE_URL", _DEFAULT_BASE),
    "ai_support": os.environ.get("AI_SUPPORT_SERVICE_URL", _DEFAULT_BASE),
    "admin":      os.environ.get("ADMIN_SERVICE_URL", _DEFAULT_BASE),
}

# Internal service key for service-to-service auth
INTERNAL_KEY = os.environ.get("INTERNAL_SERVICE_KEY", "dev-internal-key")


class ServiceClient:
    """HTTP client for calling another microservice."""

    def __init__(self, service_name):
        self.base_url = SERVICE_URLS.get(service_name, _DEFAULT_BASE)
        self.service_name = service_name

    def _request(self, method, path, data=None, timeout=10):
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-Internal-Service-Key": INTERNAL_KEY,
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return {"ok": False, "error": f"{self.service_name} returned {e.code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get(self, path, timeout=10):
        return self._request("GET", path, timeout=timeout)

    def post(self, path, data=None, timeout=10):
        return self._request("POST", path, data=data, timeout=timeout)

    def put(self, path, data=None, timeout=10):
        return self._request("PUT", path, data=data, timeout=timeout)

    def delete(self, path, timeout=10):
        return self._request("DELETE", path, timeout=timeout)
