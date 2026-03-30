import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import requests
from flask import Flask, jsonify
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tms import portal as portal_blueprint
from tms import public as public_blueprint
from tms import tms as tms_blueprint
from tms import tms_routes
from tms.tms_db import get_tracking_page_context, init_tms_db, preload_demo_data
import tms.tms_db as tms_db

REQUEST_TIMEOUT_SECONDS = 30


class _ServerThread(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.server = make_server("127.0.0.1", 0, app)
        self.port = self.server.server_port

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


class TmsExternalApiRequestsTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db_path = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tms-test.db")
        init_tms_db()
        preload_demo_data()

        self.original_limit = tms_routes.API_RATE_LIMITER.max_requests
        self.original_window = tms_routes.API_RATE_LIMITER.window_seconds
        tms_routes.API_RATE_LIMITER.max_requests = 100
        tms_routes.API_RATE_LIMITER.window_seconds = 60
        tms_routes.API_RATE_LIMITER._requests.clear()

        app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
        app.secret_key = "tms-api-test"
        app.register_blueprint(tms_blueprint)
        app.register_blueprint(portal_blueprint)
        app.register_blueprint(public_blueprint)

        @app.route("/__test/login")
        def test_login():
            from flask import session

            session["logged_in"] = True
            session["user_email"] = "admin@example.com"
            session["user_role"] = "admin"
            return jsonify({"ok": True}), 200

        @app.route("/logout")
        def logout():
            return jsonify({"ok": True}), 200

        @app.route("/track/<ref>")
        def public_tracking(ref):
            context = get_tracking_page_context(ref)
            if not context:
                return jsonify({"error": "not_found"}), 404
            return jsonify({"shipment_ref": ref}), 200

        self.server = _ServerThread(app)
        self.server.start()
        self.base_url = f"http://127.0.0.1:{self.server.port}"
        self.browser = requests.Session()
        login_response = self.browser.get(f"{self.base_url}/__test/login", timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(login_response.status_code, 200)

    def tearDown(self):
        self.browser.close()
        self.server.shutdown()
        self.server.join(timeout=5)
        tms_routes.API_RATE_LIMITER._requests.clear()
        tms_routes.API_RATE_LIMITER.max_requests = self.original_limit
        tms_routes.API_RATE_LIMITER.window_seconds = self.original_window
        tms_db.TMS_DB = self.original_db_path
        tms_db.close_open_connections()
        try:
            self.tempdir.cleanup()
        except PermissionError:
            pass

    def _create_key(self, customer_name, permissions):
        form_data = [("action", "generate"), ("customer_name", customer_name)]
        form_data.extend(("permissions", permission) for permission in permissions)
        response = self.browser.post(f"{self.base_url}/tms/api-keys", data=form_data, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'id="generated-api-key"[^>]*>([^<]+)<', response.text)
        self.assertIsNotNone(match)
        return match.group(1).strip()

    def test_external_api_endpoints_and_docs_with_requests(self):
        docs_response = self.browser.get(f"{self.base_url}/tms/api-docs", timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(docs_response.status_code, 200)
        self.assertIn("/api/v1/shipments", docs_response.text)
        self.assertIn("/api/v1/rates/lookup", docs_response.text)
        self.assertIn(f"{self.base_url}/api/v1/shipments", docs_response.text)

        page_response = self.browser.get(f"{self.base_url}/tms/api-keys", timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(page_response.status_code, 200)

        api_key = self._create_key(
            "Lakefront Foods",
            ["shipments.read", "shipments.write", "tracking.read", "rates.read"],
        )
        auth_headers = {"Authorization": f"Bearer {api_key}"}

        unauthenticated = requests.get(f"{self.base_url}/api/v1/shipments", timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(unauthenticated.status_code, 401)

        shipments_response = requests.get(f"{self.base_url}/api/v1/shipments", headers=auth_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(shipments_response.status_code, 200)
        shipments_payload = shipments_response.json()
        self.assertEqual(shipments_payload["customer_name"], "Lakefront Foods")
        self.assertGreaterEqual(shipments_payload["count"], 1)
        shipment_refs = {item["shipment_ref"] for item in shipments_payload["shipments"]}
        self.assertIn("TMS-DEMO-001", shipment_refs)

        detail_response = requests.get(f"{self.base_url}/api/v1/shipments/TMS-DEMO-001", headers=auth_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["shipment"]["shipment_ref"], "TMS-DEMO-001")
        self.assertGreaterEqual(len(detail_payload["events"]), 1)
        self.assertEqual(detail_payload["tracking"]["shipment_ref"], "TMS-DEMO-001")

        tracking_response = requests.get(f"{self.base_url}/api/v1/track/TMS-DEMO-001", headers=auth_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(tracking_response.status_code, 200)
        self.assertEqual(tracking_response.json()["shipment_ref"], "TMS-DEMO-001")

        rates_response = requests.get(
            f"{self.base_url}/api/v1/rates/lookup",
            headers=auth_headers,
            params={"origin": "Chicago, IL", "destination": "Dallas, TX"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self.assertEqual(rates_response.status_code, 200)
        rates_payload = rates_response.json()
        self.assertEqual(rates_payload["origin"], "Chicago, IL")
        self.assertIn(rates_payload["source"], {"contract_rate", "shipment_history"})
        self.assertIsNotNone(rates_payload["history"])

        create_response = requests.post(
            f"{self.base_url}/api/v1/shipments",
            headers={**auth_headers, "Content-Type": "application/json"},
            json={
                "status": "Booked",
                "consignee_name": "Dallas Test Receiver",
                "origin_port": "Chicago, IL",
                "destination_port": "Dallas, TX",
                "cargo_description": "API-created grocery replenishment",
                "mode": "FTL",
                "containers": "53' Reefer",
                "freight_rate": 3333.5,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self.assertEqual(create_response.status_code, 201)
        created_payload = create_response.json()
        created_ref = created_payload["shipment"]["shipment_ref"]
        self.assertTrue(created_ref.startswith("TMS-"))
        self.assertEqual(created_payload["shipment"]["customer_name"], "Lakefront Foods")

        refreshed_shipments = requests.get(f"{self.base_url}/api/v1/shipments", headers=auth_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(refreshed_shipments.status_code, 200)
        refreshed_refs = {item["shipment_ref"] for item in refreshed_shipments.json()["shipments"]}
        self.assertIn(created_ref, refreshed_refs)

    def test_permissions_rate_limit_and_revoke(self):
        tracking_only_key = self._create_key("Lakefront Foods", ["tracking.read"])
        tracking_only_headers = {"Authorization": f"Bearer {tracking_only_key}"}

        forbidden = requests.get(f"{self.base_url}/api/v1/shipments", headers=tracking_only_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(forbidden.status_code, 403)

        full_key = self._create_key("Lakefront Foods", ["shipments.read", "tracking.read", "rates.read"])
        full_headers = {"Authorization": f"Bearer {full_key}"}

        tms_routes.API_RATE_LIMITER._requests.clear()
        tms_routes.API_RATE_LIMITER.max_requests = 3

        statuses = []
        for _ in range(4):
            response = requests.get(f"{self.base_url}/api/v1/shipments", headers=full_headers, timeout=REQUEST_TIMEOUT_SECONDS)
            statuses.append(response.status_code)
        self.assertEqual(statuses[:3], [200, 200, 200])
        self.assertEqual(statuses[3], 429)

        revoke_response = self.browser.post(
            f"{self.base_url}/tms/api-keys",
            data={"action": "revoke", "key": full_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self.assertEqual(revoke_response.status_code, 200)

        revoked = requests.get(f"{self.base_url}/api/v1/shipments", headers=full_headers, timeout=REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(revoked.status_code, 401)

    def test_api_keys_are_hashed_at_rest(self):
        raw_key = self._create_key("Lakefront Foods", ["shipments.read"])
        conn = tms_db.get_db()
        try:
            row = conn.execute(
                """
                SELECT key, key_hint
                FROM api_keys
                WHERE customer_name = ?
                ORDER BY datetime(created_at) DESC, key ASC
                LIMIT 1
                """,
                ("Lakefront Foods",),
            ).fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertNotEqual(row["key"], raw_key)
        self.assertEqual(len(row["key"]), 64)
        self.assertIn("...", row["key_hint"])


if __name__ == "__main__":
    unittest.main()
