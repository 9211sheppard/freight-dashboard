"""
shared/config.py — Re-exports from the root config module.
All services import config from here instead of the root.
"""
import sys
import os

# Add project root to path so we can import the original config
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import *  # noqa: F401,F403
