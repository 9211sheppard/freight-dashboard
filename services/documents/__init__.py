"""
Documents & OCR Service — Document processing, PDF generation, OCR, EDI.
"""
from flask import Blueprint

document_service = Blueprint('document_service', __name__)

from . import routes  # noqa: E402,F401
