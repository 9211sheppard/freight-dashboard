"""
Rate Engine Service — Rate matching, benchmarking, AI-driven nudging, rate cycles.
"""
from flask import Blueprint

rate_service = Blueprint('rate_service', __name__)

from . import routes  # noqa: E402,F401
