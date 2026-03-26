"""
rates/models.py — Database initialization for rate-related tables.
Tables: rates, rate_cycles, rate_outreach, rate_gaps, rate_flags,
        rate_benchmarks, rate_history, nudge_log, agent_scores
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from database import init_rates_db

def init_rate_service_db():
    """Initialize all rate-related database tables."""
    init_rates_db()
