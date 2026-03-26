"""
documents/service.py — Re-exports document processing business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from tms.tms_docs import (
        generate_bol_pdf, generate_commercial_invoice_pdf,
        generate_packing_list_pdf, generate_pod_pdf,
    )
except (ImportError, AttributeError):
    generate_bol_pdf = None
    generate_commercial_invoice_pdf = None
    generate_packing_list_pdf = None
    generate_pod_pdf = None

try:
    from tms.tms_intake import extract_intake_payload
except ImportError:
    extract_intake_payload = None

try:
    from tms.tms_ocr import extract_document_payload
except ImportError:
    extract_document_payload = None

try:
    from tms.edi import X12_TRANSACTION_TYPES, EDIFACT_MESSAGE_TYPES
except ImportError:
    X12_TRANSACTION_TYPES = set()
    EDIFACT_MESSAGE_TYPES = set()
