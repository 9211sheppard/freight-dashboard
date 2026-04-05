import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tms.global_trade as global_trade
import tms.tms_db as tms_db
import tms.tms_integrations as tms_integrations


class SecretStorageTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "secret-storage.db")
        tms_db.init_tms_db()

    def tearDown(self):
        tms_db.close_open_connections()
        tms_db.TMS_DB = self.original_db
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def test_email_passwords_are_encrypted_at_rest(self):
        tms_db.save_email_settings(
            {
                "smtp_pass": "smtp-secret",
                "imap_pass": "imap-secret",
            }
        )

        conn = tms_db.get_db()
        try:
            rows = conn.execute(
                "SELECT key, value FROM tms_settings WHERE key IN (?, ?)",
                ("smtp_pass", "imap_pass"),
            ).fetchall()
        finally:
            conn.close()

        stored = {row["key"]: row["value"] for row in rows}
        self.assertTrue(stored["smtp_pass"].startswith("enc:v1:"))
        self.assertTrue(stored["imap_pass"].startswith("enc:v1:"))
        self.assertNotIn("smtp-secret", stored["smtp_pass"])
        self.assertNotIn("imap-secret", stored["imap_pass"])

        settings = tms_db.get_email_settings(include_secrets=True)
        self.assertEqual(settings["smtp_pass"], "smtp-secret")
        self.assertEqual(settings["imap_pass"], "imap-secret")

    def test_trade_api_key_is_decrypted_for_runtime_use(self):
        conn = tms_db.get_db()
        try:
            tms_db._upsert_setting(
                conn,
                "trade_api_key",
                tms_db._encode_secure_setting("trade_api_key", "trade-secret"),
            )
            conn.commit()
        finally:
            conn.close()

        settings = global_trade.get_trade_settings()
        self.assertEqual(settings["trade_api_key"], "trade-secret")

    def test_production_rejects_default_integration_secret_fallback(self):
        with mock.patch.dict(os.environ, {"TMS_ENV": "production"}, clear=True):
            with self.assertRaises(RuntimeError):
                tms_integrations._get_fernet()

        with mock.patch.dict(
            os.environ,
            {"TMS_ENV": "production", "INTEGRATION_MASTER_KEY": "z" * 48},
            clear=True,
        ):
            encrypted = tms_integrations.encrypt_key("hello")
            self.assertEqual(tms_integrations.decrypt_key(encrypted), "hello")


if __name__ == "__main__":
    unittest.main()
