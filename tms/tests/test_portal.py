import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask

from tms import portal, tms
from tms import tms_db


class PortalBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        self.test_db_path = str(Path(self.tempdir.name) / "portal-test.db")
        tms_db.TMS_DB = self.test_db_path
        tms_db.init_tms_db()

        root_dir = Path(__file__).resolve().parents[2]
        self.app = Flask(
            __name__,
            static_folder=str(root_dir / "static"),
            template_folder=str(root_dir / "templates"),
        )
        self.app.secret_key = "portal-test-secret"
        self.app.register_blueprint(tms)
        self.app.register_blueprint(portal)

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return f"tracking:{ref}"

        self.client = self.app.test_client()
        self.primary_ref = "TMS-PORTAL-001"
        self.hidden_ref = "TMS-OTHER-002"

        conn = tms_db.get_db()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO tms_settings (key, value)
                VALUES
                    ('company_name', 'Northwind Logistics'),
                    ('primary_color', '#1c7c54'),
                    ('setup_complete', '1')
                """
            )

            primary_cursor = conn.execute(
                """
                INSERT INTO shipments
                (
                    shipment_ref, status, shipper_name, shipper_address, consignee_name, consignee_address,
                    origin_port, destination_port, mode, etd, eta, cargo_description, containers,
                    weight_kg, volume_cbm, freight_rate, currency, incoterm, notes
                )
                VALUES (?, 'In Transit', 'Acme Foods', 'Chicago, IL', 'Retail Hub', 'Dallas, TX',
                        'Chicago, IL', 'Dallas, TX', 'FTL', '2026-03-24', '2026-03-28',
                        'Dry groceries', '53 Dry Van', 12000, 35, 2450, 'USD', 'DAP', 'Priority delivery')
                """,
                (self.primary_ref,),
            )
            primary_id = primary_cursor.lastrowid
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description, location)
                VALUES (?, 'Loaded', 'Trailer departed origin facility.', 'Chicago, IL')
                """,
                (primary_id,),
            )

            hidden_cursor = conn.execute(
                """
                INSERT INTO shipments
                (
                    shipment_ref, status, shipper_name, consignee_name, origin_port, destination_port,
                    mode, etd, eta, cargo_description, containers, weight_kg, volume_cbm, freight_rate, currency
                )
                VALUES (?, 'Delivered', 'Other Customer', 'Hidden Receiver', 'Toronto, ON', 'Atlanta, GA',
                        'LTL', '2026-03-20', '2026-03-22', 'Medical goods', 'Pallets', 4800, 14, 1800, 'USD')
                """,
                (self.hidden_ref,),
            )
            hidden_id = hidden_cursor.lastrowid
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description, location)
                VALUES (?, 'Delivered', 'Delivered to consignee.', 'Atlanta, GA')
                """,
                (hidden_id,),
            )
            conn.commit()
        finally:
            conn.close()

        tms_db.save_portal_token(
            token="ACME-123456",
            customer_name="Acme Foods",
            email="ops@acme.test",
            shipment_refs=[self.primary_ref],
        )
        tms_db.save_portal_token(
            token="OTHER-654321",
            customer_name="Other Customer",
            email="ops@other.test",
            shipment_refs=[self.hidden_ref],
        )

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        self.tempdir.cleanup()

    def test_portal_login_and_dashboard_filter_shipments(self):
        response = self.client.get("/portal/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Northwind Logistics", response.data)

        login_response = self.client.post(
            "/portal/login",
            data={"access_code": "123456"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertTrue(login_response.location.endswith("/portal/ACME-123456/"))

        dashboard_response = self.client.get("/portal/ACME-123456/")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(self.primary_ref.encode("utf-8"), dashboard_response.data)
        self.assertNotIn(self.hidden_ref.encode("utf-8"), dashboard_response.data)
        self.assertIn(b"Acme Foods", dashboard_response.data)

    def test_portal_request_submission_and_document_downloads(self):
        submit_response = self.client.post(
            "/portal/ACME-123456/",
            data={
                "shipper_name": "Acme Foods",
                "consignee_name": "Expansion Warehouse",
                "origin_port": "Chicago, IL",
                "destination_port": "Phoenix, AZ",
                "mode": "FTL",
                "etd": "2026-03-30",
                "eta": "2026-04-02",
                "cargo_description": "Seasonal stock",
                "containers": "53 Dry Van",
                "weight_kg": "9800",
                "volume_cbm": "28",
                "currency": "USD",
                "incoterm": "DAP",
                "notes": "Gate appointment after 09:00",
                "selected_ref": self.primary_ref,
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/portal/ACME-123456/?ref=", submit_response.location)
        new_ref = submit_response.location.rsplit("=", 1)[-1]
        redirected_path = urlsplit(submit_response.location).path
        redirected_query = urlsplit(submit_response.location).query

        dashboard_response = self.client.get(f"{redirected_path}?{redirected_query}")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(new_ref.encode("utf-8"), dashboard_response.data)
        self.assertIn(b"Shipment request", dashboard_response.data)

        portal_token = tms_db.get_portal_token("ACME-123456")
        self.assertIn(new_ref, portal_token["shipment_refs"])

        for path_fragment in ("bol.pdf", "invoice.pdf", "packing-list.pdf"):
            download_response = self.client.get(
                f"/portal/ACME-123456/shipments/{self.primary_ref}/{path_fragment}"
            )
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.mimetype, "application/pdf")
            self.assertTrue(download_response.data.startswith(b"%PDF-"))

        unauthorized_download = self.client.get(
            f"/portal/ACME-123456/shipments/{self.hidden_ref}/bol.pdf"
        )
        self.assertEqual(unauthorized_download.status_code, 404)


if __name__ == "__main__":
    unittest.main()
