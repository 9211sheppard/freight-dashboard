import tempfile
import unittest
from pathlib import Path

from flask import Flask

import tms.tms_routes as tms_routes
from tms.tms_routes import tms as tms_blueprint
from tms import tms_db


class TmsTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tracking-test.db")
        tms_db._LOCATION_COORD_CACHE.clear()
        tms_db.init_tms_db()
        tms_db.preload_demo_data()

        repo_root = Path(__file__).resolve().parents[2]
        app = Flask(
            __name__,
            template_folder=str(repo_root / "templates"),
            static_folder=str(repo_root / "static"),
        )
        app.secret_key = "tracking-test-secret"
        app.register_blueprint(tms_blueprint)

        @app.route("/track/<ref>", endpoint="public_tracking")
        def public_tracking(ref):
            return app.view_functions["tms.customer_track"](ref)

        @app.route("/logout")
        def logout():
            return "ok"

        self.app = app
        self.client = app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        tms_db.close_open_connections()
        tms_db.TMS_DB = self.original_db
        tms_db._LOCATION_COORD_CACHE.clear()
        self.client = None
        self.app = None
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def _carrier_id_for(self, shipment_ref):
        conn = tms_db.get_db()
        try:
            row = conn.execute(
                "SELECT carrier_id FROM shipments WHERE shipment_ref = ?",
                (shipment_ref,),
            ).fetchone()
            return row["carrier_id"]
        finally:
            conn.close()

    def test_tracking_ping_endpoint_stores_ping(self):
        token = tms_db.get_or_create_tracking_driver_token("TMS-DEMO-003", self._carrier_id_for("TMS-DEMO-003"))
        response = self.client.post(
            "/tms/track/ping",
            json={
                "tracking_token": token,
                "lat": 43.70011,
                "lng": -79.4163,
                "speed": 82,
                "timestamp": "2026-03-26T15:15:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ping"]["shipment_ref"], "TMS-DEMO-003")
        self.assertIn("/track/TMS-DEMO-003?token=", payload["tracking_url"])

        conn = tms_db.get_db()
        try:
            count = conn.execute("SELECT COUNT(*) FROM tracking_pings").fetchone()[0]
        finally:
            conn.close()

    def _public_tracking_url(self, shipment_ref):
        with self.app.test_request_context():
            return tms_routes.build_public_tracking_url(shipment_ref)
        self.assertEqual(count, 1)

    def test_tracking_ping_endpoint_requires_driver_token(self):
        response = self.client.post(
            "/tms/track/ping",
            json={
                "shipment_ref": "TMS-DEMO-003",
                "lat": 43.70011,
                "lng": -79.4163,
            },
        )
        self.assertEqual(response.status_code, 403)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("tracking token", payload["error"].lower())

    def test_driver_tracking_page_renders_for_generated_token(self):
        token = tms_db.get_or_create_tracking_driver_token("TMS-DEMO-003", self._carrier_id_for("TMS-DEMO-003"))
        response = self.client.get(f"/tms/track/driver/{token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"TMS-DEMO-003", response.data)
        self.assertIn(b"Submit GPS Ping", response.data)

    def test_internal_shipment_view_renders_leaflet_map(self):
        tms_db.save_tracking_ping(
            carrier_id=self._carrier_id_for("TMS-DEMO-003"),
            shipment_ref="TMS-DEMO-003",
            lat=43.70011,
            lng=-79.4163,
            speed=82,
            timestamp="2026-03-26T15:15:00Z",
        )
        response = self.client.get("/tms/shipments/TMS-DEMO-003")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"shipmentLiveMap", response.data)
        self.assertIn(b"leaflet.js", response.data)
        self.assertIn(b"Copy Driver Link", response.data)

    def test_public_tracking_page_only_shows_live_map_after_ping(self):
        unauthorized_response = self.client.get("/track/TMS-DEMO-003")
        self.assertEqual(unauthorized_response.status_code, 403)

        tracking_url = self._public_tracking_url("TMS-DEMO-003")
        self.assertIn("token=", tracking_url)

        before_response = self.client.get(tracking_url)
        self.assertEqual(before_response.status_code, 200)
        self.assertNotIn(b"publicTrackingMap", before_response.data)

        tms_db.save_tracking_ping(
            carrier_id=self._carrier_id_for("TMS-DEMO-003"),
            shipment_ref="TMS-DEMO-003",
            lat=43.70011,
            lng=-79.4163,
            speed=82,
            timestamp="2026-03-26T15:15:00Z",
        )

        after_response = self.client.get(tracking_url)
        self.assertEqual(after_response.status_code, 200)
        self.assertIn(b"publicTrackingMap", after_response.data)
        self.assertIn(b"Last known position and route trail", after_response.data)

    def test_control_tower_page_renders_leaflet_map_and_refresh_hook(self):
        response = self.client.get("/tms/control-tower")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"controlTowerMap", response.data)
        self.assertIn(b"leaflet.js", response.data)
        self.assertIn(b"/tms/control-tower/data", response.data)
        self.assertIn(b"Refreshes every 30 seconds", response.data)
        self.assertIn(b"TMS-DEMO-003", response.data)
        self.assertNotIn(b"TMS-DEMO-004", response.data)

    def test_control_tower_data_includes_active_shipments_and_live_pings(self):
        tms_db.save_tracking_ping(
            carrier_id=self._carrier_id_for("TMS-DEMO-003"),
            shipment_ref="TMS-DEMO-003",
            lat=43.70011,
            lng=-79.4163,
            speed=82,
            timestamp="2026-03-26T15:15:00Z",
        )
        tms_db.save_tracking_ping(
            carrier_id=self._carrier_id_for("TMS-DEMO-003"),
            shipment_ref="TMS-DEMO-003",
            lat=42.33143,
            lng=-83.04575,
            speed=79,
            timestamp="2026-03-26T19:45:00Z",
        )

        response = self.client.get("/tms/control-tower/data")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(payload["counts"]["total"], 4)
        self.assertEqual(payload["counts"]["on_time"], 2)
        self.assertEqual(payload["counts"]["at_risk"], 0)
        self.assertEqual(payload["counts"]["draft"], 1)
        self.assertEqual(payload["counts"]["delayed"], 1)

        shipment_refs = {shipment["shipment_ref"] for shipment in payload["shipments"]}
        self.assertIn("TMS-DEMO-003", shipment_refs)
        self.assertNotIn("TMS-DEMO-004", shipment_refs)

        shipment = next(
            shipment for shipment in payload["shipments"] if shipment["shipment_ref"] == "TMS-DEMO-003"
        )
        self.assertEqual(shipment["health_key"], "delayed")
        self.assertTrue(shipment["has_live_data"])
        self.assertEqual(shipment["gps_ping_count"], 2)
        self.assertEqual(len(shipment["gps_path"]), 2)
        self.assertEqual(shipment["marker"]["source"], "gps")

        scheduled_shipment = next(
            shipment for shipment in payload["shipments"] if shipment["shipment_ref"] == "TMS-DEMO-002"
        )
        self.assertEqual(scheduled_shipment["health_key"], "on_time")
        self.assertFalse(scheduled_shipment["has_live_data"])


if __name__ == "__main__":
    unittest.main()
