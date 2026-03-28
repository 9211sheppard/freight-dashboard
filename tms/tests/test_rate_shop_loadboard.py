import html
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask

from tms import public as public_blueprint
from tms import tms as tms_blueprint
import tms.tms_db as tms_db


REPO_ROOT = Path(__file__).resolve().parents[2]


class RateShopLoadboardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_tms_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tms_test.db")

        self.app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        self.app.secret_key = "test-secret"
        self.app.config["TESTING"] = True

        @self.app.route("/logout")
        def logout():
            return "logout"

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return f"tracking:{ref}"

        self.app.register_blueprint(tms_blueprint)
        self.app.register_blueprint(public_blueprint)
        self.client = self.app.test_client()

        with self.app.app_context():
            tms_db.init_tms_db()
            self.loadboard_ref = "SHIP-LOAD-001"
            self.hidden_ref = "SHIP-HIDDEN-001"
            self._seed_data()

    def tearDown(self):
        tms_db.TMS_DB = self.original_tms_db
        self.tempdir.cleanup()

    def _seed_data(self):
        conn = tms_db.get_db()
        try:
            conn.execute(
                """
                INSERT INTO contract_rates
                    (origin, destination, mode, rate_20ft, rate_40ft, rate_40hc, currency, valid_from, valid_to, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'USD', ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    "Chicago, IL",
                    "Houston, TX",
                    "FTL",
                    3200.0,
                    3300.0,
                    3400.0,
                    "2026-03-01",
                    "2026-04-30",
                ),
            )
            conn.execute(
                """
                INSERT INTO shipments
                    (shipment_ref, status, shipper_name, consignee_name, carrier_name, origin_port, destination_port,
                     mode, etd, eta, containers, weight_kg, freight_rate, currency, notes)
                VALUES (?, 'Delivered', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?)
                """,
                (
                    "SHIP-HISTORY-001",
                    "North Dock Foods",
                    "Metro Texas Stores",
                    "BluePeak Logistics",
                    "Chicago, IL",
                    "Houston, TX",
                    "FTL",
                    date_for_offset(-10),
                    date_for_offset(-7),
                    "53' Dry Van",
                    11800.0,
                    3425.0,
                    "Historical market benchmark shipment",
                ),
            )
            conn.execute(
                """
                INSERT INTO shipments
                    (shipment_ref, status, shipper_name, consignee_name, origin_port, destination_port,
                     mode, etd, eta, containers, weight_kg, freight_rate, currency, notes)
                VALUES (?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?)
                """,
                (
                    self.loadboard_ref,
                    "Fresh Cart Foods",
                    "Gulf Retail Hub",
                    "Chicago, IL",
                    "Houston, TX",
                    "FTL",
                    date_for_offset(2),
                    date_for_offset(4),
                    "53' Dry Van",
                    12600.0,
                    3600.0,
                    "Public load board shipment",
                ),
            )
            conn.execute(
                """
                INSERT INTO shipments
                    (shipment_ref, status, shipper_name, consignee_name, carrier_name, origin_port, destination_port,
                     mode, etd, eta, containers, weight_kg, freight_rate, currency, notes)
                VALUES (?, 'Booked', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?)
                """,
                (
                    self.hidden_ref,
                    "Assigned Foods",
                    "Texas Receiver",
                    "Assigned Carrier",
                    "Chicago, IL",
                    "Houston, TX",
                    "FTL",
                    date_for_offset(3),
                    date_for_offset(5),
                    "53' Reefer",
                    9000.0,
                    3900.0,
                    "Already assigned and should not post",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def test_rate_shop_builds_results_and_prefills_new_shipment(self):
        response = self.client.get(
            "/tms/rates/shop?origin=Chicago,%20IL&destination=Houston,%20TX&mode=FTL&weight=12600&equipment_type=53%27%20Dry%20Van&date=2026-03-26"
        )
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Contract benchmark", page)
        self.assertIn("Market average", page)
        self.assertIn("Use This Rate", page)

        prefill_match = re.search(r'href="([^"]*/tms/shipments/new\?[^"]+)"', page)
        self.assertIsNotNone(prefill_match)

        prefill_url = html.unescape(prefill_match.group(1))
        prefill_response = self.client.get(prefill_url)
        self.assertEqual(prefill_response.status_code, 200)
        self.assertIn(b"Prefilled from", prefill_response.data)
        self.assertIn(b'value="Chicago, IL"', prefill_response.data)
        self.assertIn(b'value="Houston, TX"', prefill_response.data)
        self.assertIn(b'value="FTL"', prefill_response.data)

    def test_loadboard_lists_available_loads_and_interest_creates_tender(self):
        dispatcher_board = self.client.get("/tms/loadboard")
        self.assertEqual(dispatcher_board.status_code, 200)
        self.assertIn(self.loadboard_ref.encode(), dispatcher_board.data)
        self.assertNotIn(self.hidden_ref.encode(), dispatcher_board.data)

        public_board = self.client.get("/loadboard")
        self.assertEqual(public_board.status_code, 200)
        self.assertIn(self.loadboard_ref.encode(), public_board.data)

        with tms_db.get_db() as conn:
            post = conn.execute(
                "SELECT status, views FROM loadboard_posts WHERE shipment_ref = ?",
                (self.loadboard_ref,),
            ).fetchone()
            self.assertIsNotNone(post)
            self.assertEqual(post["status"], "Active")
            self.assertGreaterEqual(post["views"], 1)

        interest_response = self.client.post(
            "/loadboard/interest",
            data={
                "shipment_ref": self.loadboard_ref,
                "carrier_name": "Atlas Freight",
                "contact_email": "ops@atlas.test",
                "contact_phone": "+1-555-0101",
                "country": "United States",
                "next": "/loadboard",
            },
            follow_redirects=False,
        )
        self.assertEqual(interest_response.status_code, 302)
        self.assertIn("/tms/tender/", interest_response.location)

        with tms_db.get_db() as conn:
            carrier = conn.execute(
                "SELECT id FROM tms_carriers WHERE LOWER(name) = LOWER('Atlas Freight')"
            ).fetchone()
            self.assertIsNotNone(carrier)

            tender = conn.execute(
                """
                SELECT t.id
                FROM tenders t
                JOIN shipments s ON s.id = t.shipment_id
                WHERE s.shipment_ref = ?
                """,
                (self.loadboard_ref,),
            ).fetchone()
            self.assertIsNotNone(tender)

            response_row = conn.execute(
                "SELECT token, carrier_id FROM tender_responses WHERE tender_id = ?",
                (tender["id"],),
            ).fetchone()
            self.assertIsNotNone(response_row)
            self.assertEqual(response_row["carrier_id"], carrier["id"])

        tender_response_page = self.client.get(interest_response.location)
        self.assertEqual(tender_response_page.status_code, 200)
        self.assertIn(self.loadboard_ref.encode(), tender_response_page.data)


def date_for_offset(days):
    return (datetime.now().date() + timedelta(days=days)).isoformat()


if __name__ == "__main__":
    unittest.main()
