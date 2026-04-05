Copy `.env.example` to `.env` and replace every placeholder secret/password, including `INTEGRATION_MASTER_KEY`.
Run `python -m pip install -r requirements.txt`.
Start the full hardened app with `python wsgi.py` or set `TMS_APP_MODE=shell` for the auth-only shell.
Use `TMS_ENV=production` only with real secrets, `BASE_URL`, real hosts, and TLS.
For containers, mount persistent storage for `/home/data`; the image no longer bundles local `.db` files.
Office logins can use plaintext `TMS_*_PASSWORD` values or preferred werkzeug hashes via `TMS_*_PASSWORD_HASH`.
Notification/workflow schedulers now stay off by default in production web processes unless `TMS_ENABLE_NOTIFICATION_SCHEDULER=true` is set for a dedicated worker.
Verify with `python -m unittest tests.test_app tests.test_api_requests tests.test_dispatch_board`.
Smoke-check a deployed Azure site with `python tms/azure_smoke_check.py https://your-app.azurewebsites.net`.
Customer tracking links are now signed; bare `/track/<ref>` requests should fail unless the user is logged in.
The bundled nginx config serves `/static/` from `/app/static` and allows up to `25m` request bodies.
