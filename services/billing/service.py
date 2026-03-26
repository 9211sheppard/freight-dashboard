"""
billing/service.py — Re-exports billing business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from billing import *  # noqa: F401,F403

from quotes import (
    init_quotes_db, create_quote, get_quote, list_quotes,
    update_quote, delete_quote, render_quote_html, generate_pdf,
    quote_from_rate,
)

try:
    from admin_panel import get_saas_metrics
except ImportError:
    get_saas_metrics = None
