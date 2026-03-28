"""
Scrapers & Data Sync Service — Web scrapers, CSV import, schedule sync.
"""
from flask import Blueprint

scraper_service = Blueprint('scraper_service', __name__)

from . import routes  # noqa: E402,F401
