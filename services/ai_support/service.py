"""
ai_support/service.py — Re-exports AI and support business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from helpbot import ask as helpbot_ask, init_helpbot_db, get_helpbot_stats

try:
    from support_ai import diagnose_ticket, process_ticket, verify_and_close_ticket
except ImportError:
    diagnose_ticket = None
    process_ticket = None
    verify_and_close_ticket = None

try:
    from translation_service import (
        detect_language, translate_to_english, translate_from_english,
        translate_text, get_language_for_country,
    )
except ImportError:
    detect_language = None
    translate_to_english = None
    translate_from_english = None
    translate_text = None
    get_language_for_country = None
