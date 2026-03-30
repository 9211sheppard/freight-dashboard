import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tms.tms_routes as tms_routes
from tms.full_app import create_app
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parents[2]


class FullAppTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "x" * 48,
                "TMS_ENV": "development",
                "TMS_DB_PATH": str(Path(self.tempdir.name) / "full-app.db"),
                "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods"),
                "INTEGRATION_MASTER_KEY": "k" * 48,
                "SESSION_COOKIE_SECURE": False,
                "ALLOWED_HOSTS": set(),
                "TMS_ENFORCE_CSRF": True,
                "TMS_ADMIN_EMAIL": "admin@example.com",
                "TMS_ADMIN_PASSWORD": "AdminPass123!",
                "TMS_ADMIN_NAME": "Admin User",
                "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                "TMS_VIEWER_EMAIL": "viewer@example.com",
                "TMS_VIEWER_PASSWORD": "ViewerPass123!",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def _csrf_token(self, path):
        self.client.get(path)
        with self.client.session_transaction() as session_state:
            return session_state["_csrf_token"]

    def test_login_sets_authenticated_session(self):
        csrf = self._csrf_token("/login")
        with mock.patch("tms.full_app.is_ip_locked", return_value=False):
            response = self.client.post(
                "/login",
                data={
                    "username": "admin@example.com",
                    "password": "AdminPass123!",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/tms/", response.location)
        with self.client.session_transaction() as session_state:
            self.assertTrue(session_state["logged_in"])
            self.assertEqual(session_state["user_role"], "admin")
            self.assertEqual(session_state["user_email"], "admin@example.com")

    def test_login_accepts_hashed_password_config(self):
        hashed_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "x" * 48,
                "TMS_ENV": "development",
                "TMS_DB_PATH": str(Path(self.tempdir.name) / "hashed-full-app.db"),
                "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods-hashed"),
                "INTEGRATION_MASTER_KEY": "k" * 48,
                "SESSION_COOKIE_SECURE": False,
                "ALLOWED_HOSTS": set(),
                "TMS_ENFORCE_CSRF": True,
                "TMS_ADMIN_EMAIL": "admin@example.com",
                "TMS_ADMIN_PASSWORD": "",
                "TMS_ADMIN_PASSWORD_HASH": generate_password_hash("AdminPass123!"),
                "TMS_ADMIN_NAME": "Admin User",
                "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                "TMS_VIEWER_EMAIL": "viewer@example.com",
                "TMS_VIEWER_PASSWORD": "ViewerPass123!",
            }
        )
        hashed_client = hashed_app.test_client()
        hashed_client.get("/login")
        with hashed_client.session_transaction() as session_state:
            csrf = session_state["_csrf_token"]

        with mock.patch("tms.full_app.is_ip_locked", return_value=False):
            response = hashed_client.post(
                "/login",
                data={
                    "username": "admin@example.com",
                    "password": "AdminPass123!",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/tms/", response.location)

    def test_production_requires_strong_secret_and_hosts(self):
        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "change-me-for-local-dev",
                    "INTEGRATION_MASTER_KEY": "k" * 48,
                    "BASE_URL": "https://example.com",
                    "TMS_DB_PATH": str(Path(self.tempdir.name) / "prod.db"),
                    "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                    "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods"),
                    "SESSION_COOKIE_SECURE": True,
                    "ALLOWED_HOSTS": {"example.com"},
                    "TMS_ADMIN_EMAIL": "admin@example.com",
                    "TMS_ADMIN_PASSWORD": "AdminPass123!",
                    "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                    "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                    "TMS_VIEWER_EMAIL": "viewer@example.com",
                    "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                }
            )

        hashed_production = create_app(
            {
                "TESTING": True,
                "TMS_ENV": "production",
                "SECRET_KEY": "z" * 48,
                "INTEGRATION_MASTER_KEY": "k" * 48,
                "BASE_URL": "https://example.com",
                "TMS_DB_PATH": str(Path(self.tempdir.name) / "prod-hash.db"),
                "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods-prod-hash"),
                "SESSION_COOKIE_SECURE": True,
                "ALLOWED_HOSTS": {"example.com"},
                "TMS_ADMIN_EMAIL": "admin@example.com",
                "TMS_ADMIN_PASSWORD": "",
                "TMS_ADMIN_PASSWORD_HASH": generate_password_hash("AdminPass123!"),
                "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                "TMS_VIEWER_EMAIL": "viewer@example.com",
                "TMS_VIEWER_PASSWORD": "ViewerPass123!",
            }
        )
        self.assertTrue(hashed_production.config["TMS_ADMIN_PASSWORD_HASH"])

    def test_login_respects_bruteforce_lockout(self):
        csrf = self._csrf_token("/login")
        with mock.patch("tms.full_app.is_ip_locked", side_effect=[False, True]), mock.patch(
            "tms.full_app.record_login_attempt"
        ) as record_attempt:
            failed = self.client.post(
                "/login",
                data={
                    "username": "admin@example.com",
                    "password": "wrong-password",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
            self.assertEqual(failed.status_code, 200)
            self.assertIn(b"Invalid username or password.", failed.data)
            record_attempt.assert_called_once_with("127.0.0.1", "admin@example.com", False)

            locked = self.client.post(
                "/login",
                data={
                    "username": "admin@example.com",
                    "password": "AdminPass123!",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
            self.assertEqual(locked.status_code, 423)
            self.assertIn(b"Too many login attempts. Try again later.", locked.data)

    def test_portal_login_requires_csrf(self):
        from tms import tms_db

        tms_db.save_portal_token(
            token="PORTAL-111222",
            customer_name="Portal Customer",
            email="portal@example.com",
            shipment_refs=[],
        )

        missing_csrf = self.client.post(
            "/portal/login",
            data={"access_code": "111222"},
            follow_redirects=False,
        )
        self.assertEqual(missing_csrf.status_code, 400)

        csrf = self._csrf_token("/portal/login")
        with mock.patch("tms.tms_routes.is_ip_locked", return_value=False):
            valid = self.client.post(
                "/portal/login",
                data={"access_code": "111222", "csrf_token": csrf},
                follow_redirects=False,
            )
        self.assertEqual(valid.status_code, 302)
        self.assertIn("/portal/PORTAL-111222/", valid.location)

    def test_portal_logout_requires_post_when_csrf_is_enforced(self):
        from tms import tms_db

        tms_db.save_portal_token(
            token="PORTAL-111222",
            customer_name="Portal Customer",
            email="portal@example.com",
            shipment_refs=[],
        )

        csrf = self._csrf_token("/portal/login")
        with self.client.session_transaction() as session_state:
            session_state["portal_token"] = "PORTAL-111222"

        blocked = self.client.get("/portal/logout", follow_redirects=False)
        self.assertEqual(blocked.status_code, 405)

        valid = self.client.post(
            "/portal/logout",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(valid.status_code, 302)
        self.assertIn("/portal/login", valid.location)
        with self.client.session_transaction() as session_state:
            self.assertNotIn("portal_token", session_state)

    def test_office_logout_requires_post_when_csrf_is_enforced(self):
        csrf = self._csrf_token("/login")
        with mock.patch("tms.full_app.is_ip_locked", return_value=False):
            valid_login = self.client.post(
                "/login",
                data={
                    "username": "admin@example.com",
                    "password": "AdminPass123!",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
        self.assertEqual(valid_login.status_code, 302)

        blocked = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(blocked.status_code, 405)

        missing_csrf = self.client.post("/logout", data={}, follow_redirects=False)
        self.assertEqual(missing_csrf.status_code, 400)

        csrf = self._csrf_token("/health")
        valid_logout = self.client.post("/logout", data={"csrf_token": csrf}, follow_redirects=False)
        self.assertEqual(valid_logout.status_code, 302)
        self.assertTrue(valid_logout.location.endswith("/login"))
        with self.client.session_transaction() as session_state:
            self.assertFalse(session_state.get("logged_in"))

    def test_public_tracking_route_is_auth_exempt_but_requires_signed_link(self):
        from tms import tms_db

        tms_db.preload_demo_data()

        blocked = self.client.get("/track/TMS-DEMO-003", follow_redirects=False)
        self.assertEqual(blocked.status_code, 403)

        with self.app.test_request_context():
            signed_url = tms_routes.build_public_tracking_url("TMS-DEMO-003")

        allowed = self.client.get(signed_url, follow_redirects=False)
        self.assertEqual(allowed.status_code, 200)
        self.assertIn(b"TMS-DEMO-003", allowed.data)

    def test_tracking_search_requires_login(self):
        response = self.client.get("/tms/track", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "y" * 48,
                    "INTEGRATION_MASTER_KEY": "k" * 48,
                    "BASE_URL": "https://example.com",
                    "TMS_DB_PATH": str(Path(self.tempdir.name) / "prod-2.db"),
                    "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                    "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods"),
                    "SESSION_COOKIE_SECURE": True,
                    "ALLOWED_HOSTS": set(),
                    "TMS_ADMIN_EMAIL": "admin@example.com",
                    "TMS_ADMIN_PASSWORD": "AdminPass123!",
                    "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                    "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                    "TMS_VIEWER_EMAIL": "viewer@example.com",
                    "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                }
            )

        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "y" * 48,
                    "INTEGRATION_MASTER_KEY": "",
                    "BASE_URL": "https://example.com",
                    "TMS_DB_PATH": str(Path(self.tempdir.name) / "prod-3.db"),
                    "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                    "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods"),
                    "SESSION_COOKIE_SECURE": True,
                    "ALLOWED_HOSTS": {"example.com"},
                    "TMS_ADMIN_EMAIL": "admin@example.com",
                    "TMS_ADMIN_PASSWORD": "AdminPass123!",
                    "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                    "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                    "TMS_VIEWER_EMAIL": "viewer@example.com",
                    "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                }
            )

        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "y" * 48,
                    "INTEGRATION_MASTER_KEY": "k" * 48,
                    "BASE_URL": "https://wrong.example.com",
                    "TMS_DB_PATH": str(Path(self.tempdir.name) / "prod-5.db"),
                    "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                    "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods"),
                    "SESSION_COOKIE_SECURE": True,
                    "ALLOWED_HOSTS": {"example.com"},
                    "TMS_ADMIN_EMAIL": "admin@example.com",
                    "TMS_ADMIN_PASSWORD": "AdminPass123!",
                    "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                    "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                    "TMS_VIEWER_EMAIL": "viewer@example.com",
                    "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                }
            )

        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "y" * 48,
                    "INTEGRATION_MASTER_KEY": "k" * 48,
                    "BASE_URL": "http://example.com",
                    "TMS_DB_PATH": str(Path(self.tempdir.name) / "prod-4.db"),
                    "TMS_CONTACTS_DB_PATH": str(ROOT / "data" / "contacts.db"),
                    "TMS_POD_UPLOAD_DIR": str(Path(self.tempdir.name) / "uploads" / "pods"),
                    "SESSION_COOKIE_SECURE": True,
                    "ALLOWED_HOSTS": {"example.com"},
                    "TMS_ADMIN_EMAIL": "admin@example.com",
                    "TMS_ADMIN_PASSWORD": "AdminPass123!",
                    "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                    "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                    "TMS_VIEWER_EMAIL": "viewer@example.com",
                    "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                }
            )


if __name__ == "__main__":
    unittest.main()
