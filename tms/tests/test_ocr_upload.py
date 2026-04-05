import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import tms.tms_routes as tms_routes
from tms.tms_routes import tms as tms_blueprint


REPO_ROOT = Path(__file__).resolve().parents[2]


class OcrUploadTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.captured = {}
        self.file_patcher = mock.patch.object(
            tms_routes,
            "__file__",
            str(Path(self.tempdir.name) / "nested" / "tms_routes.py"),
        )
        self.file_patcher.start()
        self.ocr_patcher = mock.patch.object(tms_routes, "process_ocr_upload", side_effect=self._capture_upload)
        self.ocr_patcher.start()

        app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        app.secret_key = "ocr-upload-test-secret"
        app.register_blueprint(tms_blueprint)
        self.client = app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        self.ocr_patcher.stop()
        self.file_patcher.stop()
        self.client = None
        self.tempdir.cleanup()

    def _capture_upload(self, path, filename):
        self.captured["path"] = path
        self.captured["filename"] = filename
        return {"stored_path": path, "stored_filename": filename}

    def test_ocr_upload_sanitizes_filename(self):
        response = self.client.post(
            "/tms/ocr/upload",
            data={"document": (io.BytesIO(b"hello"), "../../evil.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(self.captured["filename"], "evil.txt")
        self.assertTrue(Path(self.captured["path"]).exists())
        self.assertEqual(Path(self.captured["path"]).name.split("_", 2)[-1], "evil.txt")
        expected_dir = (Path(self.tempdir.name) / "static" / "ocr_uploads").resolve()
        self.assertEqual(Path(self.captured["path"]).resolve().parent, expected_dir)


if __name__ == "__main__":
    unittest.main()
