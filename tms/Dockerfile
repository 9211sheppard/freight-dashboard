FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080 \
    GUNICORN_BIND=127.0.0.1:8000 \
    TMS_DB_PATH=/app/data/tms.db

RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tms_app ./tms_app
COPY wsgi.py nginx.conf supervisord.conf entrypoint.sh README.md .env.example deploy_azure.sh ./

RUN chmod +x /app/entrypoint.sh /app/deploy_azure.sh && \
    mkdir -p /app/data && \
    rm -f /etc/nginx/sites-enabled/default

COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080

CMD ["/app/entrypoint.sh"]

