import os
import secrets
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash

from . import portal as portal_blueprint
from . import public as public_blueprint
from . import tms as tms_blueprint
from .soc2 import is_ip_locked, record_login_attempt
from . import tms_db


STARTUP_TIME = str(int(time.time()))
APP_NAME = "TMS Master"
PUBLIC_TMS_ENDPOINTS = {
    "tms.capture_pod",
    "tms.carrier_dock_booking",
    "tms.customer_track",
    "tms.driver_checkin",
    "tms.driver_message_reply",
    "tms.driver_tracking_page",
    "tms.fuel_surcharge_calc",
    "tms.order_submit",
    "tms.pod_photo",
    "tms.pod_submission",
    "tms.pricing_page",
    "tms.respond_to_tender",
    "tms.tracking_ping",
}
WEAK_SECRET_KEYS = {
    "",
    "change-me",
    "change-me-for-local-dev",
    "replace-with-a-long-random-secret",
    "tms-master-dev-change-me",
}
WEAK_PASSWORD_MARKERS = (
    "changeme",
    "change-me",
    "replace-this",
    "replacewith",
    "sandbox",
)
SUPPORTED_PASSWORD_HASH_PREFIXES = ("pbkdf2:", "scrypt:")
SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _split_hosts(raw_value):
    return {
        host.strip().lower()
        for host in str(raw_value or "").split(",")
        if host.strip()
    }


def _is_production_mode(app):
    return str(app.config.get("TMS_ENV", "development") or "").strip().lower() == "production"


def _looks_like_placeholder_password(value):
    normalized = str(value or "").strip().lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in WEAK_PASSWORD_MARKERS)


def _looks_like_password_hash(value):
    normalized = str(value or "").strip().lower()
    return normalized.startswith(SUPPORTED_PASSWORD_HASH_PREFIXES)


def _configured_users(app):
    users = []
    for role, email_key, password_key, password_hash_key, name_key in (
        ("admin", "TMS_ADMIN_EMAIL", "TMS_ADMIN_PASSWORD", "TMS_ADMIN_PASSWORD_HASH", "TMS_ADMIN_NAME"),
        (
            "dispatcher",
            "TMS_DISPATCHER_EMAIL",
            "TMS_DISPATCHER_PASSWORD",
            "TMS_DISPATCHER_PASSWORD_HASH",
            "TMS_DISPATCHER_NAME",
        ),
        ("viewer", "TMS_VIEWER_EMAIL", "TMS_VIEWER_PASSWORD", "TMS_VIEWER_PASSWORD_HASH", "TMS_VIEWER_NAME"),
    ):
        email = str(app.config.get(email_key, "") or "").strip()
        password = str(app.config.get(password_key, "") or "")
        password_hash = str(app.config.get(password_hash_key, "") or "").strip()
        if not email or not (password or password_hash):
            continue
        users.append(
            {
                "role": role,
                "email": email,
                "password": password_hash or password,
                "password_is_hash": bool(password_hash) or _looks_like_password_hash(password),
                "name": str(app.config.get(name_key, "") or "").strip() or email,
            }
        )
    return users


def _user_identifiers(user):
    email = str((user or {}).get("email", "") or "").strip()
    identifiers = {email.lower()}
    if "@" in email:
        identifiers.add(email.split("@", 1)[0].lower())
    return identifiers


def _require_allowed_host(app):
    allowed_hosts = app.config.get("ALLOWED_HOSTS") or set()
    if not allowed_hosts:
        return
    host = (request.host or "").split(":", 1)[0].strip().lower()
    if host and host in allowed_hosts:
        return
    abort(400, description="Host is not allowed.")


def _request_ip_address():
    return (request.remote_addr or "").strip()


def _csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(16)
        session["_csrf_token"] = token
    return token


def _validate_csrf_token():
    expected = session.get("_csrf_token")
    provided = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or ((request.get_json(silent=True) or {}).get("csrf_token") if request.is_json else "")
    )
    if not expected or not provided or not secrets.compare_digest(str(expected), str(provided)):
        abort(400, description="Invalid CSRF token.")


def _csrf_exempt_request():
    if request.method in SAFE_HTTP_METHODS:
        return True
    if request.endpoint in {"static", "login", "health"}:
        return True
    if request.path.startswith("/static/"):
        return True
    if request.blueprint == "public":
        return True
    if request.endpoint in PUBLIC_TMS_ENDPOINTS:
        return True
    return False


def _auth_exempt_request():
    if request.endpoint in {"static", "login", "logout", "health", "public_tracking"}:
        return True
    if request.path.startswith("/static/"):
        return True
    if request.blueprint in {"portal", "public"}:
        return True
    if request.endpoint in PUBLIC_TMS_ENDPOINTS:
        return True
    return False


def _safe_next_url(value):
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("tms.dashboard")


def _login_session(app, user):
    session.clear()
    session["logged_in"] = True
    session["user_role"] = user["role"]
    session["user_id"] = user["email"]
    session["user_email"] = user["email"]
    session["company_name"] = app.config["BRAND_NAME"]
    session.permanent = True
    _csrf_token()


def _password_matches(user, candidate_password):
    stored_password = str((user or {}).get("password", "") or "")
    if not stored_password:
        return False
    if (user or {}).get("password_is_hash") or _looks_like_password_hash(stored_password):
        try:
            return check_password_hash(stored_password, str(candidate_password or ""))
        except ValueError:
            return False
    return secrets.compare_digest(stored_password, str(candidate_password or ""))


def _authenticate_user(app, username, password):
    normalized_username = str(username or "").strip().lower()
    for user in _configured_users(app):
        if normalized_username in _user_identifiers(user) and _password_matches(user, password):
            return user
    return None


def _validate_startup_config(app):
    if app.config.get("TESTING"):
        return
    if not _is_production_mode(app):
        return

    secret_key = str(app.config.get("SECRET_KEY", "") or "")
    if secret_key in WEAK_SECRET_KEYS or len(secret_key) < 32:
        raise RuntimeError("Production requires a strong SECRET_KEY with at least 32 characters.")
    integration_master_key = str(app.config.get("INTEGRATION_MASTER_KEY", "") or "")
    if integration_master_key in WEAK_SECRET_KEYS or len(integration_master_key) < 32:
        raise RuntimeError("Production requires a strong INTEGRATION_MASTER_KEY with at least 32 characters.")
    base_url = str(app.config.get("BASE_URL", "") or "").strip()
    if not base_url or not base_url.lower().startswith("https://"):
        raise RuntimeError("Production requires BASE_URL to be set to the HTTPS site URL.")
    base_host = (urlparse(base_url).hostname or "").strip().lower()
    allowed_hosts = set(app.config.get("ALLOWED_HOSTS") or set())
    if not base_host or base_host not in allowed_hosts:
        raise RuntimeError("Production requires BASE_URL host to be included in TMS_ALLOWED_HOSTS.")
    if not app.config.get("SESSION_COOKIE_SECURE"):
        raise RuntimeError("Production requires SESSION_COOKIE_SECURE=true.")
    if not allowed_hosts:
        raise RuntimeError("Production requires TMS_ALLOWED_HOSTS to be set.")

    for email_key, password_key, password_hash_key in (
        ("TMS_ADMIN_EMAIL", "TMS_ADMIN_PASSWORD", "TMS_ADMIN_PASSWORD_HASH"),
        ("TMS_DISPATCHER_EMAIL", "TMS_DISPATCHER_PASSWORD", "TMS_DISPATCHER_PASSWORD_HASH"),
        ("TMS_VIEWER_EMAIL", "TMS_VIEWER_PASSWORD", "TMS_VIEWER_PASSWORD_HASH"),
    ):
        email_value = str(app.config.get(email_key, "") or "").strip()
        password_value = str(app.config.get(password_key, "") or "")
        password_hash_value = str(app.config.get(password_hash_key, "") or "").strip()
        if not email_value:
            raise RuntimeError(f"Production requires {email_key} to be set.")
        if password_hash_value:
            if not _looks_like_password_hash(password_hash_value):
                raise RuntimeError(f"Production requires {password_hash_key} to use a supported hash format.")
            continue
        if _looks_like_placeholder_password(password_value):
            raise RuntimeError(f"Production requires a non-placeholder value for {password_key}.")


def create_app(test_config=None):
    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"), static_folder=str(Path(__file__).resolve().parents[1] / "static"))
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "change-me-for-local-dev"),
        BASE_URL=(os.getenv("BASE_URL", "") or "").rstrip("/"),
        INTEGRATION_MASTER_KEY=os.getenv("INTEGRATION_MASTER_KEY", ""),
        BRAND_NAME=os.getenv("TMS_BRAND_NAME", APP_NAME),
        TMS_ENV=os.getenv("TMS_ENV", "development"),
        TMS_DB_PATH=os.getenv("TMS_DB_PATH", str(Path(__file__).resolve().parent / "tms.db")),
        TMS_CONTACTS_DB_PATH=os.getenv(
            "TMS_CONTACTS_DB_PATH",
            str(Path(__file__).resolve().parents[1] / "data" / "contacts.db"),
        ),
        TMS_POD_UPLOAD_DIR=os.getenv(
            "TMS_POD_UPLOAD_DIR",
            str(Path(__file__).resolve().parent / "uploads" / "pods"),
        ),
        TMS_ADMIN_EMAIL=os.getenv("TMS_ADMIN_EMAIL", "admin"),
        TMS_ADMIN_PASSWORD=os.getenv("TMS_ADMIN_PASSWORD", "change-me"),
        TMS_ADMIN_PASSWORD_HASH=os.getenv("TMS_ADMIN_PASSWORD_HASH", ""),
        TMS_ADMIN_NAME=os.getenv("TMS_ADMIN_NAME", "Primary Admin"),
        TMS_DISPATCHER_EMAIL=os.getenv("TMS_DISPATCHER_EMAIL", "dispatch"),
        TMS_DISPATCHER_PASSWORD=os.getenv("TMS_DISPATCHER_PASSWORD", "change-me"),
        TMS_DISPATCHER_PASSWORD_HASH=os.getenv("TMS_DISPATCHER_PASSWORD_HASH", ""),
        TMS_DISPATCHER_NAME=os.getenv("TMS_DISPATCHER_NAME", "Primary Dispatcher"),
        TMS_VIEWER_EMAIL=os.getenv("TMS_VIEWER_EMAIL", "viewer"),
        TMS_VIEWER_PASSWORD=os.getenv("TMS_VIEWER_PASSWORD", "change-me"),
        TMS_VIEWER_PASSWORD_HASH=os.getenv("TMS_VIEWER_PASSWORD_HASH", ""),
        TMS_VIEWER_NAME=os.getenv("TMS_VIEWER_NAME", "Primary Viewer"),
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_CONTENT_LENGTH_MB", "25")) * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_truthy(
            os.getenv("SESSION_COOKIE_SECURE"),
            default=os.getenv("TMS_ENV", "development").strip().lower() == "production",
        ),
        PREFERRED_URL_SCHEME="https",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=int(os.getenv("SESSION_LIFETIME_HOURS", "12"))),
        ALLOWED_HOSTS=_split_hosts(os.getenv("TMS_ALLOWED_HOSTS", "")),
        TMS_ENFORCE_ROUTE_AUTH=_truthy(
            os.getenv("TMS_ENFORCE_ROUTE_AUTH"),
            default=os.getenv("TMS_ENV", "development").strip().lower() == "production",
        ),
        TMS_ALLOW_REQUEST_TENANT_OVERRIDE=_truthy(
            os.getenv("TMS_ALLOW_REQUEST_TENANT_OVERRIDE"),
            default=os.getenv("TMS_ENV", "development").strip().lower() != "production",
        ),
        TMS_ALLOW_REQUEST_ACTOR_OVERRIDE=_truthy(
            os.getenv("TMS_ALLOW_REQUEST_ACTOR_OVERRIDE"),
            default=os.getenv("TMS_ENV", "development").strip().lower() != "production",
        ),
        TMS_ENFORCE_CSRF=_truthy(
            os.getenv("TMS_ENFORCE_CSRF"),
            default=os.getenv("TMS_ENV", "development").strip().lower() == "production",
        ),
        TMS_ENABLE_EDI_WATCHER=_truthy(os.getenv("TMS_ENABLE_EDI_WATCHER"), default=False),
    )
    if test_config:
        app.config.update(test_config)

    _validate_startup_config(app)

    Path(app.config["TMS_DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["TMS_CONTACTS_DB_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config["TMS_POD_UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    tms_db.TMS_DB = str(app.config["TMS_DB_PATH"])
    tms_db.CONTACTS_DB = str(app.config["TMS_CONTACTS_DB_PATH"])
    tms_db.POD_UPLOAD_DIR = str(app.config["TMS_POD_UPLOAD_DIR"])

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    init_tms = getattr(tms_db, "init_tms_db")
    init_tms()

    app.register_blueprint(tms_blueprint)
    app.register_blueprint(portal_blueprint)
    app.register_blueprint(public_blueprint)

    @app.before_request
    def protect_request():
        _require_allowed_host(app)
        g.csp_nonce = secrets.token_hex(16)
        session.setdefault("company_name", app.config["BRAND_NAME"])

        if app.config.get("TMS_ENFORCE_CSRF") and not _csrf_exempt_request():
            _validate_csrf_token()

        if _auth_exempt_request():
            return None
        if session.get("logged_in"):
            return None
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_url))

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers.setdefault("Cache-Control", "no-store")
        nonce = getattr(g, "csp_nonce", "")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            f"script-src 'self' 'nonce-{nonce}' https://unpkg.com; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "manifest-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.context_processor
    def inject_globals():
        return {
            "brand_name": app.config["BRAND_NAME"],
            "csp_nonce": getattr(g, "csp_nonce", ""),
            "csrf_token": _csrf_token,
            "sv": STARTUP_TIME,
        }

    @app.route("/")
    def index():
        if session.get("logged_in"):
            return redirect(url_for("tms.dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("logged_in"):
            return redirect(url_for("tms.dashboard"))

        next_url = _safe_next_url(request.values.get("next"))
        error = None
        entered_username = (request.form.get("username") or request.form.get("email") or "").strip()
        request_ip = _request_ip_address()

        if request.method == "POST":
            if app.config.get("TMS_ENFORCE_CSRF"):
                _validate_csrf_token()
            if is_ip_locked(request_ip):
                return (
                    render_template(
                        "login.html",
                        error="Too many login attempts. Try again later.",
                        next_url=next_url,
                        entered_username=entered_username,
                    ),
                    423,
                )
            user = _authenticate_user(app, entered_username, request.form.get("password") or "")
            if user:
                record_login_attempt(request_ip, entered_username, True)
                _login_session(app, user)
                return redirect(next_url)
            record_login_attempt(request_ip, entered_username, False)
            error = "Invalid username or password."

        return render_template(
            "login.html",
            error=error,
            next_url=next_url,
            entered_username=entered_username,
        )

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        if request.method == "GET" and app.config.get("TMS_ENFORCE_CSRF"):
            abort(405)
        session.clear()
        return redirect(url_for("login"))

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "product": app.config["BRAND_NAME"], "mode": "full"}), 200

    @app.route("/track/<ref>", endpoint="public_tracking")
    def public_tracking(ref):
        return app.view_functions["tms.customer_track"](ref)

    return app
