import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tms.tms_db as tms_db
from tms import tms as tms_blueprint
from tms.tenanting import tenant_context


class TenantAdminTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tenant-test.db")
        tms_db.init_tms_db()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "tenant-test-secret"
        self.app.register_blueprint(tms_blueprint)

        @self.app.route("/logout")
        def logout():
            return "", 204

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return f"tracking:{ref}"

        self.client = self.app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "qa@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        tms_db.close_open_connections()
        self.client = None
        self.app = None
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def _switch_tenant(self, tenant_id):
        with self.client.session_transaction() as session_state:
            session_state["tms_tenant_id"] = tenant_id

    def test_all_tables_have_tenant_id_and_driver_views_are_isolated(self):
        conn = tms_db.get_db()
        try:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for row in tables:
                columns = {
                    item["name"]
                    for item in conn.execute(f"PRAGMA table_info({row['name']})").fetchall()
                }
                self.assertIn("tenant_id", columns, row["name"])
        finally:
            conn.close()

        tenant = tms_db.create_tenant(
            company_name="Acme Logistics",
            plan="pro",
            max_users=12,
            data_region="us-east",
            session_timeout_minutes=45,
            allowed_ip_cidrs="",
        )

        with tenant_context(tenant_id="tenant-default"):
            conn = tms_db.get_db()
            conn.execute(
                "INSERT INTO drivers (name, license_number, phone, country, status) VALUES (?, ?, ?, ?, ?)",
                ("Default Driver", "DEF-001", "+1-555-0100", "Canada", "Active"),
            )
            conn.commit()
            conn.close()

        with tenant_context(tenant_id=tenant["tenant_id"]):
            conn = tms_db.get_db()
            conn.execute(
                "INSERT INTO drivers (name, license_number, phone, country, status) VALUES (?, ?, ?, ?, ?)",
                ("Tenant Driver", "TEN-001", "+1-555-0101", "United States", "Active"),
            )
            conn.commit()
            conn.close()

        default_response = self.client.get("/tms/drivers")
        self.assertEqual(default_response.status_code, 200)
        self.assertIn(b"Default Driver", default_response.data)
        self.assertNotIn(b"Tenant Driver", default_response.data)

        self._switch_tenant(tenant["tenant_id"])
        tenant_response = self.client.get("/tms/drivers")
        self.assertEqual(tenant_response.status_code, 200)
        self.assertIn(b"Tenant Driver", tenant_response.data)
        self.assertNotIn(b"Default Driver", tenant_response.data)

    def test_admin_tenant_route_can_create_and_switch(self):
        response = self.client.post(
            "/tms/admin/tenants",
            data={
                "action": "create",
                "company_name": "Northwind Freight",
                "plan": "enterprise",
                "max_users": "50",
                "data_region": "eu-west",
                "session_timeout_minutes": "20",
                "allowed_ip_cidrs": "203.0.113.0/24",
                "saml_entity_id": "urn:northwind",
                "saml_sso_url": "https://idp.example.com/sso",
                "saml_metadata_url": "https://idp.example.com/metadata",
                "saml_x509_cert": "CERTDATA",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Northwind Freight", response.data)

        tenant = tms_db.get_tenant("northwind-freight")
        self.assertIsNotNone(tenant)
        self.assertEqual(tenant["status"], "active")

        switch_response = self.client.post(
            "/tms/admin/tenants",
            data={"action": "switch", "tenant_id": tenant["tenant_id"]},
            follow_redirects=False,
        )
        self.assertEqual(switch_response.status_code, 302)
        with self.client.session_transaction() as session_state:
            self.assertEqual(session_state["tms_tenant_id"], tenant["tenant_id"])

    def test_admin_audit_route_and_export_capture_driver_create(self):
        create_response = self.client.post(
            "/tms/drivers/new",
            data={
                "name": "Audit Driver",
                "license_number": "AUD-001",
                "phone": "+1-555-0102",
                "country": "Canada",
                "status": "Active",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        audit_response = self.client.get("/tms/admin/audit?user_id=qa@example.com&action=INSERT")
        self.assertEqual(audit_response.status_code, 200)
        self.assertIn(b"drivers", audit_response.data)
        self.assertIn(b"qa@example.com", audit_response.data)

        export_response = self.client.get("/tms/admin/audit/export?user_id=qa@example.com&action=INSERT")
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("text/csv", export_response.headers["Content-Type"])
        self.assertIn(b"qa@example.com", export_response.data)
        self.assertIn(b"drivers", export_response.data)

    def test_non_admin_cannot_access_admin_routes(self):
        with self.client.session_transaction() as session_state:
            session_state["user_role"] = "viewer"

        tenants_response = self.client.get("/tms/admin/tenants")
        audit_response = self.client.get("/tms/admin/audit")

        self.assertEqual(tenants_response.status_code, 403)
        self.assertEqual(audit_response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
