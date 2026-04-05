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
from tms.cold_chain import configure_shipment


class LaunchGuardrailTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "guardrails.db")
        tms_db.init_tms_db()
        tms_db.preload_demo_data()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "g" * 48
        self.app.register_blueprint(tms_blueprint)

        @self.app.route("/logout")
        def logout():
            return "ok"

        @self.app.route("/track/<ref>", endpoint="public_tracking")
        def public_tracking(ref):
            return f"tracking:{ref}"

        self.client = self.app.test_client()
        configure_shipment(
            shipment_ref="TMS-DEMO-003",
            min_temp="1",
            max_temp="5",
            min_humidity="",
            max_humidity="",
            alert_email="alerts@example.com",
            provider="tive",
            sensor_id="SENSOR-77",
        )

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        tms_db.close_open_connections()
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_unauthenticated_internal_routes_fail_closed(self):
        endpoints = [
            ("/tms/api-keys", "get"),
            ("/tms/edi/partners", "get"),
            ("/tms/integrations", "get"),
            ("/tms/settings/email", "get"),
            ("/tms/settings/billing", "get"),
            ("/tms/edi/upload", "post"),
        ]
        for path, method in endpoints:
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, 401, path)

    def test_sensitive_admin_routes_require_admin_role(self):
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "viewer@example.com"
            session_state["user_role"] = "viewer"
            session_state["tms_tenant_id"] = "tenant-default"

        for path in (
            "/tms/api-keys",
            "/tms/admin/tenants",
            "/tms/admin/audit",
            "/tms/integrations",
            "/tms/settings/email",
            "/tms/settings/billing",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403, path)

    def test_api_v1_stays_bearer_protected_not_session_redirected(self):
        response = self.client.get("/api/v1/shipments")
        self.assertEqual(response.status_code, 401)
        payload = response.get_json()
        self.assertEqual(payload["error"]["code"], "missing_bearer_token")

    def test_public_ingest_routes_still_require_tokens_or_allow_public_submission(self):
        tracking_response = self.client.post(
            "/tms/track/ping",
            json={
                "shipment_ref": "TMS-DEMO-003",
                "lat": 43.7,
                "lng": -79.4,
            },
        )
        cold_chain_response = self.client.post(
            "/tms/cold-chain/reading",
            json={
                "shipment_ref": "TMS-DEMO-003",
                "provider": "tive",
                "sensor_id": "SENSOR-77",
                "temperature_c": 3.4,
            },
        )
        privacy_response = self.client.post(
            "/tms/compliance/privacy/submit",
            data={
                "request_type": "access",
                "name": "Jane Doe",
                "email": "jane@example.com",
            },
        )

        self.assertEqual(tracking_response.status_code, 403)
        self.assertEqual(cold_chain_response.status_code, 403)
        self.assertEqual(privacy_response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
