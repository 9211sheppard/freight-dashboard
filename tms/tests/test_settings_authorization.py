import sys
import tempfile
import unittest
import json
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tms.tms_db as tms_db
from tms import portal as portal_blueprint
from tms import public as public_blueprint
from tms import tms as tms_blueprint


class SettingsAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "settings-auth.db")
        tms_db.init_tms_db()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "settings-auth-secret"
        self.app.add_template_filter(lambda value: json.loads(value or "[]"), "from_json")
        self.app.register_blueprint(tms_blueprint)
        self.app.register_blueprint(portal_blueprint)
        self.app.register_blueprint(public_blueprint)

        @self.app.route("/logout")
        def logout():
            return "", 204

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return f"tracking:{ref}"

        self.client = self.app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "ops@example.com"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        tms_db.close_open_connections()
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_viewer_cannot_access_email_or_billing_settings(self):
        with self.client.session_transaction() as session_state:
            session_state["user_role"] = "viewer"

        email_response = self.client.get("/tms/settings/email")
        billing_response = self.client.get("/tms/settings/billing")
        billing_toggle_response = self.client.post(
            "/tms/settings/billing/addons/driver-app",
            json={"action": "add"},
        )
        integrations_response = self.client.get("/tms/integrations")
        integrations_settings_response = self.client.get("/tms/integrations/settings")
        integrations_test_response = self.client.post("/tms/integrations/test/fake-provider")

        self.assertEqual(email_response.status_code, 403)
        self.assertEqual(billing_response.status_code, 403)
        self.assertEqual(billing_toggle_response.status_code, 403)
        self.assertEqual(integrations_response.status_code, 403)
        self.assertEqual(integrations_settings_response.status_code, 403)
        self.assertEqual(integrations_test_response.status_code, 403)

    def test_admin_can_access_email_and_billing_settings(self):
        with self.client.session_transaction() as session_state:
            session_state["user_role"] = "admin"

        email_response = self.client.get("/tms/settings/email")
        billing_response = self.client.get("/tms/settings/billing")
        integrations_response = self.client.get("/tms/integrations")
        integrations_settings_response = self.client.get("/tms/integrations/settings")

        self.assertEqual(email_response.status_code, 200)
        self.assertEqual(billing_response.status_code, 200)
        self.assertEqual(integrations_response.status_code, 200)
        self.assertEqual(integrations_settings_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
