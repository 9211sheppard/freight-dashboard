# Deployment

## Local legacy sandbox only
1. Create and activate a virtualenv in `C:\Users\Owner\Desktop\tms-master`.
2. Install packages with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and set `SECRET_KEY`, `TMS_MASTER_USERNAME`, and `TMS_MASTER_PASSWORD`.
4. Start the legacy sandbox with `python app.py`.
5. Open `http://localhost:5001`.

## Production / Azure handoff
1. Do not deploy the root `app.py` service in production.
2. Deploy the hardened service from [`tms/wsgi.py`](/C:/Users/Owner/Desktop/tms-master/tms/wsgi.py) using the `tms/` Docker/runtime files.
3. Set non-placeholder values for `SECRET_KEY`, `TMS_ALLOWED_HOSTS`, and all seeded user passwords before startup.
4. Keep `SESSION_COOKIE_SECURE=true` and terminate TLS at Azure.
