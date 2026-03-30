import base64
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from flask import Flask, render_template

from tms import tms_db
from tms.tms_routes import tms as tms_blueprint
import tms.tms_routes as tms_routes


REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNATURE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4////fwAJ+wP9KobjigAAAABJRU5ErkJggg=="
)
PNG_BYTES = base64.b64decode(SIGNATURE_DATA_URL.split(",", 1)[1])


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class PodAndCarrierSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "tms-test.db")
        self.upload_dir = str(Path(self.tempdir.name) / "pod-uploads")
        self.patches = [
            mock.patch.object(tms_db, "TMS_DB", self.db_path),
            mock.patch.object(tms_db, "POD_UPLOAD_DIR", self.upload_dir),
            mock.patch.object(tms_routes, "POD_UPLOAD_DIR", self.upload_dir),
        ]
        for patcher in self.patches:
            patcher.start()

        tms_db.init_tms_db()

        self.app = Flask(
            __name__,
            template_folder=str(REPO_ROOT / "templates"),
            static_folder=str(REPO_ROOT / "static"),
        )
        self.app.secret_key = "pod-safety-test-secret"
        self.app.register_blueprint(tms_blueprint)

        @self.app.route("/track/<ref>")
        def public_tracking(ref):
            context = tms_db.get_tracking_page_context(ref)
            if not context:
                return render_template("tms/tracking.html", shipment=None, ref=ref), 404
            return render_template("tms/tracking.html", **context)

        @self.app.route("/logout")
        def logout():
            return "ok"

        self.client = self.app.test_client()
        with self.client.session_transaction() as session_state:
            session_state["user_email"] = "admin@example.com"
            session_state["user_role"] = "admin"
            session_state["tms_tenant_id"] = "tenant-default"

    def tearDown(self):
        tms_db.close_open_connections()
        for patcher in reversed(self.patches):
            patcher.stop()
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def _db(self):
        return tms_db.get_db()

    def _create_shipment(self, *, shipment_ref="TMS-POD-001", carrier_id=None):
        conn = self._db()
        try:
            conn.execute(
                """
                INSERT INTO shipments
                    (shipment_ref, status, shipper_name, shipper_address, consignee_name, consignee_address,
                     carrier_id, carrier_name, origin_port, destination_port, mode, etd, eta,
                     cargo_description, containers, weight_kg, volume_cbm, freight_rate, currency, incoterm, notes)
                VALUES (?, 'In Transit', 'Northwind Foods', 'Chicago, IL', 'Retail Hub', 'Dallas, TX',
                        ?, (SELECT name FROM tms_carriers WHERE id = ?), 'Chicago, IL', 'Dallas, TX', 'FTL',
                        '2026-03-25', '2026-03-27', 'Frozen goods', '53 Reefer', 12000, 41, 3200, 'USD', 'DAP',
                        'Handle with care')
                """,
                (shipment_ref, carrier_id, carrier_id),
            )
            conn.commit()
        finally:
            conn.close()
        return shipment_ref

    def _carrier_refresh_side_effect(self, safety_rating="Satisfactory", insurance_days=15):
        expiration = (datetime.utcnow().date() + timedelta(days=insurance_days)).strftime("%m/%d/%Y")

        def _side_effect(url, params=None, timeout=15):
            if url.endswith("/authority/"):
                return _MockResponse(
                    {
                        "content": [
                            {
                                "authority": {
                                    "commonAuthorityStatus": "Authorized",
                                    "insuranceStatus": "Active",
                                    "insuranceExpirationDate": expiration,
                                }
                            }
                        ]
                    }
                )
            return _MockResponse(
                {
                    "content": [
                        {
                            "carrier": {
                                "dotNumber": "123456",
                                "legalName": "Safety Carrier",
                                "safetyRating": safety_rating,
                            }
                        }
                    ]
                }
            )

        return _side_effect

    def test_public_pod_submission_marks_shipment_delivered_and_generates_pdf(self):
        ref = self._create_shipment()
        token = tms_db.get_or_create_pod_token(ref)

        get_response = self.client.get(f"/tms/pod/{ref}/{token}")
        self.assertEqual(get_response.status_code, 200)
        self.assertIn(b"Proof of Delivery", get_response.data)

        post_response = self.client.post(
            f"/tms/pod/{ref}/{token}",
            data={
                "recipient_name": "Jordan Lee",
                "delivered_at": "2026-03-26T15:30",
                "notes": "Received at dock 7.",
                "signature_data": SIGNATURE_DATA_URL,
                "photo": (io.BytesIO(PNG_BYTES), "pod.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertIn(b"shipment has been marked Delivered", post_response.data)

        conn = self._db()
        try:
            shipment = conn.execute(
                "SELECT status FROM shipments WHERE shipment_ref = ?",
                (ref,),
            ).fetchone()
            pod = conn.execute(
                "SELECT * FROM pod_records WHERE shipment_ref = ?",
                (ref,),
            ).fetchone()
        finally:
            conn.close()

        self.assertEqual(shipment["status"], "Delivered")
        self.assertIsNotNone(pod)
        self.assertEqual(pod["recipient_name"], "Jordan Lee")
        self.assertTrue(os.path.exists(pod["photo_path"]))

        shipment_page = self.client.get(f"/tms/shipments/{ref}")
        self.assertEqual(shipment_page.status_code, 200)
        self.assertIn(b"Jordan Lee", shipment_page.data)
        self.assertIn(b"Proof of Delivery", shipment_page.data)
        self.assertIn(b"/pod.pdf", shipment_page.data)

        photo_response = self.client.get(f"/tms/shipments/{ref}/pod/photo/{token}")
        self.assertEqual(photo_response.status_code, 200)
        photo_response.close()

        pdf_response = self.client.get(f"/tms/shipments/{ref}/pod.pdf")
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response.mimetype, "application/pdf")
        self.assertTrue(pdf_response.data.startswith(b"%PDF-"))

    def test_legacy_pod_submission_route_requires_token(self):
        ref = self._create_shipment(shipment_ref="TMS-POD-LEGACY-001")
        response = self.client.get(f"/tms/shipments/{ref}/pod-submit")
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"valid POD link", response.data)

    def test_legacy_pod_submission_route_accepts_token_query(self):
        ref = self._create_shipment(shipment_ref="TMS-POD-LEGACY-002")
        token = tms_db.get_or_create_pod_token(ref)
        response = self.client.get(f"/tms/shipments/{ref}/pod-submit?token={token}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Proof of Delivery", response.data)

    def test_carrier_save_auto_refreshes_fmcsa_and_manual_refresh_updates_badges(self):
        with mock.patch.dict(os.environ, {"FMCSA_WEB_KEY": "test-web-key"}, clear=False):
            with mock.patch.object(tms_db.requests, "get", side_effect=self._carrier_refresh_side_effect()):
                create_response = self.client.post(
                    "/tms/carriers/new",
                    data={
                        "name": "Safety Carrier",
                        "scac": "SAFE",
                        "dot_number": "123456",
                        "country": "United States",
                        "contact_email": "ops@safety.test",
                        "contact_phone": "+1-555-0110",
                        "active": "1",
                    },
                    follow_redirects=False,
                )
            self.assertEqual(create_response.status_code, 302)

            conn = self._db()
            try:
                carrier = conn.execute(
                    "SELECT * FROM tms_carriers WHERE name = ?",
                    ("Safety Carrier",),
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNotNone(carrier)
            self.assertEqual(carrier["safety_rating"], "Satisfactory")
            self.assertEqual(carrier["insurance_status"], "Active")
            self.assertEqual(carrier["auth_status"], "Authorized")
            carrier_id = carrier["id"]

            ref = self._create_shipment(shipment_ref="TMS-SAFE-001", carrier_id=carrier_id)

            carrier_page = self.client.get(f"/tms/carriers?carrier_id={carrier_id}")
            self.assertEqual(carrier_page.status_code, 200)
            self.assertIn(b"Satisfactory", carrier_page.data)
            self.assertIn(b"Refresh FMCSA", carrier_page.data)

            shipment_page = self.client.get(f"/tms/shipments/{ref}")
            self.assertEqual(shipment_page.status_code, 200)
            self.assertIn(b"Satisfactory", shipment_page.data)
            self.assertIn(b"Carrier insurance expires in", shipment_page.data)

            with mock.patch.object(
                tms_db.requests,
                "get",
                side_effect=self._carrier_refresh_side_effect(safety_rating="Conditional", insurance_days=7),
            ):
                refresh_response = self.client.post(
                    f"/tms/carriers/{carrier_id}/safety-refresh",
                    data={"page": "1", "q": ""},
                    follow_redirects=False,
                )
            self.assertEqual(refresh_response.status_code, 302)

            conn = self._db()
            try:
                refreshed = conn.execute(
                    "SELECT safety_rating FROM tms_carriers WHERE id = ?",
                    (carrier_id,),
                ).fetchone()
            finally:
                conn.close()
            self.assertEqual(refreshed["safety_rating"], "Conditional")


if __name__ == "__main__":
    unittest.main()
