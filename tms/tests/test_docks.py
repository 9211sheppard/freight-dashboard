import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import tms.tms_db as tms_db
from tms.tms_routes import tms as tms_blueprint


REPO_ROOT = Path(__file__).resolve().parents[2]


class DockSchedulingTests(unittest.TestCase):
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
        self.app.secret_key = "dock-test-secret"
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

    def _create_shipment(self, *, shipper_name="Lakefront Foods", consignee_name="Metro Grocers"):
        response = self.client.post(
            "/tms/shipments/new",
            data={
                "status": "Booked",
                "shipper_name": shipper_name,
                "shipper_address": "Chicago, IL",
                "consignee_name": consignee_name,
                "consignee_address": "Dallas, TX",
                "origin_port": "Chicago, IL",
                "destination_port": "Dallas, TX",
                "mode": "FTL",
                "etd": "2026-03-27",
                "eta": "2026-03-29",
                "cargo_description": "Palletized food",
                "containers": "53 Dry Van",
                "weight_kg": "12000",
                "volume_cbm": "38",
                "freight_rate": "3000",
                "currency": "USD",
                "incoterm": "DAP",
                "notes": "Dock scheduling test",
                "carrier_id": "",
                "driver_id": "",
                "vehicle_id": "",
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

    def test_dock_crud_booking_conflict_and_calendar(self):
        shipment_one = self._create_shipment()
        shipment_two = self._create_shipment(
            shipper_name="North Harbor Foods",
            consignee_name="South Hub Market",
        )

        create_dock = self.client.post(
            "/tms/docks",
            data={
                "action": "save_dock",
                "name": "Door 1",
                "dock_type": "inbound",
                "location": "Warehouse A",
                "default_duration_minutes": "90",
                "active": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_dock.status_code, 302)

        conn = self._db()
        try:
            dock = conn.execute("SELECT * FROM docks WHERE name = 'Door 1'").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(dock)
        self.assertEqual(dock["dock_type"], "inbound")
        self.assertEqual(dock["default_duration_minutes"], 90)

        edit_dock = self.client.post(
            "/tms/docks",
            data={
                "action": "save_dock",
                "record_id": str(dock["id"]),
                "name": "Door 1",
                "dock_type": "both",
                "location": "Warehouse A - East",
                "default_duration_minutes": "60",
                "active": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(edit_dock.status_code, 302)

        schedule_response = self.client.post(
            "/tms/docks",
            data={
                "action": "save_appointment",
                "shipment_ref": shipment_one["shipment_ref"],
                "dock_id": str(dock["id"]),
                "appointment_type": "inbound",
                "scheduled_start": "2026-03-27T09:00",
                "contact_name": "Warehouse Ops",
                "contact_email": "dock@example.com",
                "notes": "Arrive 15 minutes early",
            },
            follow_redirects=False,
        )
        self.assertEqual(schedule_response.status_code, 302)

        conn = self._db()
        try:
            appointment = conn.execute(
                "SELECT * FROM dock_appointments WHERE shipment_ref = ?",
                (shipment_one["shipment_ref"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(appointment)
        self.assertEqual(appointment["status"], "Scheduled")
        self.assertEqual(appointment["duration_minutes"], 60)
        self.assertTrue(appointment["booking_token"])

        conflict_response = self.client.post(
            "/tms/docks",
            data={
                "action": "save_appointment",
                "shipment_ref": shipment_two["shipment_ref"],
                "dock_id": str(dock["id"]),
                "appointment_type": "inbound",
                "scheduled_start": "2026-03-27T09:30",
            },
            follow_redirects=False,
        )
        self.assertEqual(conflict_response.status_code, 400)
        self.assertIn(b"already booked", conflict_response.data)

        status_response = self.client.post(
            f"/tms/docks/appointments/{appointment['id']}/status",
            data={"status": "Loading", "shipment_ref": shipment_one["shipment_ref"]},
            follow_redirects=False,
        )
        self.assertEqual(status_response.status_code, 302)

        calendar_response = self.client.get("/tms/docks/calendar?start=2026-03-23")
        self.assertEqual(calendar_response.status_code, 200)
        self.assertIn(b"Door 1", calendar_response.data)
        self.assertIn(shipment_one["shipment_ref"].encode("utf-8"), calendar_response.data)
        self.assertIn(b"Loading", calendar_response.data)

        shipment_page = self.client.get(f"/tms/shipments/{shipment_one['shipment_ref']}")
        self.assertEqual(shipment_page.status_code, 200)
        self.assertIn(b"Dock Appointment", shipment_page.data)
        self.assertIn(b"Carrier Booking Link", shipment_page.data)

    def test_carrier_self_booking_uses_generated_token(self):
        shipment = self._create_shipment(shipper_name="Prairie Supply", consignee_name="Atlantic Retail")
        self.client.post(
            "/tms/docks",
            data={
                "action": "save_dock",
                "name": "Door 5",
                "dock_type": "both",
                "location": "Crossdock North",
                "default_duration_minutes": "60",
                "active": "1",
            },
            follow_redirects=False,
        )

        conn = self._db()
        try:
            dock = conn.execute("SELECT * FROM docks WHERE name = 'Door 5'").fetchone()
        finally:
            conn.close()

        with self.app.test_request_context():
            token = tms_db.get_or_create_dock_booking_token(shipment["shipment_ref"])

        booking_page = self.client.get(f"/tms/docks/book/{token}")
        self.assertEqual(booking_page.status_code, 200)
        self.assertIn(shipment["shipment_ref"].encode("utf-8"), booking_page.data)

        slots = tms_db.list_available_dock_slots(appointment_type="outbound")
        selected_slot = None
        for day in slots:
            for dock_entry in day["docks"]:
                if dock_entry["id"] == dock["id"] and dock_entry["slots"]:
                    selected_slot = dock_entry["slots"][0]
                    break
            if selected_slot:
                break

        self.assertIsNotNone(selected_slot)

        book_response = self.client.post(
            f"/tms/docks/book/{token}",
            data={
                "action": "book",
                "appointment_type": "outbound",
                "slot": f"{selected_slot['dock_id']}|{selected_slot['start_value']}",
                "contact_name": "Carrier Ops",
                "contact_email": "ops@carrier.test",
                "notes": "Driver will call before arrival",
            },
            follow_redirects=False,
        )
        self.assertEqual(book_response.status_code, 302)

        conn = self._db()
        try:
            appointment = conn.execute(
                "SELECT * FROM dock_appointments WHERE shipment_ref = ?",
                (shipment["shipment_ref"],),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(appointment)
        self.assertEqual(appointment["dock_id"], dock["id"])
        self.assertEqual(appointment["appointment_type"], "outbound")
        self.assertEqual(appointment["booked_by"], "carrier")
        self.assertEqual(appointment["contact_email"], "ops@carrier.test")
        self.assertIn(selected_slot["start_value"].replace("T", " "), appointment["scheduled_start"])


if __name__ == "__main__":
    unittest.main()
