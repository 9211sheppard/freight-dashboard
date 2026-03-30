import tempfile
import unittest
from pathlib import Path

import tms.tms_db as tms_db


class EmailSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "email-settings.db")
        tms_db.init_tms_db()

    def tearDown(self):
        tms_db.close_open_connections()
        tms_db.TMS_DB = self.original_db
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_get_email_settings_masks_saved_passwords(self):
        tms_db.save_email_settings(
            {
                "smtp_host": "smtp.example.com",
                "smtp_pass": "smtp-secret",
                "imap_host": "imap.example.com",
                "imap_pass": "imap-secret",
            }
        )

        settings = tms_db.get_email_settings()
        self.assertEqual(settings["smtp_pass"], "")
        self.assertEqual(settings["imap_pass"], "")
        self.assertTrue(settings["smtp_pass_configured"])
        self.assertTrue(settings["imap_pass_configured"])

    def test_save_email_settings_preserves_or_clears_existing_passwords_explicitly(self):
        tms_db.save_email_settings({"smtp_pass": "smtp-secret"})
        tms_db.save_email_settings({"smtp_pass": ""})

        conn = tms_db.get_db()
        try:
            preserved = tms_db._get_settings(conn)["smtp_pass"]
        finally:
            conn.close()
        self.assertEqual(preserved, "smtp-secret")

        tms_db.save_email_settings({"smtp_pass": "", "clear_smtp_pass": "true"})
        conn = tms_db.get_db()
        try:
            cleared = tms_db._get_settings(conn)["smtp_pass"]
        finally:
            conn.close()
        self.assertEqual(cleared, "")


if __name__ == "__main__":
    unittest.main()
