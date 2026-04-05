import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask

from tms import tms as tms_blueprint
import tms.tms_db as tms_db


REPO_ROOT = Path(__file__).resolve().parents[2]


class TenderWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
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
        self.client = self.app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

        with self.app.app_context():
            tms_db.init_tms_db()
            self.shipment_ref = "SHIP-TENDER-001"
            self.shipment_id, self.carrier_ids = self._seed_data()

    def tearDown(self):
        tms_db.TMS_DB = self.original_tms_db
        self.tempdir.cleanup()

    def _seed_data(self):
        conn = tms_db.get_db()
        try:
            carrier_ids = []
            for name in ("Atlas Freight", "Beacon Logistics", "Cinder Transport"):
                cursor = conn.execute(
                    """
                    INSERT INTO tms_carriers (name, active, updated_at)
                    VALUES (?, 1, CURRENT_TIMESTAMP)
                    """,
                    (name,),
                )
                carrier_ids.append(cursor.lastrowid)

            cursor = conn.execute(
                """
                INSERT INTO shipments
                    (shipment_ref, status, shipper_name, consignee_name, carrier_name,
                     origin_port, destination_port, etd, eta, cargo_description,
                     containers, freight_rate, currency, incoterm, notes)
                VALUES (?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'USD', 'FOB', ?)
                """,
                (
                    self.shipment_ref,
                    "North Dock Foods",
                    "Prairie Stores",
                    "Legacy Carrier",
                    "Chicago, IL",
                    "Houston, TX",
                    date_for_offset(2),
                    date_for_offset(9),
                    "Frozen retail replenishment",
                    "40HC",
                    4200.00,
                    "Tender workflow test shipment",
                ),
            )
            shipment_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                (shipment_id, "Created", f"Shipment {self.shipment_ref} created"),
            )
            conn.commit()
            return shipment_id, carrier_ids
        finally:
            conn.close()

    def test_tender_workflow_end_to_end(self):
        deadline = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
        create_response = self.client.post(
            f"/tms/shipments/{self.shipment_ref}/tender",
            data={
                "carrier_ids": [str(self.carrier_ids[0]), str(self.carrier_ids[1])],
                "deadline_at": deadline.strftime("%Y-%m-%dT%H:%M"),
                "notes": "Need best spot rate and transit.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertTrue(create_response.location.endswith(f"/tms/shipments/{self.shipment_ref}"))

        conn = tms_db.get_db()
        try:
            tender = conn.execute("SELECT * FROM tenders").fetchone()
            self.assertIsNotNone(tender)
            responses = conn.execute(
                "SELECT * FROM tender_responses WHERE tender_id = ? ORDER BY carrier_id",
                (tender["id"],),
            ).fetchall()
            self.assertEqual(len(responses), 2)
            self.assertNotEqual(responses[0]["token"], responses[1]["token"])
            first_token = responses[0]["token"]
            second_token = responses[1]["token"]
        finally:
            conn.close()

        board_response = self.client.get("/tms/tenders")
        self.assertEqual(board_response.status_code, 200)
        self.assertIn(self.shipment_ref.encode(), board_response.data)
        self.assertIn(b"Atlas Freight", board_response.data)
        self.assertIn(b"Beacon Logistics", board_response.data)

        first_form = self.client.get(f"/tms/tender/{first_token}/respond")
        self.assertEqual(first_form.status_code, 200)
        self.assertIn(self.shipment_ref.encode(), first_form.data)

        submit_one = self.client.post(
            f"/tms/tender/{first_token}/respond",
            data={
                "rate_20ft": "",
                "rate_40ft": "3550",
                "rate_40hc": "3650",
                "transit_days": "6",
                "notes": "Equipment available this week.",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_one.status_code, 302)
        self.assertIn("/tms/tender/", submit_one.location)

        submit_two = self.client.post(
            f"/tms/tender/{second_token}/respond",
            data={
                "rate_20ft": "",
                "rate_40ft": "3400",
                "rate_40hc": "3500",
                "transit_days": "5",
                "notes": "Fastest service option.",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_two.status_code, 302)

        board_after_responses = self.client.get("/tms/tenders")
        self.assertEqual(board_after_responses.status_code, 200)
        self.assertIn(b"Submitted", board_after_responses.data)
        self.assertIn(b"3,500.00", board_after_responses.data)

        award_response = self.client.post(
            f"/tms/tenders/{tender['id']}/award",
            data={"response_id": str(responses[1]["id"])},
            follow_redirects=False,
        )
        self.assertEqual(award_response.status_code, 302)
        self.assertTrue(award_response.location.endswith("/tms/tenders"))

        conn = tms_db.get_db()
        try:
            shipment = conn.execute(
                "SELECT carrier_id, carrier_name, freight_rate FROM shipments WHERE id = ?",
                (self.shipment_id,),
            ).fetchone()
            updated_tender = conn.execute(
                "SELECT status, awarded_response_id FROM tenders WHERE id = ?",
                (tender["id"],),
            ).fetchone()
            winning_response = conn.execute(
                "SELECT response_status FROM tender_responses WHERE id = ?",
                (responses[1]["id"],),
            ).fetchone()
            losing_response = conn.execute(
                "SELECT response_status FROM tender_responses WHERE id = ?",
                (responses[0]["id"],),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(shipment["carrier_id"], self.carrier_ids[1])
        self.assertEqual(shipment["carrier_name"], "Beacon Logistics")
        self.assertEqual(shipment["freight_rate"], 3500.00)
        self.assertEqual(updated_tender["status"], "Awarded")
        self.assertEqual(updated_tender["awarded_response_id"], responses[1]["id"])
        self.assertEqual(winning_response["response_status"], "Awarded")
        self.assertEqual(losing_response["response_status"], "Not Awarded")

        shipment_response = self.client.get(f"/tms/shipments/{self.shipment_ref}")
        self.assertEqual(shipment_response.status_code, 200)
        self.assertIn(b"Beacon Logistics", shipment_response.data)
        self.assertIn(b"3,500.00", shipment_response.data)


def date_for_offset(days):
    return (datetime.now().date() + timedelta(days=days)).isoformat()


if __name__ == "__main__":
    unittest.main()
