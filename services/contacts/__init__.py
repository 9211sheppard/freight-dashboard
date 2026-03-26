"""
Contact Service — Contact management, verification, enrichment, intelligence.
"""
from flask import Blueprint

contact_service = Blueprint('contact_service', __name__)

from . import routes  # noqa: E402,F401
