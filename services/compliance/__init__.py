"""
Compliance & Audit Service — Audit logging, GDPR compliance, SOC2, export controls.
"""
from flask import Blueprint

compliance_service = Blueprint('compliance_service', __name__)

from . import routes  # noqa: E402,F401
