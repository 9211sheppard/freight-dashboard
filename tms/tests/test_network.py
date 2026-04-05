import tempfile
import unittest
from pathlib import Path

from flask import Flask

from tms.tms_routes import tms as tms_blueprint
import tms.tms_db as tms_db


class NetworkRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "network-test.db")
        tms_db.init_tms_db()

        conn = tms_db.get_db()
        try:
            conn.execute(
                """
                INSERT INTO network_loads (
                    posted_by, company_name, origin_city, origin_country,
                    dest_city, dest_country, cargo_type, weight_kg, volume_cbm,
                    ready_date, equipment_type, rate_usd, rate_type, mode, notes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "dispatcher@example.com",
                    "Road Carrier",
                    "Toronto",
                    "CA",
                    "Chicago",
                    "US",
                    "General Freight",
                    1000,
                    10,
                    "2026-03-29",
                    "Van",
                    1200,
                    "flat",
                    "road",
                    "",
                    "open",
                ),
            )
            conn.execute(
                """
                INSERT INTO network_loads (
                    posted_by, company_name, origin_city, origin_country,
                    dest_city, dest_country, cargo_type, weight_kg, volume_cbm,
                    ready_date, equipment_type, rate_usd, rate_type, mode, notes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "dispatcher@example.com",
                    "Ocean Carrier",
                    "Vancouver",
                    "CA",
                    "Busan",
                    "KR",
                    "Containers",
                    2000,
                    20,
                    "2026-03-30",
                    "Container",
                    2400,
                    "flat",
                    "ocean",
                    "",
                    "open",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        repo_root = Path(__file__).resolve().parents[2]
        app = Flask(
            __name__,
            template_folder=str(repo_root / "templates"),
            static_folder=str(repo_root / "static"),
        )
        app.secret_key = "network-test-secret"
        app.register_blueprint(tms_blueprint)
        self.client = app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        tms_db.close_open_connections()
        tms_db.TMS_DB = self.original_db
        self.client = None
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_network_mode_filter_returns_matching_rows(self):
        response = self.client.get("/tms/network?mode=road")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Road Carrier", response.data)
        self.assertNotIn(b"Ocean Carrier", response.data)

    def test_network_mode_filter_treats_sql_injection_as_literal(self):
        response = self.client.get("/tms/network?mode=road%27%20OR%20%271%27=%271")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Road Carrier", response.data)
        self.assertNotIn(b"Ocean Carrier", response.data)


if __name__ == "__main__":
    unittest.main()
