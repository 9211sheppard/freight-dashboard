## Monday Handoff

Use the hardened full service in [`wsgi.py`](/C:/Users/Owner/Desktop/tms-master/tms/wsgi.py). It now serves the legacy TMS feature set with production guards. Do not deploy the legacy root [`app.py`](/C:/Users/Owner/Desktop/tms-master/app.py).

### Required production env

- `TMS_ENV=production`
- `SECRET_KEY=<32+ char random secret>`
- `INTEGRATION_MASTER_KEY=<separate 32+ char random secret>`
- `BASE_URL=https://<your-azure-hostname>`
- `SESSION_COOKIE_SECURE=true`
- `TMS_ALLOWED_HOSTS=<azure hostname>`
- `TMS_CONTACTS_DB_PATH=/home/data/contacts.db`
- `TMS_POD_UPLOAD_DIR=/home/data/uploads/pods`
- `TMS_ADMIN_EMAIL=<real admin email>`
- `TMS_ADMIN_PASSWORD=<real strong password>` or `TMS_ADMIN_PASSWORD_HASH=<werkzeug hash>`
- `TMS_DISPATCHER_EMAIL=<real dispatcher email>`
- `TMS_DISPATCHER_PASSWORD=<real strong password>` or `TMS_DISPATCHER_PASSWORD_HASH=<werkzeug hash>`
- `TMS_VIEWER_EMAIL=<real viewer email>`
- `TMS_VIEWER_PASSWORD=<real strong password>` or `TMS_VIEWER_PASSWORD_HASH=<werkzeug hash>`

### Monday scope

- Private pilot only
- Named users only
- No public signup
- Azure HTTPS only
- Rotate every placeholder secret before first boot
- `TMS_APP_MODE=full`
- `TMS_ENFORCE_CSRF=true`
- `TMS_ENFORCE_ROUTE_AUTH=true`
- `TMS_ALLOW_REQUEST_TENANT_OVERRIDE=false`
- `TMS_ALLOW_REQUEST_ACTOR_OVERRIDE=false`
- `TMS_ENABLE_NOTIFICATION_SCHEDULER=false`
- `TMS_ENABLE_EDI_WATCHER=false`
- Use a dedicated `INTEGRATION_MASTER_KEY`, not a placeholder and not a short dev secret
- Set `BASE_URL` before sending any customer/driver emails so links do not point to localhost
- Customer shipment tracking now uses signed `/track/<ref>?token=...` links; bare `/track/<ref>` should stay blocked
- The container image no longer ships bundled SQLite data; mount or provision `/home/data` on Azure
- Static assets are served from `/app/static` in the container, and nginx now allows up to `25m` uploads to match the hardened app path
- The hardened login supports werkzeug password hashes for office users; hashes are preferred over plaintext app-setting passwords
- Notification and workflow schedulers stay off in the Azure web app by default; run them only in a deliberate worker process

### AI operating workflow

- Claude owns Azure setup, ticket intake, deployment, and first-pass review.
- Codex owns code fixes, hardening, regression checks, and post-deploy verification.
- Every fix goes to staging first, with backup/rollback ready before Azure publish.
- After Claude deploys, Codex verifies the live Azure config matches the hardened code path.
- Only tell pilot users an issue is fixed after deployment verification passes.

### Verify

- `python -m unittest tests.test_app`
- `python -m unittest tms.tests.test_secret_storage tms.tests.test_portal`
- `python tms/azure_smoke_check.py https://<your-azure-hostname>`
- `/track/<ref>` returns `403` without a signed token
- Login requires MFA setup or MFA verify
- Admin pages load only after login
- Hostname outside `TMS_ALLOWED_HOSTS` is rejected
