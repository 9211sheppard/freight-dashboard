import os
import sys
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
if (CURRENT_DIR / "__init__.py").exists():
    repo_root = CURRENT_DIR.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


APP_MODE = os.getenv("TMS_APP_MODE", "full").strip().lower()
if APP_MODE == "shell":
    from tms.tms_app import create_app
else:
    from tms.full_app import create_app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "").strip() == "1",
    )

