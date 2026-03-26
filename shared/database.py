"""
shared/database.py — Re-exports from the root database module.
All services import database utilities from here.
"""
import sys
import os

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from database import *  # noqa: F401,F403
from database import get_db, _get_existing_columns
