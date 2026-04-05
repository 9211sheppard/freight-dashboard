import io
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from tms import tms as tms_blueprint
import tms.tms_db as tms_db


REPO_ROOT = Path(__file__).resolve().parents[2]


class ClaimWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_tms_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "claims-test.db")

        self.app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        self.app.secret_key = "claim-test-secret"
        self.app.config["TESTING"] = True
        self.app.config["TMS_CLAIMS_UPLOAD_DIR"] = str(Path(self.tempdir.name) / "claim_uploads")
        self.app.jinja_env.globals["csrf_token"] = lambda: ""

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
            self.shipment_ref = "SHIP-CLAIM-001"
            self.carrier_id = self._seed_data()

    def tearDown(self):
        tms_db.TMS_DB = self.original_tms_db
        self.tempdir.cleanup()

    def _seed_data(self):
        conn = tms_db.get_db()
        try:
            carrier_cursor = conn.execute(
                """
                INSERT INTO tms_carriers (name, scac, active, updated_at)
                VALUES ('Atlas Freight', 'ATLS', 1, CURRENT_TIMESTAMP)
                """
            )
            carrier_id = carrier_cursor.lastrowid
            shipment_cursor = conn.execute(
                """
                INSERT INTO shipments
                    (shipment_ref, status, customer_name, shipper_name, consignee_name,
                     carrier_name, carrier_id, origin_port, destination_port, mode,
                     etd, eta, cargo_description, containers, freight_rate, currency, notes)
                VALUES (?, 'Delivered', 'North Dock Foods', 'North Dock Foods', 'Prairie Stores',
                        'Atlas Freight', ?, 'Chicago, IL', 'Houston, TX', 'FTL',
                        '2026-03-20', '2026-03-24', 'Frozen retail replenishment',
                        '53 Reefer', 4200.00, 'USD', 'Claim workflow test shipment')
                """,
                (self.shipment_ref, carrier_id),
            )
            conn.execute(
                "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                (shipment_cursor.lastrowid, "Delivered", f"Shipment {self.shipment_ref} delivered."),
            )
            conn.commit()
            return carrier_id
        finally:
            conn.close()

    def test_claim_lifecycle_end_to_end(self):
        create_response = self.client.post(
            "/tms/claims/new",
            data={
                "shipment_ref": self.shipment_ref,
                "claim_type": "Damage",
                "description": "Two pallets arrived crushed with visible water exposure.",
                "claimed_amount": "1250.00",
                "currency": "USD",
                "evidence": (io.BytesIO(b"\x89PNG\r\n\x1a\nclaim"), "damage.png", "image/png"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertIn("/tms/claims?claim_id=", create_response.location)

        conn = tms_db.get_db()
        try:
            claim = conn.execute("SELECT * FROM freight_claims").fetchone()
            self.assertIsNotNone(claim)
            self.assertEqual(claim["shipment_ref"], self.shipment_ref)
            self.assertEqual(claim["carrier_id"], self.carrier_id)
            self.assertEqual(claim["status"], "Filed")
            self.assertEqual(claim["claim_type"], "Damage")
            self.assertTrue(claim["response_token"])
            self.assertTrue(claim["evidence_path"])
            claim_id = claim["id"]
            response_token = claim["response_token"]
            evidence_path = Path(self.app.config["TMS_CLAIMS_UPLOAD_DIR"]) / claim["evidence_path"]
        finally:
            conn.close()

        self.assertTrue(evidence_path.exists())

        board_response = self.client.get(
            f"/tms/claims?status=Filed&carrier_id={self.carrier_id}&claim_type=Damage&claim_id={claim_id}"
        )
        self.assertEqual(board_response.status_code, 200)
        self.assertIn(self.shipment_ref.encode(), board_response.data)
        self.assertIn(b"Damage", board_response.data)

        response_form = self.client.get(f"/tms/claims/{claim_id}/respond/{response_token}")
        self.assertEqual(response_form.status_code, 200)
        self.assertIn(self.shipment_ref.encode(), response_form.data)

        carrier_submit = self.client.post(
            f"/tms/claims/{claim_id}/respond/{response_token}",
            data={
                "carrier_notes": "Pallets were received with torn wrap; carrier proposes partial settlement.",
                "counter_offer": "950.00",
            },
            follow_redirects=False,
        )
        self.assertEqual(carrier_submit.status_code, 302)
        self.assertIn(f"/tms/claims/{claim_id}/respond/{response_token}?submitted=1", carrier_submit.location)

        conn = tms_db.get_db()
        try:
            claim_after_response = conn.execute(
                "SELECT status, carrier_notes, counter_offer FROM freight_claims WHERE id = ?",
                (claim_id,),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(claim_after_response["status"], "Under Review")
        self.assertIn("partial settlement", claim_after_response["carrier_notes"])
        self.assertEqual(claim_after_response["counter_offer"], 950.00)

        approve_response = self.client.post(
            f"/tms/claims/{claim_id}/status",
            data={"status": "Approved", "settlement_amount": "1000.00"},
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)
        self.assertTrue(approve_response.location.endswith(f"/tms/claims?claim_id={claim_id}"))

        paid_response = self.client.post(
            f"/tms/claims/{claim_id}/status",
            data={"status": "Paid", "settlement_amount": "1000.00"},
            follow_redirects=False,
        )
        self.assertEqual(paid_response.status_code, 302)

        conn = tms_db.get_db()
        try:
            final_claim = conn.execute(
                """
                SELECT status, settlement_amount, settled_at
                FROM freight_claims
                WHERE id = ?
                """,
                (claim_id,),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(final_claim["status"], "Paid")
        self.assertEqual(final_claim["settlement_amount"], 1000.00)
        self.assertTrue(final_claim["settled_at"])

        shipment_response = self.client.get(f"/tms/shipments/{self.shipment_ref}")
        self.assertEqual(shipment_response.status_code, 200)
        self.assertIn(b"Freight Claims", shipment_response.data)
        self.assertIn(b"Paid", shipment_response.data)
        self.assertIn(b"1,000.00", shipment_response.data)


if __name__ == "__main__":
    unittest.main()
