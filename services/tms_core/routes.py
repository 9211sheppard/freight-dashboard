"""
tms_core/routes.py — HTTP routes for the TMS service.
TMS routes are served via its own blueprints (tms, portal, public)
which are registered directly on the Flask app.
"""
from . import tms_core_service
# TMS routes are served by tms_blueprint, portal_blueprint, public_blueprint
# registered in app.py. No additional routes needed here.
