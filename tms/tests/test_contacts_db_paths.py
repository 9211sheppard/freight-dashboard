import importlib
import os
import tempfile
import unittest
from pathlib import Path


DB_PATH_MODULES = [
    "tms.auto_invoice",
    "tms.carrier_scorecard",
    "tms.doc_ocr",
    "tms.eld",
    "tms.fuel_surcharge",
    "tms.ifta",
    "tms.load_matcher",
    "tms.market_rates",
    "tms.rate_matrix",
    "tms.soc2",
    "tms.subscriptions",
]
RELOADED_MODULES = DB_PATH_MODULES + [
    "tms.email_engine",
    "tms.rate_reply_parser",
]


class ContactsDbPathTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.contacts_db_path = str(Path(self.tempdir.name) / "contacts.db")
        self.original_env = os.environ.get("TMS_CONTACTS_DB_PATH")
        os.environ["TMS_CONTACTS_DB_PATH"] = self.contacts_db_path

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop("TMS_CONTACTS_DB_PATH", None)
        else:
            os.environ["TMS_CONTACTS_DB_PATH"] = self.original_env
        for module_name in RELOADED_MODULES:
            module = importlib.import_module(module_name)
            importlib.reload(module)
        self.tempdir.cleanup()

    def test_modules_honor_tms_contacts_db_path(self):
        for module_name in DB_PATH_MODULES:
            module = importlib.import_module(module_name)
            module = importlib.reload(module)
            self.assertEqual(module.DB_PATH, self.contacts_db_path, module_name)

        email_engine = importlib.import_module("tms.email_engine")
        email_engine = importlib.reload(email_engine)
        self.assertEqual(email_engine.DEFAULT_DB_PATH, self.contacts_db_path)

        rate_reply_parser = importlib.import_module("tms.rate_reply_parser")
        rate_reply_parser = importlib.reload(rate_reply_parser)
        self.assertEqual(rate_reply_parser._contact_db_path(), self.contacts_db_path)
        self.assertEqual(rate_reply_parser._email_engine_db_path(), self.contacts_db_path)


if __name__ == "__main__":
    unittest.main()
