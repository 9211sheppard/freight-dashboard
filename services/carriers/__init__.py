"""
Carrier & Fleet Service — Carrier APIs, reliability scoring, ETA predictions, schedules.
"""
from flask import Blueprint

carrier_service = Blueprint('carrier_service', __name__)

from . import routes  # noqa: E402,F401
