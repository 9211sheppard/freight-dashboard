import os
import sys

# ─────────────────────────────────────────────
#  LOGIN PASSWORD  — change this to your own
# ─────────────────────────────────────────────
PASSWORD = "admin123"

# ─────────────────────────────────────────────
#  EMAIL / SMTP  — fill in to enable sending
#  Leave EMAIL_USER blank to disable sending
#  (manual parse/upload path still works)
# ─────────────────────────────────────────────
EMAIL_HOST = ""
EMAIL_PORT = 587
EMAIL_USER = ""
EMAIL_PASS = ""
EMAIL_FROM = ""

# ─────────────────────────────────────────────
#  FMCSA SAFER API KEY  — free at:
#  https://ask.fmcsa.dot.gov/app/ask
# ─────────────────────────────────────────────
FMCSA_KEY = ""   # paste your free key here

# ─────────────────────────────────────────────
#  SECRET KEY  — used to sign session cookies
# ─────────────────────────────────────────────
SECRET_KEY = "wfa-dashboard-secret-key-2024-change-me"

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

# ── Owner's source CSV paths (only used when the files actually exist) ────
# Team members don't need these — they use the Import CSV button instead.
_WFA_CANDIDATES = [
    r"C:\Users\Owner\automations\wfa_contacts.csv",
    os.path.join(DATA_DIR, "upload_wfa.csv"),          # uploaded via dashboard
]
_WWPC_CANDIDATES = [
    r"C:\Users\Owner\Desktop\wwpc_contacts.csv",
    os.path.join(DATA_DIR, "upload_wwpc.csv"),         # uploaded via dashboard
]
_FIATA_CANDIDATES = [
    r"C:\Users\Owner\Desktop\fiata_contacts.csv",
    os.path.join(DATA_DIR, "upload_fiata.csv"),        # uploaded via dashboard
]
_FREIGHTNET_CANDIDATES = [
    r"C:\Users\Owner\Desktop\freightnet_global.csv",          # global scrape (primary)
    os.path.join(DATA_DIR, "upload_freightnet.csv"),          # uploaded via dashboard
]
_AHK_JAPAN_CANDIDATES = [
    os.path.join(DATA_DIR, "upload_ahk-japan.csv"),           # AHK Japan member directory
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
