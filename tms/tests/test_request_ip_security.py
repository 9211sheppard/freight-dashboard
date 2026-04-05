import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from tms import soc2, tms_routes


class RequestIpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.contacts_db_path = str(Path(self.tempdir.name) / "contacts.db")
        self.app = Flask(__name__)
        self.app.secret_key = "x" * 48

    def tearDown(self):
        self.tempdir.cleanup()

    def test_tms_routes_request_ip_ignores_raw_forwarded_for_header(self):
        with self.app.test_request_context(
            "/tms/",
            headers={"X-Forwarded-For": "198.51.100.7"},
            environ_base={"REMOTE_ADDR": "203.0.113.5"},
        ):
            self.assertEqual(tms_routes._request_ip_address(), "203.0.113.5")

    def test_soc2_audit_uses_remote_addr_instead_of_forwarded_for(self):
        with mock.patch.object(soc2, "DB_PATH", self.contacts_db_path):
            soc2.init_soc2_tables()
            with self.app.test_request_context(
                "/audit",
                headers={"X-Forwarded-For": "198.51.100.7"},
                environ_base={"REMOTE_ADDR": "203.0.113.5"},
            ):
                soc2.audit("TEST_EVENT")

        conn = sqlite3.connect(self.contacts_db_path)
        try:
            row = conn.execute(
                "SELECT ip_address FROM soc2_audit_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], "203.0.113.5")


if __name__ == "__main__":
    unittest.main()
