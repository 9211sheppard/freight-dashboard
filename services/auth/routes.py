"""
auth/routes.py — HTTP routes for the Auth service.
These routes will be extracted from app.py in a future step.
For now, the blueprint is registered and routes are served from app.py.
"""
from . import auth_service
# Auth routes are currently served directly from app.py.
# They will be migrated here incrementally.
# The blueprint is registered so inter-service imports work.
