import shutil
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from tms.tms_routes import tms as tms_blueprint
from tms import tms_db


class DispatchBoardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        repo_root = Path(__file__).resolve().parents[2]
        source_db = repo_root / "tms" / "tms.db"
        test_db = Path(self.tempdir.name) / "dispatch-test.db"
        shutil.copy2(source_db, test_db)
        tms_db.TMS_DB = str(test_db)
        tms_db._LOCATION_COORD_CACHE.clear()
        tms_db.init_tms_db()
        tms_db.preload_demo_data()

        app = Flask(
            __name__,
            template_folder=str(repo_root / "templates"),
            static_folder=str(repo_root / "static"),
        )
        app.secret_key = "dispatch-test-secret"

        @app.context_processor
        def inject_test_globals():
            return {"csrf_token": lambda: "dispatch-test-token"}

        app.register_blueprint(tms_blueprint)

        @app.route("/track/<ref>")
        def public_tracking(ref):
            return f"tracking:{ref}"

        @app.route("/logout")
        def logout():
            return "ok"

        self.app = app
        self.client = app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

        conn = tms_db.get_db()
        try:
            conn.execute(
                "UPDATE shipments SET mode = 'FTL' WHERE shipment_ref = 'TMS-DEMO-001'"
            )
            conn.execute(
                "UPDATE shipments SET mode = 'LTL' WHERE shipment_ref = 'TMS-DEMO-003'"
            )
            conn.execute(
                "UPDATE shipments SET mode = 'FTL' WHERE shipment_ref = 'TMS-DEMO-005'"
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        tms_db.TMS_DB = self.original_db
        tms_db._LOCATION_COORD_CACHE.clear()
        tms_db.close_open_connections()
        self.client = None
        self.app = None
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def _shipment_row(self, shipment_ref):
        conn = tms_db.get_db()
        try:
            return conn.execute(
                "SELECT shipment_ref, status, carrier_id, carrier_name FROM shipments WHERE shipment_ref = ?",
                (shipment_ref,),
            ).fetchone()
        finally:
            conn.close()

    def _carrier_id(self, carrier_name):
        conn = tms_db.get_db()
        try:
            row = conn.execute(
                "SELECT id FROM tms_carriers WHERE name = ?",
                (carrier_name,),
            ).fetchone()
            return row["id"]
        finally:
            conn.close()

    def test_dispatch_board_renders_filters_and_columns(self):
        response = self.client.get("/tms/dispatch")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dispatch Board", response.data)
        self.assertIn(b"Unassigned", response.data)
        self.assertIn(b"Tendered", response.data)
        self.assertIn(b"Confirmed", response.data)
        self.assertIn(b"In Transit", response.data)
        self.assertIn(b"Delivered", response.data)
        self.assertIn(b"TMS-DEMO-005", response.data)

        filtered = self.client.get("/tms/dispatch?mode=LTL")
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b"TMS-DEMO-003", filtered.data)
        self.assertNotIn(b"TMS-DEMO-001", filtered.data)

    def test_dispatch_board_updates_carrier_and_status(self):
        carrier_id = self._carrier_id("NorthStar Freight")

        carrier_response = self.client.post(
            "/tms/shipments/TMS-DEMO-005/carrier",
            json={"carrier_id": carrier_id},
        )
        self.assertEqual(carrier_response.status_code, 200)
        self.assertTrue(carrier_response.get_json()["ok"])

        shipment = self._shipment_row("TMS-DEMO-005")
        self.assertEqual(shipment["carrier_id"], carrier_id)
        self.assertEqual(shipment["carrier_name"], "NorthStar Freight")

        status_response = self.client.post(
            "/tms/shipments/TMS-DEMO-005/status",
            json={"status": "Booked"},
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.get_json()["ok"])

        updated = self._shipment_row("TMS-DEMO-005")
        self.assertEqual(updated["status"], "Booked")


if __name__ == "__main__":
    unittest.main()
