import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import tms.tms_db as tms_db
import tms.wms as wms
from tms.tms_routes import tms as tms_blueprint


REPO_ROOT = Path(__file__).resolve().parents[2]


class WarehouseManagementTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "wms-test.db")
        self.db_patch = mock.patch.object(tms_db, "TMS_DB", self.db_path)
        self.db_patch.start()

        self.app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        self.app.secret_key = "wms-test-secret"
        self.app.register_blueprint(tms_blueprint)

        @self.app.route("/logout")
        def logout():
            return "logout"

        tms_db.init_tms_db()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_wms_receiving_pick_flow_and_dashboard(self):
        receipt = wms.create_receipt(
            "INB-1001",
            "North Harbor Supply",
            "PO-4451",
            [
                {"sku": "SKU-1001", "expected_qty": 8, "location_code": "A-01-01", "notes": "Primary stock"},
                {"sku": "SKU-2002", "expected_qty": 4, "location_code": "B-01-01", "notes": "Reserve stock"},
            ],
        )
        receipt_detail = wms.get_receipt(receipt["id"])
        self.assertIsNotNone(receipt_detail)
        self.assertEqual(receipt_detail["status"], "pending")
        self.assertEqual(len(receipt_detail["lines"]), 2)

        first_line = receipt_detail["lines"][0]
        second_line = receipt_detail["lines"][1]
        receive_result = wms.receive_line(first_line["id"], 8, "A-01-01")
        self.assertEqual(receive_result["status"], "receiving")

        inventory_by_sku = wms.get_inventory_by_sku("SKU-1001")
        self.assertEqual(len(inventory_by_sku), 1)
        self.assertEqual(inventory_by_sku[0]["location_code"], "A-01-01")
        self.assertEqual(inventory_by_sku[0]["quantity"], 8)

        pick = wms.create_pick(
            "OUT-9001",
            [{"sku": "SKU-1001", "quantity": 5, "location_code": "A-01-01"}],
        )
        pick_detail = wms.get_pick(pick["id"])
        self.assertIsNotNone(pick_detail)
        self.assertEqual(pick_detail["status"], "pending")
        self.assertEqual(len(pick_detail["lines"]), 1)
        self.assertEqual(pick_detail["lines"][0]["available_qty"], 8)

        pick_result = wms.pick_line(pick_detail["lines"][0]["id"], 3)
        self.assertEqual(pick_result["status"], "short")
        self.assertEqual(pick_result["pick_status"], "complete")

        location_inventory = wms.get_inventory_by_location("A-01-01")
        self.assertEqual(len(location_inventory), 1)
        self.assertEqual(location_inventory[0]["sku"], "SKU-1001")
        self.assertEqual(location_inventory[0]["quantity"], 5)

        low_stock = wms.get_low_stock(threshold=6)
        self.assertEqual(low_stock[0]["sku"], "SKU-1001")

        dashboard = wms.get_wms_dashboard()
        self.assertEqual(dashboard["sku_count"], 1)
        self.assertEqual(dashboard["pending_receipts"], 1)
        self.assertEqual(dashboard["open_picks"], 0)
        self.assertEqual(dashboard["inventory_value_display"], "N/A")

        updated_receipt = wms.get_receipt(receipt["id"])
        self.assertEqual(updated_receipt["lines"][0]["received_qty"], 8)
        self.assertEqual(updated_receipt["lines"][1]["id"], second_line["id"])

    def test_wms_pages_render_with_seeded_data(self):
        receipt = wms.create_receipt(
            "INB-1002",
            "Blue Peak Vendor",
            "PO-7788",
            [{"sku": "SKU-3003", "expected_qty": 2, "location_code": "C-01-01"}],
        )
        receipt_detail = wms.get_receipt(receipt["id"])
        wms.receive_line(receipt_detail["lines"][0]["id"], 2, "C-01-01")
        pick = wms.create_pick(
            "OUT-9002",
            [{"sku": "SKU-3003", "quantity": 1, "location_code": "C-01-01"}],
        )

        dashboard_response = self.client.get("/tms/wms")
        inventory_response = self.client.get("/tms/wms/inventory")
        receipts_response = self.client.get(f"/tms/wms/receipts/{receipt['id']}")
        picks_response = self.client.get(f"/tms/wms/picks/{pick['id']}")
        locations_response = self.client.get("/tms/wms/locations")

        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(inventory_response.status_code, 200)
        self.assertEqual(receipts_response.status_code, 200)
        self.assertEqual(picks_response.status_code, 200)
        self.assertEqual(locations_response.status_code, 200)

        self.assertIn(b"Warehouse Dashboard", dashboard_response.data)
        self.assertIn(b"All Inventory", inventory_response.data)
        self.assertIn(receipt["receipt_ref"].encode("utf-8"), receipts_response.data)
        self.assertIn(pick["pick_ref"].encode("utf-8"), picks_response.data)
        self.assertIn(b"Location Grid", locations_response.data)
