import tempfile
import unittest
from unittest import mock
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
        self.primary_token = "ACME-DEMO-TOKEN"
        self.hidden_token = "OTHER-DEMO-TOKEN"
        self.primary_pin = tms_db._portal_pin_for_token(self.primary_token)

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
            token=self.primary_token,
            customer_name="Acme Foods",
            email="ops@acme.test",
            shipment_refs=[self.primary_ref],
        )
        tms_db.save_portal_token(
            token=self.hidden_token,
            customer_name="Other Customer",
            email="ops@other.test",
            shipment_refs=[self.hidden_ref],
        )

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        tms_db.close_open_connections()
        self.client = None
        self.app = None
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_portal_login_and_dashboard_filter_shipments(self):
        response = self.client.get("/portal/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Northwind Logistics", response.data)

        with mock.patch("tms.tms_routes.is_ip_locked", return_value=False):
            login_response = self.client.post(
                "/portal/login",
                data={"access_code": self.primary_pin},
                follow_redirects=False,
            )
        self.assertEqual(login_response.status_code, 302)
        self.assertTrue(login_response.location.endswith(f"/portal/{self.primary_token}/"))

        dashboard_response = self.client.get(f"/portal/{self.primary_token}/")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(self.primary_ref.encode("utf-8"), dashboard_response.data)
        self.assertNotIn(self.hidden_ref.encode("utf-8"), dashboard_response.data)
        self.assertIn(b"Acme Foods", dashboard_response.data)
        self.assertIn(f'/track/{self.primary_ref}?token='.encode("utf-8"), dashboard_response.data)

    def test_portal_login_locks_after_bruteforce_threshold(self):
        with mock.patch("tms.tms_routes.is_ip_locked", side_effect=[False, True]), mock.patch(
            "tms.tms_routes.record_login_attempt"
        ) as record_attempt:
            failed = self.client.post(
                "/portal/login",
                data={"access_code": "000000"},
                follow_redirects=False,
            )
            self.assertEqual(failed.status_code, 401)
            self.assertIn(b"Enter a valid portal token or 6-digit PIN.", failed.data)
            record_attempt.assert_called_once_with("127.0.0.1", "000000", False)

            locked = self.client.post(
                "/portal/login",
                data={"access_code": "000000"},
                follow_redirects=False,
            )
            self.assertEqual(locked.status_code, 423)
        self.assertIn(b"Too many login attempts. Try again later.", locked.data)

    def test_portal_login_rejects_expired_token(self):
        tms_db.save_portal_token(
            token="EXPIRED-999888",
            customer_name="Expired Customer",
            email="expired@example.com",
            shipment_refs=[self.primary_ref],
            expires_at="2020-01-01 00:00:00",
        )

        with mock.patch("tms.tms_routes.is_ip_locked", return_value=False):
            response = self.client.post(
                "/portal/login",
                data={"access_code": "999888"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Enter a valid portal token or 6-digit PIN.", response.data)

    def test_portal_request_submission_and_document_downloads(self):
        submit_response = self.client.post(
            f"/portal/{self.primary_token}/",
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
        self.assertIn(f"/portal/{self.primary_token}/?ref=", submit_response.location)
        new_ref = submit_response.location.rsplit("=", 1)[-1]
        redirected_path = urlsplit(submit_response.location).path
        redirected_query = urlsplit(submit_response.location).query

        dashboard_response = self.client.get(f"{redirected_path}?{redirected_query}")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(new_ref.encode("utf-8"), dashboard_response.data)
        self.assertIn(b"Shipment request", dashboard_response.data)

        portal_token = tms_db.get_portal_token(self.primary_token)
        self.assertIn(new_ref, portal_token["shipment_refs"])

        for path_fragment in ("bol.pdf", "invoice.pdf", "packing-list.pdf"):
            download_response = self.client.get(
                f"/portal/{self.primary_token}/shipments/{self.primary_ref}/{path_fragment}"
            )
            self.assertEqual(download_response.status_code, 200)
            self.assertEqual(download_response.mimetype, "application/pdf")
            self.assertTrue(download_response.data.startswith(b"%PDF-"))

        unauthorized_download = self.client.get(
            f"/portal/{self.primary_token}/shipments/{self.hidden_ref}/bol.pdf"
        )
        self.assertEqual(unauthorized_download.status_code, 404)


if __name__ == "__main__":
    unittest.main()
