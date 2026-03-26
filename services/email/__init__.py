"""
Email Service — Outreach, intro mailer, reply parsing, bounce monitoring.
"""
from flask import Blueprint

email_service = Blueprint('email_service', __name__)

from . import routes  # noqa: E402,F401
