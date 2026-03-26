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


class CarrierAuditTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "audit-test.db")
        tms_db.init_tms_db()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"),
        )
        self.app.secret_key = "audit-test-secret"

        @self.app.route("/logout")
        def logout():
            return "", 204

        self.app.add_url_rule(
            "/tms/audit",
            endpoint="tms.audit",
            view_func=tms_routes.audit,
            methods=["GET", "POST"],
        )
        self.client = self.app.test_client()

        conn = tms_db.get_db()
        conn.execute(
            """
            INSERT INTO shipments
                (shipment_ref, status, customer_name, carrier_name, origin_port, destination_port, freight_rate, currency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TMS-AUDIT-001",
                "Active",
                "Audit Test Customer",
                "NorthStar Freight",
                "Chicago, IL",
                "Dallas, TX",
                1000.00,
                "USD",
            ),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        tms_db.TMS_DB = self.original_db_path
        self.tempdir.cleanup()

    def test_create_invoice_matches_shipment_and_flags_variance(self):
        response = self.client.post(
            "/tms/audit",
            data={
                "action": "create",
                "carrier_name": "NorthStar Freight",
                "shipment_ref": "TMS-AUDIT-001",
                "invoice_no": "NS-1001",
                "amount": "1060.00",
                "currency": "USD",
                "notes": "Uploaded from carrier portal",
                "status_filter": "",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NS-1001", response.data)
        self.assertIn(b"Flagged", response.data)

        conn = tms_db.get_db()
        try:
            invoice = conn.execute(
                "SELECT * FROM carrier_invoices WHERE invoice_no = ?",
                ("NS-1001",),
            ).fetchone()
            self.assertIsNotNone(invoice)
            self.assertEqual(invoice["status"], "Pending")
            self.assertAlmostEqual(invoice["variance_pct"], 6.0)
        finally:
            conn.close()

    def test_status_workflow_moves_invoice_to_paid_and_keeps_notes(self):
        conn = tms_db.get_db()
        conn.execute(
            """
            INSERT INTO carrier_invoices
                (shipment_ref, carrier_name, invoice_no, amount, currency, status, variance_pct, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TMS-AUDIT-001",
                "NorthStar Freight",
                "NS-2002",
                1000.00,
                "USD",
                "Pending",
                0.0,
                "",
            ),
        )
        conn.commit()
        conn.close()

        approve_response = self.client.post(
            "/tms/audit",
            data={
                "action": "update_status",
                "invoice_id": "1",
                "status": "Approved",
                "notes": "Rate matches shipment",
                "status_filter": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

        paid_response = self.client.post(
            "/tms/audit",
            data={
                "action": "update_status",
                "invoice_id": "1",
                "status": "Paid",
                "notes": "",
                "status_filter": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(paid_response.status_code, 302)

        conn = tms_db.get_db()
        try:
            invoice = conn.execute(
                "SELECT * FROM carrier_invoices WHERE id = 1"
            ).fetchone()
            self.assertEqual(invoice["status"], "Paid")
            self.assertIn("Approved: Rate matches shipment", invoice["notes"])
        finally:
            conn.close()

    def test_status_filter_returns_only_matching_invoices(self):
        conn = tms_db.get_db()
        conn.executemany(
            """
            INSERT INTO carrier_invoices
                (shipment_ref, carrier_name, invoice_no, amount, currency, status, variance_pct, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TMS-AUDIT-001", "NorthStar Freight", "NS-3001", 1000.00, "USD", "Approved", 0.0, ""),
                ("TMS-AUDIT-001", "NorthStar Freight", "NS-3002", 1020.00, "USD", "Pending", 2.0, ""),
            ],
        )
        conn.commit()
        conn.close()

        response = self.client.get("/tms/audit?status=Approved")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"NS-3001", response.data)
        self.assertNotIn(b"NS-3002", response.data)


if __name__ == "__main__":
    unittest.main()
