import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("TMS_MASTER_BRAND_NAME", "TMS Master")
PORT = int(os.getenv("PORT", "5001"))
SECRET_KEY = os.getenv("SECRET_KEY", "tms-master-dev-change-me")
SESSION_LIFETIME_HOURS = int(os.getenv("SESSION_LIFETIME_HOURS", "12"))
MAX_CONTENT_LENGTH_MB = int(os.getenv("MAX_CONTENT_LENGTH_MB", "50"))
LOGIN_USERNAME = os.getenv("TMS_MASTER_USERNAME", "admin")
LOGIN_PASSWORD = os.getenv("TMS_MASTER_PASSWORD", "change-me")

DATA_DIR = Path(os.getenv("TMS_MASTER_DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(Path(os.getenv("TMS_MASTER_DB_PATH", DATA_DIR / "contacts.db")).resolve())
BASE_URL = os.getenv("BASE_URL", f"http://localhost:{PORT}")
