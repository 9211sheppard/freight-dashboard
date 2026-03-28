FROM python:3.11-slim

# System deps for psycopg2 and bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for SQLite fallback / file uploads
RUN mkdir -p /app/data

# Default port (Railway sets $PORT automatically)
ENV PORT=5000
ENV PRODUCTION=1

EXPOSE $PORT

CMD gunicorn wsgi:app --workers 2 --bind 0.0.0.0:$PORT --timeout 120
