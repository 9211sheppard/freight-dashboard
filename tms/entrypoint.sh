#!/bin/sh
set -eu

DB_PATH="${TMS_DB_PATH:-/app/data/tms.db}"
mkdir -p "$(dirname "$DB_PATH")" /var/log/supervisor /var/cache/nginx /var/lib/nginx /run/nginx

exec /usr/bin/supervisord -c /app/supervisord.conf
