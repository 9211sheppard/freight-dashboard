"""
Auth Service — User authentication, MFA, OAuth, permissions, API keys.
Isolated service for all identity and access management.
"""
from flask import Blueprint

auth_service = Blueprint('auth_service', __name__)

from . import routes  # noqa: E402,F401
