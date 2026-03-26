Copy `.env.example` to `.env` and replace placeholder secrets.
Run `python -m pip install -r requirements.txt`.
Start with `python wsgi.py`.
Open `/tms/admin/tenants`, `/tms/admin/audit`, and `/login`.
Verify with `python -m unittest tests.test_app tms.tests.test_tenant_admin`.
