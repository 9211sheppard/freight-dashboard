"""
gateway/ — API Gateway and service registry.
In monolith mode, all services run as blueprints under a single Flask app.
In distributed mode, this becomes a reverse proxy routing to independent services.
"""

# Service registry — import all service blueprints
from services.auth import auth_service
from services.contacts import contact_service
from services.email import email_service
from services.rates import rate_service
from services.tms_core import tms_core_service
from services.carriers import carrier_service
from services.documents import document_service
from services.billing import billing_service
from services.compliance import compliance_service
from services.scrapers import scraper_service
from services.ai_support import ai_support_service
from services.admin import admin_service

ALL_SERVICES = [
    auth_service,
    contact_service,
    email_service,
    rate_service,
    tms_core_service,
    carrier_service,
    document_service,
    billing_service,
    compliance_service,
    scraper_service,
    ai_support_service,
    admin_service,
]


def register_all_services(app):
    """Register all microservice blueprints on a Flask app (monolith mode)."""
    for service in ALL_SERVICES:
        try:
            app.register_blueprint(service)
        except Exception as e:
            print(f"[gateway] Failed to register {service.name}: {e}")
