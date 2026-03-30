FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    TMS_ENV=production \
    SESSION_COOKIE_SECURE=1 \
    FLASK_DEBUG=0 \
    GUNICORN_BIND=127.0.0.1:8000 \
    TMS_DB_PATH=/home/data/tms.db

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY tms/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY tms /app/tms
COPY templates /app/templates
COPY static /app/static
COPY tms/wsgi.py tms/nginx.conf tms/supervisord.conf tms/entrypoint.sh tms/README.md tms/.env.example tms/deploy_azure.sh ./

RUN chmod +x /app/entrypoint.sh /app/deploy_azure.sh && \
    mkdir -p /home/data && \
    rm -f /etc/nginx/sites-enabled/default

COPY tms/nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080

CMD ["/app/entrypoint.sh"]

