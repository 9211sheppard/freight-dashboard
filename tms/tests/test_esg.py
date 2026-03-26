import csv
import io
import math
import tempfile
import unittest
from pathlib import Path

from flask import Flask

import tms.tms_db as tms_db
from tms.tms_routes import tms as tms_blueprint


REPO_ROOT = Path(__file__).resolve().parents[2]


def _haversine_km(coord_a, coord_b):
    lat1, lon1 = coord_a
    lat2, lon2 = coord_b
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


class TmsEsgTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "esg-test.db")
        tms_db._LOCATION_COORD_CACHE.clear()
        tms_db.init_tms_db()

        app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        app.secret_key = "esg-test-secret"
        app.register_blueprint(tms_blueprint)

        @app.route("/logout")
        def logout():
            return "ok"

        self.app = app
        self.client = app.test_client()

    def tearDown(self):
        tms_db.TMS_DB = self.original_db
        tms_db._LOCATION_COORD_CACHE.clear()
        self.tempdir.cleanup()

    def _db(self):
        return tms_db.get_db()

    def test_new_shipment_save_persists_co2_kg(self):
        response = self.client.post(
            "/tms/shipments/new",
            data={
                "status": "Booked",
                "shipper_name": "Lakefront Foods",
                "shipper_address": "Chicago, IL",
                "consignee_name": "Metro Grocers",
                "consignee_address": "Dallas, TX",
                "origin_port": "Chicago, IL",
                "destination_port": "Dallas, TX",
                "mode": "FTL",
                "etd": "2026-03-26",
                "eta": "2026-03-28",
                "cargo_description": "Frozen goods",
                "containers": "53' Reefer",
                "weight_kg": "12000",
                "volume_cbm": "41",
                "freight_rate": "3200",
                "currency": "USD",
                "incoterm": "DAP",
                "notes": "Priority delivery",
                "carrier_id": "",
                "driver_id": "",
                "vehicle_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        conn = self._db()
        try:
            shipment = conn.execute(
                "SELECT * FROM shipments ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(shipment)
        self.assertIsNotNone(shipment["co2_kg"])

        expected_distance = _haversine_km(
            tms_db.KNOWN_LOCATION_COORDINATES["chicago, il"],
            tms_db.KNOWN_LOCATION_COORDINATES["dallas, tx"],
        )
        expected_co2 = round(expected_distance * 12 * 0.096, 2)
        self.assertAlmostEqual(shipment["co2_kg"], expected_co2, places=2)

    def test_esg_dashboard_renders_charts_and_framework_labels(self):
        tms_db.preload_demo_data()

        response = self.client.get("/tms/esg")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ESG Dashboard", response.data)
        self.assertIn(b"ISO 14083 / GLEC estimate", response.data)
        self.assertIn(b"co2ByModeChart", response.data)
        self.assertIn(b"co2TrendChart", response.data)
        self.assertIn(b"Export CSV", response.data)

    def test_esg_export_contains_per_shipment_carbon_data(self):
        tms_db.preload_demo_data()

        response = self.client.get("/tms/esg/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.headers.get("Content-Type", ""))

        rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8"))))
        self.assertGreaterEqual(len(rows), 1)

        demo_row = next(row for row in rows if row["shipment_ref"] == "TMS-DEMO-001")
        self.assertEqual(demo_row["framework_label"], tms_db.CARBON_FRAMEWORK_LABEL)
        self.assertEqual(demo_row["esg_mode"], "Road")
        self.assertNotEqual(demo_row["co2_kg"], "")
        self.assertNotEqual(demo_row["origin_source_url"], "")
        self.assertNotEqual(demo_row["destination_source_url"], "")


if __name__ == "__main__":
    unittest.main()
