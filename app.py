import os
import secrets
import time
from datetime import timedelta

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for

from config import (
    APP_NAME,
    LOGIN_PASSWORD,
    LOGIN_USERNAME,
    MAX_CONTENT_LENGTH_MB,
    PORT,
    SECRET_KEY,
    SESSION_LIFETIME_HOURS,
)
from tms import portal as portal_blueprint
from tms import public as public_blueprint
from tms import tms as tms_blueprint
from tms.tms_db import init_tms_db


STARTUP_TIME = str(int(time.time()))
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


def _safe_next_url(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("tms.dashboard")


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(16)
        session["_csrf_token"] = token
    return token


def _login_session(username: str) -> None:
    session.clear()
    session["logged_in"] = True
    session["user_role"] = "admin"
    session["user_id"] = username
    session["user_email"] = username
    session["company_name"] = APP_NAME
    session.permanent = True


def create_app():
    if os.getenv("TMS_ENV", "development").strip().lower() == "production":
        raise RuntimeError(
            "The legacy root app is disabled in production. Deploy the hardened service from tms/wsgi.py instead."
        )

    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=SESSION_LIFETIME_HOURS)

    init_tms_db()

    app.register_blueprint(tms_blueprint)
    app.register_blueprint(portal_blueprint)
    app.register_blueprint(public_blueprint)

    @app.before_request
    def require_login():
        g.csp_nonce = secrets.token_hex(16)
        session.setdefault("company_name", APP_NAME)

        if request.endpoint in {"static", "login", "logout", "health", "public_tracking"}:
            return None
        if request.path.startswith("/static/"):
            return None
        if request.blueprint in {"portal", "public"}:
            return None
        if request.endpoint in PUBLIC_TMS_ENDPOINTS:
            return None
        if session.get("logged_in"):
            return None
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_url))

    @app.context_processor
    def inject_globals():
        return {
            "brand_name": APP_NAME,
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

        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
                _login_session(username)
                return redirect(next_url)
            error = "Invalid username or password."

        return render_template("login.html", error=error, next_url=next_url)

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        if request.method == "GET" and app.config.get("TMS_ENFORCE_CSRF"):
            abort(405)
        session.clear()
        return redirect(url_for("login"))

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "product": APP_NAME}), 200

    @app.route("/track/<ref>", endpoint="public_tracking")
    def public_tracking(ref):
        return app.view_functions["tms.customer_track"](ref)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
