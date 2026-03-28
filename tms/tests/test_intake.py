import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fitz
from flask import Flask


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tms.tms_db as tms_db
from tms.tms_routes import tms as tms_blueprint


class IntakeRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "tms-intake-test.db")
        self.db_patch = mock.patch.object(tms_db, "TMS_DB", self.db_path)
        self.db_patch.start()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "intake-test-secret"
        self.app.register_blueprint(tms_blueprint)

        @self.app.route("/logout")
        def logout():
            return "", 204

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return ref, 200

        tms_db.init_tms_db()
        self.client = self.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def _db(self):
        return tms_db.get_db()

    def _build_pdf(self, text):
        document = fitz.open()
        page = document.new_page()
        page.insert_textbox(fitz.Rect(40, 40, 555, 780), text, fontsize=12)
        pdf_bytes = document.tobytes()
        document.close()
        return pdf_bytes

    def test_email_text_intake_review_and_create_shipment(self):
        email_text = """Shipper: Lakefront Foods
Consignee: Metro Grocers
Origin: Chicago, IL
Destination: Dallas, TX
Cargo Description: Frozen grocery replenishment
Weight: 26,455 lbs
Containers: 1 x 40HC
ETD: 2026-04-02
ETA: 2026-04-06
Incoterm: DAP
Currency: USD
Rate: USD 4250
"""
        extract_response = self.client.post(
            "/tms/intake",
            data={"action": "extract", "email_text": email_text},
            follow_redirects=False,
        )
        self.assertEqual(extract_response.status_code, 302)
        self.assertIn("/tms/intake?intake_id=", extract_response.location)

        review_response = self.client.get(extract_response.location)
        self.assertEqual(review_response.status_code, 200)
        self.assertIn(b"Lakefront Foods", review_response.data)
        self.assertIn(b"Create Shipment", review_response.data)

        conn = self._db()
        try:
            intake_row = conn.execute("SELECT * FROM intake_documents WHERE id = 1").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(intake_row)
        self.assertEqual(intake_row["status"], "processed")
        self.assertGreater(intake_row["confidence"], 0)

        save_response = self.client.post(
            "/tms/intake",
            data={
                "action": "save_review",
                "intake_id": "1",
                "shipper": "Lakefront Foods",
                "consignee": "Metro Grocers",
                "origin": "Chicago, IL",
                "destination": "Dallas, TX",
                "cargo_description": "Frozen grocery replenishment",
                "weight": "26,455 lbs",
                "containers": "1 x 40HC",
                "etd": "2026-04-02",
                "eta": "2026-04-06",
                "incoterm": "DAP",
                "currency": "USD",
                "rate": "4250",
            },
            follow_redirects=False,
        )
        self.assertEqual(save_response.status_code, 302)
        self.assertTrue(save_response.location.endswith("/tms/intake?intake_id=1"))

        conn = self._db()
        try:
            saved_intake = conn.execute("SELECT * FROM intake_documents WHERE id = 1").fetchone()
        finally:
            conn.close()
        saved_payload = json.loads(saved_intake["extracted_json"])
        self.assertEqual(saved_intake["status"], "reviewed")
        self.assertEqual(saved_payload["fields"]["rate"]["value"], "4250")

        create_response = self.client.post(
            "/tms/intake",
            data={
                "action": "create_shipment",
                "intake_id": "1",
                "shipper": "Lakefront Foods",
                "consignee": "Metro Grocers",
                "origin": "Chicago, IL",
                "destination": "Dallas, TX",
                "cargo_description": "Frozen grocery replenishment",
                "weight": "26,455 lbs",
                "containers": "1 x 40HC",
                "etd": "2026-04-02",
                "eta": "2026-04-06",
                "incoterm": "DAP",
                "currency": "USD",
                "rate": "4250",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertIn("/tms/shipments/", create_response.location)

        conn = self._db()
        try:
            shipment = conn.execute("SELECT * FROM shipments ORDER BY id DESC LIMIT 1").fetchone()
            intake_row = conn.execute("SELECT * FROM intake_documents WHERE id = 1").fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(shipment)
        self.assertEqual(shipment["shipper_name"], "Lakefront Foods")
        self.assertEqual(shipment["consignee_name"], "Metro Grocers")
        self.assertEqual(shipment["origin_port"], "Chicago, IL")
        self.assertEqual(shipment["destination_port"], "Dallas, TX")
        self.assertEqual(shipment["cargo_description"], "Frozen grocery replenishment")
        self.assertEqual(shipment["containers"], "1 x 40HC")
        self.assertEqual(shipment["currency"], "USD")
        self.assertEqual(shipment["incoterm"], "DAP")
        self.assertAlmostEqual(float(shipment["weight_kg"]), 11999.79, delta=0.1)
        self.assertAlmostEqual(float(shipment["freight_rate"]), 4250.0, delta=0.1)
        self.assertEqual(intake_row["status"], "shipment_created")
        self.assertEqual(intake_row["shipment_ref"], shipment["shipment_ref"])

    def test_pdf_upload_extracts_and_logs_intake(self):
        pdf_text = """Shipper: Acme Export
Consignee: Pacific Imports
Origin: Shanghai, CN
Destination: Los Angeles, CA
Cargo Description: Apparel cartons
Weight: 12000 kg
Containers: 2 x 40HC
ETD: 2026-05-01
ETA: 2026-05-18
Incoterm: FOB
Currency: USD
Rate: USD 3800
"""
        pdf_bytes = self._build_pdf(pdf_text)

        response = self.client.post(
            "/tms/intake",
            data={
                "action": "extract",
                "document": (io.BytesIO(pdf_bytes), "order-intake.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/tms/intake?intake_id=", response.location)

        review_response = self.client.get(response.location)
        self.assertEqual(review_response.status_code, 200)
        self.assertIn(b"Acme Export", review_response.data)
        self.assertIn(b"order-intake.pdf", review_response.data)

        conn = self._db()
        try:
            intake_row = conn.execute("SELECT * FROM intake_documents WHERE id = 1").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(intake_row)
        payload = json.loads(intake_row["extracted_json"])
        self.assertEqual(payload["source_kind"], "pdf")
        self.assertEqual(payload["source_name"], "order-intake.pdf")
        self.assertEqual(payload["fields"]["shipper"]["value"], "Acme Export")
        self.assertEqual(payload["fields"]["containers"]["value"], "2 x 40HC")
        self.assertEqual(intake_row["status"], "processed")
        self.assertGreater(intake_row["confidence"], 0)


if __name__ == "__main__":
    unittest.main()
