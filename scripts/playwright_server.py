import atexit
import shutil
import tempfile
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tms import tms_db
from tms.full_app import create_app


PORT = 4173
RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="tms-playwright-"))


def _cleanup():
    try:
        tms_db.close_open_connections()
    finally:
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)


atexit.register(_cleanup)


def build_app():
    app = create_app(
        {
            "TESTING": True,
            "TMS_ENV": "development",
            "SECRET_KEY": "playwright-launch-secret-1234567890",
            "BASE_URL": f"http://127.0.0.1:{PORT}",
            "ALLOWED_HOSTS": {"127.0.0.1", "localhost"},
            "SESSION_COOKIE_SECURE": False,
            "TMS_ENFORCE_CSRF": True,
            "TMS_DB_PATH": str(RUNTIME_DIR / "tms.db"),
            "TMS_CONTACTS_DB_PATH": str(RUNTIME_DIR / "contacts.db"),
            "TMS_POD_UPLOAD_DIR": str(RUNTIME_DIR / "pods"),
            "TMS_ADMIN_EMAIL": "admin@example.com",
            "TMS_ADMIN_PASSWORD_HASH": generate_password_hash("LaunchPilot!123"),
            "TMS_ADMIN_NAME": "Playwright Admin",
            "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
            "TMS_DISPATCHER_PASSWORD_HASH": generate_password_hash("LaunchPilot!123"),
            "TMS_VIEWER_EMAIL": "viewer@example.com",
            "TMS_VIEWER_PASSWORD_HASH": generate_password_hash("LaunchPilot!123"),
        }
    )
    tms_db.save_setup("Playwright Freight", "#0f766e")
    return app


app = build_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
