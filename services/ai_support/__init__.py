"""
AI & Support Service — Helpbot, support tickets, AI diagnostics, translation.
"""
from flask import Blueprint

ai_support_service = Blueprint('ai_support_service', __name__)

from . import routes  # noqa: E402,F401
