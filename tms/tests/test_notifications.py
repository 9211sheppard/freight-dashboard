import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

from tms import notifications, tms_db


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "notifications-test.db")
        tms_db.init_tms_db()
        tms_db.preload_demo_data()

        self.app = Flask(__name__)
        self.app.secret_key = "n" * 48
        self.app.config["SECRET_KEY"] = self.app.secret_key
        self.app.config["BASE_URL"] = "https://pilot.example.com"

    def tearDown(self):
        tms_db.close_open_connections()
        tms_db.TMS_DB = self.original_db
        self.tempdir.cleanup()

    def test_shipment_context_uses_signed_public_tracking_url(self):
        with self.app.app_context():
            conn = tms_db.get_db()
            try:
                context = notifications._load_shipment_context(conn, "TMS-DEMO-003")
            finally:
                conn.close()

        self.assertIsNotNone(context)
        self.assertEqual(context["shipment_ref"], "TMS-DEMO-003")
        self.assertTrue(context["tracking_url"].startswith("https://pilot.example.com/track/TMS-DEMO-003?token="))

    def test_public_tracking_url_fails_closed_without_secret_key(self):
        app = Flask(__name__)
        app.config["BASE_URL"] = "https://pilot.example.com"
        with app.app_context():
            self.assertEqual(notifications._public_tracking_url("TMS-DEMO-003"), "")

    def test_public_tracking_url_fails_closed_without_base_url(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "n" * 48
        with app.app_context():
            self.assertEqual(notifications._public_tracking_url("TMS-DEMO-003"), "")

    def test_scheduler_does_not_autostart_in_production_web_process(self):
        app = Flask(__name__)
        app.config["TMS_ENV"] = "production"
        app.config["TESTING"] = False
        with mock.patch.dict("os.environ", {}, clear=False), mock.patch(
            "tms.notifications.threading.Thread"
        ) as thread_cls:
            with app.app_context():
                notifications.ensure_notification_scheduler()
        thread_cls.assert_not_called()

    def test_notification_log_read_has_no_processing_side_effects(self):
        with mock.patch("tms.notifications.ensure_notification_scheduler") as ensure_scheduler, mock.patch(
            "tms.notifications.run_notification_jobs"
        ) as run_jobs:
            logs = notifications.get_notification_log()
        self.assertIsInstance(logs, list)
        ensure_scheduler.assert_not_called()
        run_jobs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
