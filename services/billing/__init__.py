"""
Billing Service — Subscriptions, invoices, quotes, SaaS metrics.
"""
from flask import Blueprint

billing_service = Blueprint('billing_service', __name__)

from . import routes  # noqa: E402,F401
