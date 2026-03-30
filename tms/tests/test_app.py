import tempfile
import unittest
from pathlib import Path

import pyotp
import tms_app.app as tms_app_module
from werkzeug.security import generate_password_hash

from tms_app import create_app
from tms_app.database import enable_totp, get_user_by_email, get_user_by_id


class TmsSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "test.db")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE_PATH": self.db_path,
                "SESSION_COOKIE_SECURE": False,
                "ALLOWED_HOSTS": set(),
                "TMS_ADMIN_EMAIL": "admin@example.com",
                "TMS_ADMIN_PASSWORD": "AdminPass123!",
                "TMS_ADMIN_NAME": "Admin User",
                "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                "TMS_DISPATCHER_NAME": "Dispatch User",
                "TMS_VIEWER_EMAIL": "viewer@example.com",
                "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                "TMS_VIEWER_NAME": "Viewer User",
                "TMS_OTP_ISSUER": "TMS Sandbox Test",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def _csrf_token(self, path):
        self.client.get(path)
        with self.client.session_transaction() as session_state:
            return session_state["csrf_token"]

    def _login_and_setup_mfa(self, email, password):
        csrf = self._csrf_token("/login")
        response = self.client.post(
            "/login",
            data={"tenant_id": "tenant-default", "email": email, "password": password, "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/mfa/setup"))
        self.client.get("/mfa/setup")
        with self.client.session_transaction() as session_state:
            secret = session_state["pending_totp_secret"]
            csrf = session_state["csrf_token"]
        response = self.client.post(
            "/mfa/setup",
            data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/password/change"))
        return self._complete_password_change(email)

    def _enable_existing_mfa(self, email, secret):
        with self.app.app_context():
            user = get_user_by_email(email)
            enable_totp(user["id"], secret)

    def _login_with_existing_mfa(self, email, password, secret):
        csrf = self._csrf_token("/login")
        response = self.client.post(
            "/login",
            data={"tenant_id": "tenant-default", "email": email, "password": password, "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/mfa/verify"))
        self.client.get("/mfa/verify")
        with self.client.session_transaction() as session_state:
            csrf = session_state["csrf_token"]
        response = self.client.post(
            "/mfa/verify",
            data={"code": pyotp.TOTP(secret).now(), "csrf_token": csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/password/change"))
        return self._complete_password_change(email)

    def _complete_password_change(self, email):
        local_part = email.split("@", 1)[0].title()
        new_password = f"{local_part}Reset123!"
        csrf = self._csrf_token("/password/change")
        response = self.client.post(
            "/password/change",
            data={
                "new_password": new_password,
                "confirm_password": new_password,
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/dashboard"))
        return new_password

    def test_first_login_requires_totp_setup(self):
        self._login_and_setup_mfa("admin@example.com", "AdminPass123!")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin workspace", response.data)

    def test_viewer_cannot_access_dispatch_or_admin(self):
        secret = pyotp.random_base32()
        self._enable_existing_mfa("viewer@example.com", secret)
        self._login_with_existing_mfa("viewer@example.com", "ViewerPass123!", secret)
        dispatch_response = self.client.get("/dispatch-board")
        admin_response = self.client.get("/admin/users")
        self.assertEqual(dispatch_response.status_code, 403)
        self.assertEqual(admin_response.status_code, 403)

    def test_admin_can_update_role_and_reset_mfa(self):
        admin_secret = pyotp.random_base32()
        viewer_secret = pyotp.random_base32()
        self._enable_existing_mfa("admin@example.com", admin_secret)
        self._enable_existing_mfa("viewer@example.com", viewer_secret)
        self._login_with_existing_mfa("admin@example.com", "AdminPass123!", admin_secret)
        csrf = self._csrf_token("/admin/users")
        with self.app.app_context():
            viewer = get_user_by_email("viewer@example.com")
            viewer_id = viewer["id"]
        update_response = self.client.post(
            "/admin/users",
            data={
                "action": "set_role",
                "user_id": str(viewer_id),
                "role": "dispatcher",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)
        csrf = self._csrf_token("/admin/users")
        reset_response = self.client.post(
            "/admin/users",
            data={
                "action": "reset_mfa",
                "user_id": str(viewer_id),
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(reset_response.status_code, 302)
        with self.app.app_context():
            viewer = get_user_by_id(viewer_id)
            self.assertEqual(viewer["role"], "dispatcher")
            self.assertEqual(viewer["totp_enabled"], 0)
            self.assertEqual(viewer["totp_secret"], "")

    def test_failed_login_locks_account_after_five_attempts(self):
        for attempt in range(5):
            csrf = self._csrf_token("/login")
            response = self.client.post(
                "/login",
                data={
                    "tenant_id": "tenant-default",
                    "email": "admin@example.com",
                    "password": "WrongPassword123!",
                    "csrf_token": csrf,
                },
                follow_redirects=False,
            )
            expected_status = 423 if attempt == 4 else 401
            self.assertEqual(response.status_code, expected_status)

    def test_session_timeout_redirects_to_login(self):
        secret = pyotp.random_base32()
        self._enable_existing_mfa("admin@example.com", secret)
        self._login_with_existing_mfa("admin@example.com", "AdminPass123!", secret)
        with self.client.session_transaction() as session_state:
            session_state["session_last_activity_at"] = "2000-01-01T00:00:00+00:00"
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/login"))

    def test_request_ip_ignores_raw_forwarded_for_header(self):
        with self.app.test_request_context(
            "/login",
            headers={"X-Forwarded-For": "198.51.100.7"},
            environ_base={"REMOTE_ADDR": "203.0.113.5"},
        ):
            self.assertEqual(tms_app_module._request_ip_address(), "203.0.113.5")

    def test_saml_stub_can_bootstrap_login_in_testing(self):
        response = self.client.get("/login/sso?tenant_id=tenant-default")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SAML 2.0 SSO Stub", response.data)

        acs_response = self.client.get(
            "/saml/acs?tenant_id=tenant-default&email=admin@example.com",
            follow_redirects=False,
        )
        self.assertEqual(acs_response.status_code, 302)
        self.assertTrue(acs_response.location.endswith("/password/change"))

    def test_login_accepts_hashed_seed_password_config(self):
        hashed_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE_PATH": str(Path(self.tempdir.name) / "hashed-test.db"),
                "SESSION_COOKIE_SECURE": False,
                "ALLOWED_HOSTS": set(),
                "TMS_ADMIN_EMAIL": "admin@example.com",
                "TMS_ADMIN_PASSWORD": "",
                "TMS_ADMIN_PASSWORD_HASH": generate_password_hash("AdminPass123!"),
                "TMS_ADMIN_NAME": "Admin User",
                "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                "TMS_DISPATCHER_NAME": "Dispatch User",
                "TMS_VIEWER_EMAIL": "viewer@example.com",
                "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                "TMS_VIEWER_NAME": "Viewer User",
                "TMS_OTP_ISSUER": "TMS Sandbox Test",
            }
        )
        hashed_client = hashed_app.test_client()
        hashed_client.get("/login")
        with hashed_client.session_transaction() as session_state:
            csrf = session_state["csrf_token"]
        response = hashed_client.post(
            "/login",
            data={
                "tenant_id": "tenant-default",
                "email": "admin@example.com",
                "password": "AdminPass123!",
                "csrf_token": csrf,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/mfa/setup"))

    def test_production_requires_strong_secret_and_hosts(self):
        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "change-me-for-local-dev",
                    "BASE_URL": "https://example.com",
                    "DATABASE_PATH": str(Path(self.tempdir.name) / "prod.db"),
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
                    "SECRET_KEY": "a" * 48,
                    "BASE_URL": "https://example.com",
                    "DATABASE_PATH": str(Path(self.tempdir.name) / "prod-2.db"),
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

    def test_production_rejects_placeholder_seed_passwords(self):
        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TMS_ENV": "production",
                    "SECRET_KEY": "b" * 48,
                    "BASE_URL": "https://example.com",
                    "DATABASE_PATH": str(Path(self.tempdir.name) / "prod-3.db"),
                    "SESSION_COOKIE_SECURE": True,
                    "ALLOWED_HOSTS": {"example.com"},
                    "TMS_ADMIN_EMAIL": "admin@example.com",
                    "TMS_ADMIN_PASSWORD": "ChangeMe-Admin1!",
                    "TMS_DISPATCHER_EMAIL": "dispatch@example.com",
                    "TMS_DISPATCHER_PASSWORD": "DispatchPass123!",
                    "TMS_VIEWER_EMAIL": "viewer@example.com",
                    "TMS_VIEWER_PASSWORD": "ViewerPass123!",
                }
            )

    def test_production_accepts_hashed_seed_password_config(self):
        hashed_production = create_app(
            {
                "TMS_ENV": "production",
                "SECRET_KEY": "c" * 48,
                "BASE_URL": "https://example.com",
                "DATABASE_PATH": str(Path(self.tempdir.name) / "prod-hash.db"),
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


if __name__ == "__main__":
    unittest.main()
