"""
wsgi.py — Production entry point for gunicorn.
Usage:  gunicorn wsgi:app --workers 4 --bind 0.0.0.0:$PORT
"""
import os

# Signal production mode
os.environ.setdefault("PRODUCTION", "1")

from app import app, init_all_dbs, start_background_workers

# Initialize databases on import (runs once per worker)
init_all_dbs()

# Start background workers only in the first worker (avoid duplicates)
# gunicorn preload + --workers uses fork, so threads start per-process.
# For single-worker or Railway (typically 1-2 workers), this is fine.
_workers_started = False

@app.before_request
def _ensure_workers():
    global _workers_started
    if not _workers_started:
        _workers_started = True
        start_background_workers()
