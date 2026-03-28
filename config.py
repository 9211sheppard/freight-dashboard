import os
import sys

# ─────────────────────────────────────────────
#  LOGIN PASSWORD  — change this to your own
#  On Azure, set env var DASHBOARD_PASSWORD
# ─────────────────────────────────────────────
_DEFAULT_DEV_PASSWORD = "admin123"
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", _DEFAULT_DEV_PASSWORD)
if PASSWORD == _DEFAULT_DEV_PASSWORD and not os.environ.get("FLASK_DEBUG"):
    import warnings
    warnings.warn(
        "Using default password! Set env var DASHBOARD_PASSWORD for production.",
        stacklevel=2
    )

# ─────────────────────────────────────────────
#  DEV MODE — auto-login locally (no password prompt)
#  Set AUTO_LOGIN=1 or rely on localhost detection
# ─────────────────────────────────────────────
AUTO_LOGIN = os.environ.get("AUTO_LOGIN", "1" if not os.environ.get("WEBSITE_HOSTNAME") else "0") == "1"

# ─────────────────────────────────────────────
#  SECURITY SETTINGS
# ─────────────────────────────────────────────
MAX_LOGIN_ATTEMPTS    = int(os.environ.get("MAX_LOGIN_ATTEMPTS", "5"))
LOCKOUT_MINUTES       = int(os.environ.get("LOCKOUT_MINUTES", "15"))
SESSION_LIFETIME_HOURS = int(os.environ.get("SESSION_LIFETIME_HOURS", "8"))
MFA_ISSUER_NAME       = os.environ.get("MFA_ISSUER_NAME", "Freight Intelligence")
SECURITY_PASSWORD_SALT = os.environ.get("SECURITY_PASSWORD_SALT", "freight-salt-v1")
API_RATE_LIMIT        = int(os.environ.get("API_RATE_LIMIT", "120"))
LOGIN_RATE_LIMIT      = int(os.environ.get("LOGIN_RATE_LIMIT", "10"))
MAX_UPLOAD_SIZE_MB    = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "10"))

# ─────────────────────────────────────────────
#  OAuth2 / SSO  (set env vars to enable)
# ─────────────────────────────────────────────
GOOGLE_CLIENT_ID      = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET  = os.environ.get("GOOGLE_CLIENT_SECRET", "")
MICROSOFT_CLIENT_ID   = os.environ.get("MICROSOFT_CLIENT_ID", "")
MICROSOFT_CLIENT_SECRET = os.environ.get("MICROSOFT_CLIENT_SECRET", "")
OAUTH_REDIRECT_BASE   = os.environ.get("OAUTH_REDIRECT_BASE", "http://localhost:5000")

# ─────────────────────────────────────────────
#  Bot Protection (hCaptcha — set env vars to enable)
# ─────────────────────────────────────────────
HCAPTCHA_SITE_KEY     = os.environ.get("HCAPTCHA_SITE_KEY", "")
HCAPTCHA_SECRET_KEY   = os.environ.get("HCAPTCHA_SECRET_KEY", "")

# ─────────────────────────────────────────────
#  Security Contact (for security.txt)
# ─────────────────────────────────────────────
SECURITY_CONTACT_EMAIL = os.environ.get("SECURITY_CONTACT_EMAIL", "security@flashcargo.com")

# ─────────────────────────────────────────────
#  WAF / Reverse Proxy (Cloudflare, AWS ALB)
#  Set BEHIND_PROXY=true when behind Cloudflare/ALB
# ─────────────────────────────────────────────
BEHIND_PROXY          = os.environ.get("BEHIND_PROXY", "").lower() in ("true", "1", "yes")
TRUSTED_PROXY_IPS     = [ip.strip() for ip in os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1").split(",") if ip.strip()]
CLOUDFLARE_ENABLED    = os.environ.get("CLOUDFLARE_ENABLED", "").lower() in ("true", "1", "yes")

# ─────────────────────────────────────────────
#  DDoS / Abuse Protection
# ─────────────────────────────────────────────
DDOS_RATE_LIMIT       = int(os.environ.get("DDOS_RATE_LIMIT", "300"))       # max requests/min per IP (global)
DDOS_BAN_THRESHOLD    = int(os.environ.get("DDOS_BAN_THRESHOLD", "1000"))   # auto-ban IP after this many in 1 min
DDOS_BAN_DURATION_MIN = int(os.environ.get("DDOS_BAN_DURATION_MIN", "60"))  # ban duration in minutes

# ─────────────────────────────────────────────
#  SOC 2 / Compliance
# ─────────────────────────────────────────────
AUDIT_RETENTION_DAYS  = int(os.environ.get("AUDIT_RETENTION_DAYS", "365"))  # keep audit logs for 1 year
DATA_RETENTION_DAYS   = int(os.environ.get("DATA_RETENTION_DAYS", "730"))   # keep user data for 2 years
ACCESS_REVIEW_INTERVAL_DAYS = int(os.environ.get("ACCESS_REVIEW_INTERVAL", "90"))  # quarterly access reviews

# ─────────────────────────────────────────────
#  Bug Bounty
# ─────────────────────────────────────────────
BUG_BOUNTY_ENABLED    = os.environ.get("BUG_BOUNTY_ENABLED", "").lower() in ("true", "1", "yes")
BUG_BOUNTY_URL        = os.environ.get("BUG_BOUNTY_URL", "")  # e.g., HackerOne/Bugcrowd URL

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
