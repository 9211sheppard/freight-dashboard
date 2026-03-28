import io
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from tms import tms_db
from tms.tms_routes import tms as tms_blueprint


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ContractRateTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tms.db")
        tms_db.init_tms_db()

        self.app = Flask(
            __name__,
            template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"),
        )
        self.app.secret_key = "test-secret"

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return ref

        @self.app.route("/logout")
        def logout():
            return "ok"

        self.app.register_blueprint(tms_blueprint)
        self.client = self.app.test_client()

    def tearDown(self):
        tms_db.TMS_DB = self.original_db
        self.tempdir.cleanup()

    def test_manual_contract_rate_crud_flow(self):
        create_response = self.client.post(
            "/tms/rates",
            data={
                "origin": "Shanghai",
                "destination": "Los Angeles",
                "mode": "Ocean",
                "rate_20ft": "1800",
                "rate_40ft": "2800",
                "rate_40hc": "2900",
                "currency": "USD",
                "valid_from": "2026-03-01",
                "valid_to": "2026-04-30",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with tms_db.get_db() as conn:
            row = conn.execute("SELECT * FROM contract_rates").fetchone()
            self.assertIsNotNone(row)
            rate_id = row["id"]
            self.assertEqual(row["origin"], "Shanghai")

        update_response = self.client.post(
            "/tms/rates",
            data={
                "rate_id": str(rate_id),
                "origin": "Shanghai",
                "destination": "Los Angeles",
                "mode": "Ocean",
                "rate_20ft": "1750",
                "rate_40ft": "2750",
                "rate_40hc": "2850",
                "currency": "USD",
                "valid_from": "2026-03-01",
                "valid_to": "2026-04-15",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        page_response = self.client.get(f"/tms/rates?rate_id={rate_id}")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn(b"Edit Contract", page_response.data)
        self.assertIn(b"Los Angeles", page_response.data)

        delete_response = self.client.post(f"/tms/rates/{rate_id}/delete", follow_redirects=False)
        self.assertEqual(delete_response.status_code, 302)
        with tms_db.get_db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM contract_rates").fetchone()[0]
        self.assertEqual(count, 0)

    def test_upload_lookup_and_auto_rate_new_shipment(self):
        csv_payload = """origin,destination,mode,rate_20ft,rate_40ft,rate_40hc,currency,valid_from,valid_to
Shanghai,Los Angeles,Ocean,1800,2800,2900,USD,2026-03-01,2026-04-30
Shanghai,Los Angeles,Ocean,1750,2750,2850,USD,2026-03-01,2026-04-15
"""
        upload_response = self.client.post(
            "/tms/rates/upload",
            data={"tariff_file": (io.BytesIO(csv_payload.encode("utf-8")), "tariff.csv")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(upload_response.status_code, 302)

        lookup_response = self.client.get(
            "/tms/rates/lookup?origin=Shanghai&destination=Los%20Angeles&mode=Ocean&containers=1x40HC&date=2026-03-20"
        )
        self.assertEqual(lookup_response.status_code, 200)
        lookup_data = lookup_response.get_json()
        self.assertTrue(lookup_data["ok"])
        self.assertEqual(lookup_data["rate"], 2850.0)
        self.assertEqual(lookup_data["rate_field"], "rate_40hc")

        create_response = self.client.post(
            "/tms/shipments/new",
            data={
                "status": "Draft",
                "shipper_name": "Importer One",
                "shipper_address": "Shanghai",
                "consignee_name": "Retail DC",
                "consignee_address": "Los Angeles",
                "carrier_name": "",
                "origin_port": "Shanghai",
                "destination_port": "Los Angeles",
                "mode": "Ocean",
                "etd": "2026-03-20",
                "eta": "2026-04-10",
                "cargo_description": "Consumer goods",
                "containers": "1x40HC",
                "weight_kg": "12000",
                "volume_cbm": "52",
                "freight_rate": "9999",
                "currency": "EUR",
                "incoterm": "FOB",
                "notes": "Auto-rate me",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        shipment_ref = create_response.headers["Location"].rstrip("/").split("/")[-1]

        with tms_db.get_db() as conn:
            shipment = conn.execute(
                "SELECT * FROM shipments WHERE shipment_ref = ?",
                (shipment_ref,),
            ).fetchone()
            self.assertIsNotNone(shipment)
            self.assertEqual(shipment["mode"], "Ocean")
            self.assertEqual(shipment["freight_rate"], 2850.0)
            self.assertEqual(shipment["currency"], "USD")
            self.assertIsNotNone(shipment["contract_rate_id"])

        shipment_page = self.client.get(f"/tms/shipments/{shipment_ref}")
        self.assertEqual(shipment_page.status_code, 200)
        self.assertIn(b"APPLIED CONTRACT MATCH", shipment_page.data)
        self.assertIn(b"40HC", shipment_page.data)


if __name__ == "__main__":
    unittest.main()
