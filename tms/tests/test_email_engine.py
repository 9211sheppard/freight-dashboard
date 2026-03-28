import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import email_engine


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class EmailEngineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "tms.db"
        self.template_dir = Path(self.tempdir.name) / "templates"
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir.joinpath("sample.subject.txt").write_text(
            "Hello {{ recipient_name }}",
            encoding="utf-8",
        )
        self.template_dir.joinpath("sample.html").write_text(
            (
                "<html><body>"
                "<p>Hi {{ recipient_name }}</p>"
                '<a href="https://example.com/quote">Quote</a>'
                "</body></html>"
            ),
            encoding="utf-8",
        )
        self.engine = email_engine.EmailEngine(
            db_path=self.db_path,
            template_dir=self.template_dir,
            tracking_base_url="https://track.example.com/email",
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_gmail_send_flow_marks_message_sent(self):
        self.engine.connect_gmail(
            client_id="gmail-client",
            client_secret="gmail-secret",
            refresh_token="refresh-token",
            from_email="sender@gmail.com",
            from_name="Sender",
        )

        with patch.object(
            email_engine.requests,
            "post",
            side_effect=[
                FakeResponse({"access_token": "access-token", "expires_in": 3600}),
                FakeResponse({"id": "gmail-msg-1", "threadId": "gmail-thread-1"}),
            ],
        ) as mock_post:
            message = self.engine.send_message(
                provider="gmail",
                to_email="lead@example.com",
                template_name="sample",
                template_context={"recipient_name": "Taylor"},
            )

        self.assertEqual(message["status"], "sent")
        self.assertEqual(message["provider_message_id"], "gmail-msg-1")
        self.assertEqual(message["provider_thread_id"], "gmail-thread-1")
        self.assertIn("/click/", message["html_body"])
        self.assertIn("/open/", message["html_body"])
        self.assertEqual(mock_post.call_args_list[0].args[0], email_engine.GMAIL_TOKEN_URL)
        self.assertEqual(mock_post.call_args_list[1].args[0], email_engine.GMAIL_SEND_URL)

    def test_record_open_and_click_update_message_metrics(self):
        self.engine.connect_gmail(
            client_id="gmail-client",
            client_secret="gmail-secret",
            refresh_token="refresh-token",
            from_email="sender@gmail.com",
            from_name="Sender",
        )

        with patch.object(
            email_engine.requests,
            "post",
            side_effect=[
                FakeResponse({"access_token": "access-token", "expires_in": 3600}),
                FakeResponse({"id": "gmail-msg-2", "threadId": "gmail-thread-2"}),
            ],
        ):
            message = self.engine.send_message(
                provider="gmail",
                to_email="lead@example.com",
                subject="Tracking test",
                html_body='<html><body><a href="https://example.com/rate">Rate</a></body></html>',
            )

        self.engine.record_open(message["tracking_id"], remote_addr="127.0.0.1", user_agent="test-agent")
        self.engine.record_click(message["tracking_id"], "https://example.com/rate", remote_addr="127.0.0.1")
        refreshed = self.engine.get_message(message["id"])
        self.assertEqual(refreshed["open_count"], 1)
        self.assertEqual(refreshed["click_count"], 1)

    def test_scheduler_processes_due_email(self):
        schedule_id = self.engine.schedule_email(
            provider="gmail",
            to_email="lead@example.com",
            template_name="sample",
            context={"recipient_name": "Queued Lead"},
            scheduled_for="2026-03-25T10:00:00+00:00",
        )

        fake_message = {
            "id": 41,
            "status": "sent",
            "provider_message_id": "queued-msg-1",
        }
        with patch.object(self.engine, "send_message", return_value=fake_message):
            processed = self.engine.process_due_scheduled()

        self.assertEqual(len(processed), 1)
        with self.engine._connect() as conn:
            row = conn.execute(
                "SELECT status, sent_message_id FROM email_schedules WHERE id=?",
                (schedule_id,),
            ).fetchone()
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["sent_message_id"], 41)

    @unittest.skipUnless(
        all(
            os.getenv(name)
            for name in [
                "TMS_LIVE_GMAIL_CLIENT_ID",
                "TMS_LIVE_GMAIL_CLIENT_SECRET",
                "TMS_LIVE_GMAIL_REFRESH_TOKEN",
                "TMS_LIVE_GMAIL_FROM",
            ]
        ),
        "Live Gmail credentials not configured",
    )
    def test_live_gmail_send_optional(self):
        from_email = os.environ["TMS_LIVE_GMAIL_FROM"]
        self.engine.connect_gmail(
            client_id=os.environ["TMS_LIVE_GMAIL_CLIENT_ID"],
            client_secret=os.environ["TMS_LIVE_GMAIL_CLIENT_SECRET"],
            refresh_token=os.environ["TMS_LIVE_GMAIL_REFRESH_TOKEN"],
            from_email=from_email,
            from_name="TMS Test",
        )
        message = self.engine.send_message(
            provider="gmail",
            to_email=os.getenv("TMS_LIVE_GMAIL_TO", from_email),
            subject="TMS live Gmail send test",
            html_body="<html><body><p>Live Gmail send test.</p></body></html>",
        )
        self.assertEqual(message["status"], "sent")


if __name__ == "__main__":
    unittest.main()
