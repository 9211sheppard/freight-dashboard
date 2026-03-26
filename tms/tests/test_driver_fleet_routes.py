import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import tms.tms_db as tms_db
from tms.tms_routes import tms as tms_blueprint


REPO_ROOT = Path(__file__).resolve().parents[2]


class DriverFleetRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "tms-test.db")
        self.db_patch = mock.patch.object(tms_db, "TMS_DB", self.db_path)
        self.db_patch.start()

        self.app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(tms_blueprint)

        @self.app.route("/logout")
        def logout():
            return "logout"

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            return f"tracking:{ref}"

        tms_db.init_tms_db()
        self.client = self.app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.tempdir.cleanup()

    def _db(self):
        return tms_db.get_db()

    def _create_driver(self, name="Jamie Torres", license_number="LIC-001"):
        response = self.client.post(
            "/tms/drivers/new",
            data={
                "name": name,
                "license_number": license_number,
                "phone": "+1-555-0101",
                "country": "United States",
                "status": "Active",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        conn = self._db()
        try:
            row = conn.execute(
                "SELECT * FROM drivers WHERE license_number = ?",
                (license_number,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        return row

    def _create_vehicle(self, truck_number="TRK-100"):
        response = self.client.post(
            "/tms/fleet/new",
            data={
                "truck_number": truck_number,
                "vehicle_type": "53' Dry Van",
                "capacity_weight": "22000",
                "capacity_cbm": "82",
                "country": "United States",
                "status": "Active",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        conn = self._db()
        try:
            row = conn.execute(
                "SELECT * FROM vehicles WHERE truck_number = ?",
                (truck_number,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        return row

    def _create_shipment(self, driver_id=None, vehicle_id=None):
        response = self.client.post(
            "/tms/shipments/new",
            data={
                "status": "Active",
                "shipper_name": "Lakefront Foods",
                "shipper_address": "Chicago, IL",
                "consignee_name": "Metro Grocers",
                "consignee_address": "Dallas, TX",
                "origin_port": "Chicago, IL",
                "destination_port": "Dallas, TX",
                "mode": "FTL",
                "etd": "2026-03-26",
                "eta": "2026-03-28",
                "cargo_description": "Frozen goods",
                "containers": "53' Reefer",
                "weight_kg": "12000",
                "volume_cbm": "41",
                "freight_rate": "3200",
                "currency": "USD",
                "incoterm": "DAP",
                "notes": "Priority delivery",
                "driver_id": str(driver_id or ""),
                "vehicle_id": str(vehicle_id or ""),
                "carrier_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        conn = self._db()
        try:
            row = conn.execute(
                "SELECT * FROM shipments ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        return row

    def test_driver_and_vehicle_crud_with_shipment_assignment(self):
        driver = self._create_driver()
        vehicle = self._create_vehicle()

        drivers_page = self.client.get("/tms/drivers")
        fleet_page = self.client.get("/tms/fleet")
        self.assertEqual(drivers_page.status_code, 200)
        self.assertEqual(fleet_page.status_code, 200)
        self.assertIn(b"Jamie Torres", drivers_page.data)
        self.assertIn(b"TRK-100", fleet_page.data)

        shipment = self._create_shipment(driver_id=driver["id"], vehicle_id=vehicle["id"])

        shipment_page = self.client.get(f"/tms/shipments/{shipment['shipment_ref']}")
        self.assertEqual(shipment_page.status_code, 200)
        self.assertIn(b"Jamie Torres", shipment_page.data)
        self.assertIn(b"TRK-100", shipment_page.data)

        edit_driver = self.client.post(
            f"/tms/drivers/{driver['id']}/edit",
            data={
                "name": "Jamie Torres",
                "license_number": "LIC-001",
                "phone": "+1-555-0199",
                "country": "Canada",
                "status": "On Trip",
            },
            follow_redirects=False,
        )
        edit_vehicle = self.client.post(
            f"/tms/fleet/{vehicle['id']}/edit",
            data={
                "truck_number": "TRK-100",
                "vehicle_type": "53' Reefer",
                "capacity_weight": "24000",
                "capacity_cbm": "84",
                "country": "Canada",
                "status": "On Trip",
            },
            follow_redirects=False,
        )
        self.assertEqual(edit_driver.status_code, 302)
        self.assertEqual(edit_vehicle.status_code, 302)

        conn = self._db()
        try:
            updated_driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver["id"],)).fetchone()
            updated_vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle["id"],)).fetchone()
        finally:
            conn.close()
        self.assertEqual(updated_driver["status"], "On Trip")
        self.assertEqual(updated_driver["country"], "Canada")
        self.assertEqual(updated_vehicle["vehicle_type"], "53' Reefer")
        self.assertEqual(updated_vehicle["status"], "On Trip")

        delete_driver = self.client.post(
            f"/tms/drivers/{driver['id']}/delete",
            follow_redirects=False,
        )
        delete_vehicle = self.client.post(
            f"/tms/fleet/{vehicle['id']}/delete",
            follow_redirects=False,
        )
        self.assertEqual(delete_driver.status_code, 302)
        self.assertEqual(delete_vehicle.status_code, 302)

        conn = self._db()
        try:
            remaining_driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver["id"],)).fetchone()
            remaining_vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle["id"],)).fetchone()
            updated_shipment = conn.execute(
                "SELECT driver_id, vehicle_id FROM shipments WHERE shipment_ref = ?",
                (shipment["shipment_ref"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(remaining_driver)
        self.assertIsNone(remaining_vehicle)
        self.assertIsNone(updated_shipment["driver_id"])
        self.assertIsNone(updated_shipment["vehicle_id"])

    def test_mobile_checkin_creates_duty_log_and_hos_alert(self):
        driver = self._create_driver(name="Avery Cole", license_number="LIC-777")
        vehicle = self._create_vehicle(truck_number="TRK-777")
        shipment = self._create_shipment(driver_id=driver["id"], vehicle_id=vehicle["id"])

        response = self.client.post(
            f"/tms/driver/{driver['checkin_token']}",
            data={
                "status": "On Trip",
                "location": "Memphis, TN",
                "issue": "Running late due to inspection",
                "duty_status": "Driving",
                "duty_start": "2026-03-26T06:00",
                "duty_end": "2026-03-26T18:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        conn = self._db()
        try:
            updated_driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver["id"],)).fetchone()
            duty_log = conn.execute(
                "SELECT * FROM duty_logs WHERE driver_id = ? ORDER BY id DESC LIMIT 1",
                (driver["id"],),
            ).fetchone()
            events = conn.execute(
                "SELECT event_type, description FROM shipment_events WHERE shipment_id = ? ORDER BY id DESC",
                (shipment["id"],),
            ).fetchall()
        finally:
            conn.close()

        self.assertEqual(updated_driver["status"], "On Trip")
        self.assertEqual(updated_driver["last_location"], "Memphis, TN")
        self.assertEqual(updated_driver["last_issue"], "Running late due to inspection")
        self.assertEqual(duty_log["duty_status"], "Driving")
        self.assertEqual(duty_log["exceeds_driving_limit"], 1)
        self.assertAlmostEqual(duty_log["hours_logged"], 12.5, places=2)
        event_types = [row["event_type"] for row in events]
        self.assertIn("Driver Check-In", event_types)
        self.assertIn("Driver Issue", event_types)
        self.assertIn("HOS Alert", event_types)

        drivers_page = self.client.get(f"/tms/drivers?driver_id={driver['id']}")
        self.assertEqual(drivers_page.status_code, 200)
        self.assertIn(b"Over 11h", drivers_page.data)


if __name__ == "__main__":
    unittest.main()
