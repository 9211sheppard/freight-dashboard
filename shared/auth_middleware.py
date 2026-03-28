"""
shared/auth_middleware.py — Common authentication middleware for all services.
Each service uses this to validate that requests come from authenticated users
or from other trusted internal services.
"""
from functools import wraps
from flask import session, redirect, url_for, jsonify, request


def login_required(f):
    """Require a logged-in user session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required."}), 401
            return redirect(url_for("auth_service.login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Require an admin user session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Authentication required."}), 401
            return redirect(url_for("auth_service.login"))
        if session.get("user_role") != "admin":
            return jsonify({"ok": False, "error": "Admin access required."}), 403
        return f(*args, **kwargs)
    return decorated


# Internal service-to-service auth header
_INTERNAL_SERVICE_HEADER = "X-Internal-Service-Key"


def internal_service_required(service_key):
    """Decorator factory for internal service-to-service authentication."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            provided_key = request.headers.get(_INTERNAL_SERVICE_HEADER, "")
            if provided_key != service_key:
                return jsonify({"ok": False, "error": "Unauthorized internal request."}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
