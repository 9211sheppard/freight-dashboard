"""
auth/client.py — Client for other services to call the Auth service.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from shared.service_client import ServiceClient

_client = ServiceClient("auth")

def validate_token(session_token):
    """Check if a session token is valid."""
    return _client.post("/api/internal/auth/validate", {"token": session_token})

def get_user(user_id):
    """Get user details by ID."""
    return _client.get(f"/api/internal/auth/user/{user_id}")
