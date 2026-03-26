"""
carriers/service.py — Re-exports carrier and fleet business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from carrier_api import ORIGIN_PORTS, DEST_PORTS, has_any_api_keys_configured
try:
    from reliability import (
        init_reliability_db, enrich_schedules_with_reliability,
        get_carrier_leaderboard, get_lane_leaderboard, compute_reliability_scores,
    )
except ImportError:
    init_reliability_db = None
    enrich_schedules_with_reliability = None
    get_carrier_leaderboard = None
    get_lane_leaderboard = None
    compute_reliability_scores = None

try:
    from predictive_eta import init_predictive_db, enrich_schedules_with_predictions
except ImportError:
    init_predictive_db = None
    enrich_schedules_with_predictions = None

try:
    from record_arrivals import mark_arrived
except ImportError:
    mark_arrived = None

try:
    from schedule_sync_api import ensure_schedule_schema, start_background_sync
except ImportError:
    ensure_schedule_schema = None
    start_background_sync = None
