"""
rates/service.py — Re-exports rate engine business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

import rate_engine
import rate_engine_v2

# Re-export key functions
from rate_engine_v2 import (
    to_locode, best_match, get_benchmarks, calculate_benchmarks,
    get_trend, get_flags, nudge_rate,
)
try:
    from rate_data_seeder import seed_demo_rates
except ImportError:
    seed_demo_rates = None
