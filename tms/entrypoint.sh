#!/bin/sh
set -eu

DB_PATH="${TMS_DB_PATH:-/home/data/tms.db}"
CONTACTS_DB_PATH="${TMS_CONTACTS_DB_PATH:-/home/data/contacts.db}"
POD_UPLOAD_DIR="${TMS_POD_UPLOAD_DIR:-/home/data/uploads/pods}"
mkdir -p "$(dirname "$DB_PATH")" "$(dirname "$CONTACTS_DB_PATH")" "$POD_UPLOAD_DIR" /var/log/supervisor /var/cache/nginx /var/lib/nginx /run/nginx

if [ ! -f "$CONTACTS_DB_PATH" ]; then
  python - "$CONTACTS_DB_PATH" <<'PY'
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
db_path.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(db_path)
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL DEFAULT '',
        dot_number TEXT DEFAULT '',
        safety_rating TEXT DEFAULT '',
        country TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone_number TEXT DEFAULT ''
    )
    """
)
conn.commit()
conn.close()
PY
fi

if [ "${TMS_ENV:-development}" = "production" ]; then
  for var_name in \
    SECRET_KEY \
    INTEGRATION_MASTER_KEY \
    BASE_URL \
    TMS_ALLOWED_HOSTS \
    TMS_ADMIN_EMAIL \
    TMS_ADMIN_PASSWORD \
    TMS_DISPATCHER_EMAIL \
    TMS_DISPATCHER_PASSWORD \
    TMS_VIEWER_EMAIL \
    TMS_VIEWER_PASSWORD
  do
    eval "var_value=\${$var_name:-}"
    if [ -z "$var_value" ]; then
      echo "Missing required production environment variable: $var_name" >&2
      exit 1
    fi
  done
fi

exec /usr/bin/supervisord -c /app/supervisord.conf
