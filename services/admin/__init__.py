"""
Admin & Monitoring Service — WAF, health checks, rate limiting, tenant management.
"""
from flask import Blueprint

admin_service = Blueprint('admin_service', __name__)

from . import routes  # noqa: E402,F401
