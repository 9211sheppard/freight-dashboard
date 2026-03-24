import os
import sys

# ─────────────────────────────────────────────
#  LOGIN PASSWORD  — change this to your own
#  On Azure, set env var DASHBOARD_PASSWORD
# ─────────────────────────────────────────────
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "admin123")  # MUST override via env var in production

# ─────────────────────────────────────────────
#  EMAIL — Microsoft Graph API (no SMTP needed)
#  App: Freight Dashboard Mailer
#  Permission: Mail.Send (application)
#  On Azure, set env vars: EMAIL_FROM, GRAPH_TENANT_ID,
#  GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
# ─────────────────────────────────────────────
EMAIL_FROM          = os.environ.get("EMAIL_FROM", "")
GRAPH_TENANT_ID     = os.environ.get("GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID     = os.environ.get("GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")

# Legacy SMTP (disabled — tenant has SMTP AUTH off)
EMAIL_HOST = ""
EMAIL_PORT = 587
EMAIL_USER = ""
EMAIL_PASS = ""

# ─────────────────────────────────────────────
#  SECRET KEY  — used to sign session cookies
#  On Azure, set env var SECRET_KEY
# ─────────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")

# ─────────────────────────────────────────────
#  PATHS  (work on any machine automatically)
# ─────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    # Running as a PyInstaller .exe — bundled code is in sys._MEIPASS,
    # but the database/data folder lives next to the .exe file itself
    # so it persists between runs and can be updated by the user.
    BASE_DIR = sys._MEIPASS
    DATA_DIR = os.path.join(os.path.dirname(sys.executable), "data")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")

DB_PATH  = os.path.join(DATA_DIR, "contacts.db")

# ── Database URL (PostgreSQL for production, SQLite for local dev) ──────────
# Set DATABASE_URL env var to use PostgreSQL, e.g.:
#   DATABASE_URL=postgresql://user:pass@host:5432/dbname
# If not set, falls back to SQLite at DB_PATH above.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ── CSV source paths — all relative to DATA_DIR ────────────────────────────
# Users import data via the dashboard's Import CSV button.
# For local dev, place CSVs in the data/ folder.
_WFA_CANDIDATES = [
    os.path.join(DATA_DIR, "upload_wfa.csv"),
]
_WWPC_CANDIDATES = [
    os.path.join(DATA_DIR, "upload_wwpc.csv"),
]
_FIATA_CANDIDATES = [
    os.path.join(DATA_DIR, "upload_fiata.csv"),
]
_FREIGHTNET_CANDIDATES = [
    os.path.join(DATA_DIR, "upload_freightnet.csv"),
]
_AHK_JAPAN_CANDIDATES = [
    os.path.join(DATA_DIR, "upload_ahk-japan.csv"),
]

def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None

CSV_PATH            = _first_existing(_WFA_CANDIDATES)
WWPC_CSV_PATH       = _first_existing(_WWPC_CANDIDATES)
FIATA_CSV_PATH      = _first_existing(_FIATA_CANDIDATES)
FREIGHTNET_CSV_PATH = _first_existing(_FREIGHTNET_CANDIDATES)

# Only include sources whose files actually exist right now
AHK_JAPAN_CSV_PATH = _first_existing(_AHK_JAPAN_CANDIDATES)

CSV_SOURCES = [s for s in [
    {"path": CSV_PATH,             "network": "WFA"}       if CSV_PATH             else None,
    {"path": WWPC_CSV_PATH,        "network": "WWPC"}      if WWPC_CSV_PATH        else None,
    {"path": FIATA_CSV_PATH,       "network": "FIATA"}     if FIATA_CSV_PATH       else None,
    {"path": FREIGHTNET_CSV_PATH,  "network": None}        if FREIGHTNET_CSV_PATH  else None,
    {"path": AHK_JAPAN_CSV_PATH,   "network": "AHK-Japan"} if AHK_JAPAN_CSV_PATH  else None,
] if s]

# Carrier schedule APIs
MAERSK_API_KEY = os.environ.get("MAERSK_API_KEY", "")
MSC_API_KEY    = os.environ.get("MSC_API_KEY", "")
CMA_API_KEY    = os.environ.get("CMA_API_KEY", "")
HAPAG_API_KEY  = os.environ.get("HAPAG_API_KEY", "")
DCSA_API_KEY   = os.environ.get("DCSA_API_KEY", "")

# Schedule sync
SCHEDULE_SYNC_INTERVAL_HOURS = int(os.environ.get("SCHEDULE_SYNC_INTERVAL", "6"))
SCHEDULE_SYNC_DAYS_AHEAD     = int(os.environ.get("SCHEDULE_SYNC_DAYS", "30"))
