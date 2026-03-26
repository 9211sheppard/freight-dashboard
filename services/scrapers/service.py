"""
scrapers/service.py — Re-exports scraper and data sync business logic.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from import_csv import import_all_csvs, import_csv

try:
    from scrape_utils import safe_get, extract_emails, RateLimiter
except ImportError:
    safe_get = None
    extract_emails = None
    RateLimiter = None

try:
    from sync_schedules import sync_all_schedules
except ImportError:
    sync_all_schedules = None

try:
    from schedule_watcher import start_schedule_watcher
except ImportError:
    start_schedule_watcher = None
