import sys
import tempfile
import unittest
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tms.tms_db as tms_db
import tms.tms_routes as tms_routes


class FreightAuditModuleTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "freight-audit-test.db")
        tms_db.init_tms_db()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "freight-audit-secret"

        @self.app.route("/logout")
        def logout():
            return "", 204

        self.app.add_url_rule(
            "/tms/freight-audit",
            endpoint="tms.freight_audit_page",
            view_func=tms_routes.freight_audit_page,
            methods=["GET"],
        )
        self.app.add_url_rule(
            "/tms/freight-audit/run",
            endpoint="tms.freight_audit_run",
            view_func=tms_routes.freight_audit_run,
            methods=["POST"],
        )
        self.app.add_url_rule(
            "/tms/freight-audit/approve/<int:id>",
            endpoint="tms.freight_audit_approve",
            view_func=tms_routes.freight_audit_approve,
            methods=["POST"],
        )
        self.app.add_url_rule(
            "/tms/freight-audit/dispute/<int:id>",
            endpoint="tms.freight_audit_dispute",
            view_func=tms_routes.freight_audit_dispute,
            methods=["POST"],
        )
        self.client = self.app.test_client()

        conn = tms_db.get_db()
        conn.execute(
            """
            INSERT INTO shipments
                (shipment_ref, status, customer_name, carrier_name, origin_port, destination_port,
                 mode, weight_kg, freight_rate, currency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TMS-FA-001",
                "Active",
                "Audit Customer",
                "NorthStar Freight",
                "Chicago, IL",
                "Dallas, TX",
                "LTL",
                453.592,
                480.00,
                "USD",
            ),
        )
        conn.execute(
            """
            INSERT INTO carrier_invoices
                (shipment_ref, carrier_name, invoice_no, amount, currency, status, variance_pct, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TMS-FA-001",
                "NorthStar Freight",
                "AP-1001",
                512.25,
                "USD",
                "Pending",
                0.0,
                "",
            ),
        )
        conn.execute(
            """
            CREATE TABLE tms_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_ref TEXT NOT NULL,
                rate REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO tms_rates (shipment_ref, rate) VALUES (?, ?)",
            ("TMS-FA-001", 0.5),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        self.tempdir.cleanup()

    def test_run_route_creates_pending_discrepancy_item(self):
        response = self.client.post("/tms/freight-audit/run", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Audit complete", response.data)
        self.assertIn(b"AP-1001", response.data)

        conn = tms_db.get_db()
        try:
            item = conn.execute(
                "SELECT * FROM freight_audit_items WHERE invoice_id = 1"
            ).fetchone()
            self.assertIsNotNone(item)
            self.assertEqual(item["status"], "pending")
            self.assertAlmostEqual(item["expected_amount"], 500.00)
            self.assertAlmostEqual(item["discrepancy"], 12.25)
        finally:
            conn.close()

    def test_dispute_route_updates_status_and_notes(self):
        self.client.post("/tms/freight-audit/run", follow_redirects=False)

        response = self.client.post(
            "/tms/freight-audit/dispute/1",
            data={"notes": "Carrier accessorial needs backup"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        conn = tms_db.get_db()
        try:
            item = conn.execute(
                "SELECT * FROM freight_audit_items WHERE id = 1"
            ).fetchone()
            self.assertEqual(item["status"], "disputed")
            self.assertEqual(item["notes"], "Carrier accessorial needs backup")
        finally:
            conn.close()

    def test_rerun_updates_existing_item_instead_of_creating_duplicate(self):
        self.client.post("/tms/freight-audit/run", follow_redirects=False)

        conn = tms_db.get_db()
        conn.execute(
            "UPDATE carrier_invoices SET amount = ? WHERE id = ?",
            (500.00, 1),
        )
        conn.commit()
        conn.close()

        response = self.client.post("/tms/freight-audit/run", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        conn = tms_db.get_db()
        try:
            items = conn.execute("SELECT * FROM freight_audit_items").fetchall()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["status"], "resolved")
            self.assertAlmostEqual(items[0]["discrepancy"], 0.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
