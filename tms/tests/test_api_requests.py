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

from tms import tms as tms_blueprint
from tms import tms_routes
from tms.tms_db import get_tracking_page_context, init_tms_db, preload_demo_data
import tms.tms_db as tms_db


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

    def tearDown(self):
        self.server.shutdown()
        self.server.join(timeout=5)
        tms_routes.API_RATE_LIMITER._requests.clear()
        tms_routes.API_RATE_LIMITER.max_requests = self.original_limit
        tms_routes.API_RATE_LIMITER.window_seconds = self.original_window
        tms_db.TMS_DB = self.original_db_path
        self.tempdir.cleanup()

    def _create_key(self, customer_name, permissions):
        form_data = [("action", "generate"), ("customer_name", customer_name)]
        form_data.extend(("permissions", permission) for permission in permissions)
        response = requests.post(f"{self.base_url}/tms/api-keys", data=form_data, timeout=10)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'id="generated-api-key"[^>]*>([^<]+)<', response.text)
        self.assertIsNotNone(match)
        return match.group(1).strip()

    def test_external_api_endpoints_and_docs_with_requests(self):
        docs_response = requests.get(f"{self.base_url}/tms/api-docs", timeout=10)
        self.assertEqual(docs_response.status_code, 200)
        self.assertIn("/api/v1/shipments", docs_response.text)
        self.assertIn("/api/v1/rates/lookup", docs_response.text)

        page_response = requests.get(f"{self.base_url}/tms/api-keys", timeout=10)
        self.assertEqual(page_response.status_code, 200)

        api_key = self._create_key(
            "Lakefront Foods",
            ["shipments.read", "shipments.write", "tracking.read", "rates.read"],
        )
        auth_headers = {"Authorization": f"Bearer {api_key}"}

        unauthenticated = requests.get(f"{self.base_url}/api/v1/shipments", timeout=10)
        self.assertEqual(unauthenticated.status_code, 401)

        shipments_response = requests.get(f"{self.base_url}/api/v1/shipments", headers=auth_headers, timeout=10)
        self.assertEqual(shipments_response.status_code, 200)
        shipments_payload = shipments_response.json()
        self.assertEqual(shipments_payload["customer_name"], "Lakefront Foods")
        self.assertGreaterEqual(shipments_payload["count"], 1)
        shipment_refs = {item["shipment_ref"] for item in shipments_payload["shipments"]}
        self.assertIn("TMS-DEMO-001", shipment_refs)

        detail_response = requests.get(f"{self.base_url}/api/v1/shipments/TMS-DEMO-001", headers=auth_headers, timeout=10)
        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["shipment"]["shipment_ref"], "TMS-DEMO-001")
        self.assertGreaterEqual(len(detail_payload["events"]), 1)
        self.assertEqual(detail_payload["tracking"]["shipment_ref"], "TMS-DEMO-001")

        tracking_response = requests.get(f"{self.base_url}/api/v1/track/TMS-DEMO-001", headers=auth_headers, timeout=10)
        self.assertEqual(tracking_response.status_code, 200)
        self.assertEqual(tracking_response.json()["shipment_ref"], "TMS-DEMO-001")

        rates_response = requests.get(
            f"{self.base_url}/api/v1/rates/lookup",
            headers=auth_headers,
            params={"origin": "Chicago, IL", "destination": "Dallas, TX"},
            timeout=10,
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
            timeout=10,
        )
        self.assertEqual(create_response.status_code, 201)
        created_payload = create_response.json()
        created_ref = created_payload["shipment"]["shipment_ref"]
        self.assertTrue(created_ref.startswith("TMS-"))
        self.assertEqual(created_payload["shipment"]["customer_name"], "Lakefront Foods")

        refreshed_shipments = requests.get(f"{self.base_url}/api/v1/shipments", headers=auth_headers, timeout=10)
        self.assertEqual(refreshed_shipments.status_code, 200)
        refreshed_refs = {item["shipment_ref"] for item in refreshed_shipments.json()["shipments"]}
        self.assertIn(created_ref, refreshed_refs)

    def test_permissions_rate_limit_and_revoke(self):
        tracking_only_key = self._create_key("Lakefront Foods", ["tracking.read"])
        tracking_only_headers = {"Authorization": f"Bearer {tracking_only_key}"}

        forbidden = requests.get(f"{self.base_url}/api/v1/shipments", headers=tracking_only_headers, timeout=10)
        self.assertEqual(forbidden.status_code, 403)

        full_key = self._create_key("Lakefront Foods", ["shipments.read", "tracking.read", "rates.read"])
        full_headers = {"Authorization": f"Bearer {full_key}"}

        tms_routes.API_RATE_LIMITER._requests.clear()
        tms_routes.API_RATE_LIMITER.max_requests = 3

        statuses = []
        for _ in range(4):
            response = requests.get(f"{self.base_url}/api/v1/shipments", headers=full_headers, timeout=10)
            statuses.append(response.status_code)
        self.assertEqual(statuses[:3], [200, 200, 200])
        self.assertEqual(statuses[3], 429)

        revoke_response = requests.post(
            f"{self.base_url}/tms/api-keys",
            data={"action": "revoke", "key": full_key},
            timeout=10,
        )
        self.assertEqual(revoke_response.status_code, 200)

        revoked = requests.get(f"{self.base_url}/api/v1/shipments", headers=full_headers, timeout=10)
        self.assertEqual(revoked.status_code, 401)


if __name__ == "__main__":
    unittest.main()
