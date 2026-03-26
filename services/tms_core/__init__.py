"""
TMS Core Service — Transportation Management System.
Shipments, loads, dispatch, tracking, dock management, fleet.
Already semi-independent with its own database (tms.db).
"""
from flask import Blueprint

tms_core_service = Blueprint('tms_core_service', __name__)

# The TMS already has its own blueprints (tms, portal, public).
# This service wrapper provides the microservice interface.
from . import routes  # noqa: E402,F401
