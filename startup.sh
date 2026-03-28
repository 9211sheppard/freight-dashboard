#!/bin/bash
# Azure App Service startup script for Freight Intelligence Dashboard

# Install system dependencies for weasyprint PDF generation
apt-get update -qq && apt-get install -y -qq libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info 2>/dev/null || true

# Start gunicorn
gunicorn wsgi:app \
  --workers 2 \
  --threads 4 \
  --bind 0.0.0.0:${PORT:-5000} \
  --timeout 120 \
  --access-logfile - \
  --error-logfile - \
  --log-level info
