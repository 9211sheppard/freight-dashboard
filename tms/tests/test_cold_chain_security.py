import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tms.tms_db as tms_db
import tms.tms_routes as tms_routes
from tms import tms as tms_blueprint
from tms.cold_chain import configure_shipment


class ColdChainSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "cold-chain.db")
        tms_db.init_tms_db()
        tms_db.preload_demo_data()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "c" * 48
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

    def _token(self):
        with self.app.test_request_context():
            return tms_routes._create_cold_chain_ingest_token("TMS-DEMO-003", "tive", "SENSOR-77")

    def test_cold_chain_reading_requires_signed_ingest_token(self):
        response = self.client.post(
            "/tms/cold-chain/reading",
            json={
                "shipment_ref": "TMS-DEMO-003",
                "provider": "tive",
                "sensor_id": "SENSOR-77",
                "temperature_c": 3.4,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("token", response.get_json()["error"].lower())

    def test_cold_chain_reading_accepts_valid_signed_ingest_token(self):
        response = self.client.post(
            "/tms/cold-chain/reading",
            json={
                "shipment_ref": "TMS-DEMO-003",
                "provider": "tive",
                "sensor_id": "SENSOR-77",
                "temperature_c": 3.4,
                "ingest_token": self._token(),
            },
        )
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["reading"]["shipment_ref"], "TMS-DEMO-003")
        self.assertEqual(payload["reading"]["sensor_id"], "SENSOR-77")

    def test_cold_chain_reading_rejects_mismatched_sensor_even_with_token(self):
        response = self.client.post(
            "/tms/cold-chain/reading",
            json={
                "shipment_ref": "TMS-DEMO-003",
                "provider": "tive",
                "sensor_id": "SENSOR-OTHER",
                "temperature_c": 3.4,
                "ingest_token": self._token(),
            },
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
