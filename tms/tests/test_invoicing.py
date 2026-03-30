import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
import sys
import types

from flask import Flask

sys.modules.setdefault("fitz", types.ModuleType("fitz"))
sys.modules.setdefault("pdfplumber", types.ModuleType("pdfplumber"))
pil_module = sys.modules.setdefault("PIL", types.ModuleType("PIL"))
image_module = sys.modules.setdefault("PIL.Image", types.ModuleType("PIL.Image"))
image_ops_module = sys.modules.setdefault("PIL.ImageOps", types.ModuleType("PIL.ImageOps"))
pil_module.Image = image_module
pil_module.ImageOps = image_ops_module

import tms.tms_db as tms_db
from tms import tms as tms_blueprint


class TmsInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tms-test.db")
        tms_db.init_tms_db()
        tms_db.preload_demo_data()

        app = Flask(
            __name__,
            template_folder=str(Path(__file__).resolve().parents[2] / "templates"),
            static_folder=str(Path(__file__).resolve().parents[2] / "static"),
        )
        app.secret_key = "test-secret"
        app.register_blueprint(tms_blueprint)

        @app.route("/logout")
        def logout():
            return "logout"

        @app.route("/track/<ref>", endpoint="public_tracking")
        def public_tracking(ref):
            return ref

        self.app = app
        self.client = app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        tms_db.close_open_connections()
        tms_db.TMS_DB = self.original_db
        self.client = None
        self.app = None
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_invoice_page_pdf_and_exports(self):
        response = self.client.get("/tms/invoices")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Customer Invoices", response.data)

        due_date = (date.today() + timedelta(days=7)).isoformat()
        response = self.client.post(
            "/tms/invoices",
            data={
                "action": "save",
                "shipment_ref": "TMS-DEMO-005",
                "customer_name": "Cobalt Commerce",
                "amount": "2995.00",
                "currency": "CAD",
                "exchange_rate": "1.3500",
                "status": "Sent",
                "due_date": due_date,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        conn = tms_db.get_db()
        try:
            invoice = conn.execute(
                "SELECT * FROM customer_invoices WHERE shipment_ref = ? ORDER BY id DESC",
                ("TMS-DEMO-005",),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(invoice)
        invoice_id = invoice["id"]

        pdf_response = self.client.get(f"/tms/invoices/{invoice_id}/pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF"))

        quickbooks_response = self.client.get("/tms/invoices/export/quickbooks")
        self.assertEqual(quickbooks_response.status_code, 200)
        quickbooks_csv = quickbooks_response.get_data(as_text=True)
        self.assertIn("Invoice No,Customer,Invoice Date,Due Date", quickbooks_csv)
        self.assertIn("CINV-", quickbooks_csv)
        self.assertIn("Cobalt Commerce", quickbooks_csv)
        self.assertIn("CAD", quickbooks_csv)

        xero_response = self.client.get("/tms/invoices/export/xero")
        self.assertEqual(xero_response.status_code, 200)
        xero_csv = xero_response.get_data(as_text=True)
        self.assertIn("Type,ContactName,InvoiceNumber,InvoiceDate", xero_csv)
        self.assertIn("ACCREC", xero_csv)
        self.assertIn("Cobalt Commerce", xero_csv)
        self.assertIn("CAD", xero_csv)


if __name__ == "__main__":
    unittest.main()
