import csv
import io
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from .database import (
    ROLE_CHOICES,
    attempt_password_login,
    change_password,
    create_tenant,
    enable_totp,
    get_tenant_by_id,
    get_user_by_id,
    init_app as init_db_app,
    list_audit_entries,
    list_tenants,
    list_users,
    note_audit,
    record_login,
    reset_totp,
    update_role,
    update_tenant_status,
)
from .enterprise import build_saml_stub_context, is_ip_allowed, validate_password_complexity
from .security import (
    ROLE_LABELS,
    build_totp_qr_data_uri,
    build_totp_uri,
    clear_login_state,
    complete_login,
    generate_csrf_token,
    generate_totp_secret,
    login_required,
    require_allowed_host,
    roles_required,
    validate_csrf_token,
    verify_totp_code,
)


SAMPLE_LOADS = [
    {
        "reference": "SBX-2041",
        "lane": "Toronto, ON -> Dallas, TX",
        "mode": "FTL",
        "status": "Booked",
        "eta": "2026-03-27 14:00 UTC",
        "priority": "High",
    },
    {
        "reference": "SBX-2048",
        "lane": "Montreal, QC -> Newark, NJ",
        "mode": "LTL",
        "status": "Customs Hold",
        "eta": "2026-03-26 18:30 UTC",
        "priority": "High",
    },
    {
        "reference": "SBX-2052",
        "lane": "Vancouver, BC -> Phoenix, AZ",
        "mode": "Rail",
        "status": "In Transit",
        "eta": "2026-03-29 08:45 UTC",
        "priority": "Medium",
    },
    {
        "reference": "SBX-2059",
        "lane": "Chicago, IL -> Calgary, AB",
        "mode": "Drayage",
        "status": "Awaiting Pickup",
        "eta": "2026-03-26 16:15 UTC",
        "priority": "Medium",
    },
]


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _request_ip_address():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr or ""


def _session_timed_out(last_activity_at, timeout_minutes):
    if not last_activity_at:
        return False
    try:
        last_activity = datetime.fromisoformat(last_activity_at)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - last_activity).total_seconds() > (timeout_minutes * 60)


def create_app(test_config=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "change-me-for-local-dev"),
        DATABASE_PATH=os.getenv(
            "TMS_DB_PATH",
            str(Path(__file__).resolve().parent.parent / "data" / "tms.db"),
        ),
        TMS_ENV=os.getenv("TMS_ENV", "development"),
        TMS_OTP_ISSUER=os.getenv("TMS_OTP_ISSUER", "TMS Sandbox"),
        TMS_DEFAULT_TENANT_ID=os.getenv("TMS_DEFAULT_TENANT_ID", "tenant-default"),
        TMS_DEFAULT_TENANT_NAME=os.getenv("TMS_DEFAULT_TENANT_NAME", "Sandbox Tenant"),
        TMS_ADMIN_EMAIL=os.getenv("TMS_ADMIN_EMAIL", "admin@tms.local"),
        TMS_ADMIN_PASSWORD=os.getenv("TMS_ADMIN_PASSWORD", "ChangeMe-Admin1!"),
        TMS_ADMIN_NAME=os.getenv("TMS_ADMIN_NAME", "Sandbox Admin"),
        TMS_DISPATCHER_EMAIL=os.getenv("TMS_DISPATCHER_EMAIL", "dispatcher@tms.local"),
        TMS_DISPATCHER_PASSWORD=os.getenv("TMS_DISPATCHER_PASSWORD", "ChangeMe-Dispatch1!"),
        TMS_DISPATCHER_NAME=os.getenv("TMS_DISPATCHER_NAME", "Sandbox Dispatcher"),
        TMS_VIEWER_EMAIL=os.getenv("TMS_VIEWER_EMAIL", "viewer@tms.local"),
        TMS_VIEWER_PASSWORD=os.getenv("TMS_VIEWER_PASSWORD", "ChangeMe-Viewer1!"),
        TMS_VIEWER_NAME=os.getenv("TMS_VIEWER_NAME", "Sandbox Viewer"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_truthy(os.getenv("SESSION_COOKIE_SECURE"), default=False),
        PREFERRED_URL_SCHEME="https",
        ALLOWED_HOSTS={
            host.strip().lower()
            for host in os.getenv("TMS_ALLOWED_HOSTS", "").split(",")
            if host.strip()
        },
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    init_db_app(app)

    @app.before_request
    def load_current_user():
        require_allowed_host()
        requested_tenant_id = (
            request.values.get("tenant_id")
            or session.get("tenant_id")
            or app.config["TMS_DEFAULT_TENANT_ID"]
        )
        g.current_tenant = get_tenant_by_id(requested_tenant_id)
        user_id = session.get("user_id")
        g.current_user = get_user_by_id(user_id) if user_id else None
        if user_id and not g.current_user:
            clear_login_state()
        if g.current_user:
            g.current_tenant = get_tenant_by_id(g.current_user["tenant_id"])
            if not g.current_tenant or g.current_tenant["status"] != "active":
                clear_login_state()
                flash("Your tenant is not active.", "error")
                return redirect(url_for("login"))
            if not is_ip_allowed(_request_ip_address(), g.current_tenant.get("allowed_ip_cidrs")):
                note_audit(
                    g.current_user["tenant_id"],
                    g.current_user["id"],
                    "BLOCKED_IP",
                    "tenants",
                    g.current_user["tenant_id"],
                    {"ip": _request_ip_address()},
                    ip=_request_ip_address(),
                )
                clear_login_state()
                abort(403, description="Your network is not allowed for this tenant.")
            if _session_timed_out(
                session.get("session_last_activity_at"),
                g.current_tenant.get("session_timeout_minutes", 30),
            ):
                note_audit(
                    g.current_user["tenant_id"],
                    g.current_user["id"],
                    "SESSION_TIMEOUT",
                    "users",
                    g.current_user["id"],
                    {"timeout_minutes": g.current_tenant.get("session_timeout_minutes", 30)},
                    ip=_request_ip_address(),
                )
                clear_login_state()
                flash("Your session timed out.", "error")
                return redirect(url_for("login"))
            session["session_last_activity_at"] = datetime.now(timezone.utc).isoformat()
        if request.method == "POST" and request.endpoint != "saml_acs":
            validate_csrf_token()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self'; "
            "script-src 'self'; "
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
            "csrf_token": generate_csrf_token(),
            "current_user": g.get("current_user"),
            "current_tenant": g.get("current_tenant"),
            "role_labels": ROLE_LABELS,
        }

    def finalize_authenticated_user(user, tenant, success_message):
        record_login(user["id"], ip=_request_ip_address())
        refreshed_user = get_user_by_id(user["id"])
        if refreshed_user["password_change_required"]:
            session.clear()
            session["password_change_user_id"] = refreshed_user["id"]
            session["password_change_tenant_id"] = tenant["tenant_id"]
            flash("Change your password before entering the workspace.", "warning")
            return redirect(url_for("password_change"))
        complete_login(refreshed_user, tenant)
        flash(success_message, "success")
        return redirect(url_for("dashboard"))

    @app.route("/")
    def index():
        if g.get("current_user"):
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.get("current_user"):
            return redirect(url_for("dashboard"))
        tenant_id = (
            request.form.get("tenant_id")
            or request.args.get("tenant_id")
            or session.get("tenant_id")
            or app.config["TMS_DEFAULT_TENANT_ID"]
        )
        tenant = get_tenant_by_id(tenant_id)
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            tenant_id = request.form.get("tenant_id", app.config["TMS_DEFAULT_TENANT_ID"]).strip() or app.config["TMS_DEFAULT_TENANT_ID"]
            tenant = get_tenant_by_id(tenant_id)
            if not tenant or tenant["status"] != "active":
                flash("That tenant is not active.", "error")
                return render_template("login.html", tenant_id=tenant_id), 403
            if not is_ip_allowed(_request_ip_address(), tenant.get("allowed_ip_cidrs")):
                note_audit(
                    tenant["tenant_id"],
                    email,
                    "BLOCKED_IP",
                    "tenants",
                    tenant["tenant_id"],
                    {"ip": _request_ip_address()},
                    ip=_request_ip_address(),
                )
                flash("Your IP address is not on the tenant allowlist.", "error")
                return render_template("login.html", tenant_id=tenant_id), 403
            result = attempt_password_login(email, password, tenant_id=tenant["tenant_id"], ip=_request_ip_address())
            user = result["user"]
            if result["error"] == "locked":
                flash("Account locked after too many failed attempts. Try again later.", "error")
                return render_template("login.html", tenant_id=tenant_id), 423
            if not user:
                flash("Invalid email or password.", "error")
                return render_template("login.html", tenant_id=tenant_id), 401
            session.clear()
            session["tenant_id"] = tenant["tenant_id"]
            if user["totp_enabled"]:
                session["preauth_user_id"] = user["id"]
                session["preauth_tenant_id"] = tenant["tenant_id"]
                session["preauth_step"] = "verify"
                flash("Password accepted. Enter your Google Authenticator code.", "info")
                return redirect(url_for("mfa_verify"))
            session["mfa_setup_user_id"] = user["id"]
            session["mfa_setup_tenant_id"] = tenant["tenant_id"]
            session["preauth_step"] = "setup"
            flash("Scan the QR code and confirm one 6-digit code to finish setup.", "info")
            return redirect(url_for("mfa_setup"))
        return render_template("login.html", tenant_id=tenant["tenant_id"] if tenant else tenant_id)

    @app.route("/mfa/setup", methods=["GET", "POST"])
    def mfa_setup():
        user_id = session.get("mfa_setup_user_id")
        tenant = get_tenant_by_id(session.get("mfa_setup_tenant_id") or session.get("tenant_id"))
        if not user_id:
            return redirect(url_for("login"))
        user = get_user_by_id(user_id)
        if not user or not tenant:
            clear_login_state()
            return redirect(url_for("login"))
        secret = session.get("pending_totp_secret")
        if not secret:
            secret = generate_totp_secret()
            session["pending_totp_secret"] = secret
        qr_uri = build_totp_uri(user["email"], secret)
        qr_code_data_uri = build_totp_qr_data_uri(qr_uri)
        if request.method == "POST":
            code = request.form.get("code", "")
            if not verify_totp_code(secret, code):
                flash("That code did not verify. Try the latest 6-digit code.", "error")
                return (
                    render_template(
                        "mfa_setup.html",
                        user=user,
                        qr_uri=qr_uri,
                        qr_code_data_uri=qr_code_data_uri,
                        manual_secret=secret,
                    ),
                    401,
                )
            enable_totp(user["id"], secret, ip=_request_ip_address())
            return finalize_authenticated_user(user, tenant, "MFA enabled. Your sandbox account is ready.")
        return render_template(
            "mfa_setup.html",
            user=user,
            qr_uri=qr_uri,
            qr_code_data_uri=qr_code_data_uri,
            manual_secret=secret,
        )

    @app.route("/mfa/verify", methods=["GET", "POST"])
    def mfa_verify():
        user_id = session.get("preauth_user_id")
        tenant = get_tenant_by_id(session.get("preauth_tenant_id") or session.get("tenant_id"))
        if not user_id:
            return redirect(url_for("login"))
        user = get_user_by_id(user_id)
        if not user or not user["totp_enabled"] or not tenant:
            clear_login_state()
            return redirect(url_for("login"))
        if request.method == "POST":
            code = request.form.get("code", "")
            if not verify_totp_code(user["totp_secret"], code):
                flash("Invalid MFA code.", "error")
                return render_template("mfa_verify.html", user=user), 401
            return finalize_authenticated_user(user, tenant, "Signed in.")
        return render_template("mfa_verify.html", user=user)

    @app.route("/password/change", methods=["GET", "POST"])
    def password_change():
        user_id = session.get("password_change_user_id") or session.get("user_id")
        tenant = get_tenant_by_id(session.get("password_change_tenant_id") or session.get("tenant_id"))
        if not user_id or not tenant:
            return redirect(url_for("login"))
        user = get_user_by_id(user_id)
        if not user:
            clear_login_state()
            return redirect(url_for("login"))
        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
                return render_template("password_change.html", user=user, tenant=tenant), 400
            try:
                change_password(user["id"], new_password, ip=_request_ip_address())
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template("password_change.html", user=user, tenant=tenant), 400
            complete_login(get_user_by_id(user["id"]), tenant)
            flash("Password updated.", "success")
            return redirect(url_for("dashboard"))
        return render_template("password_change.html", user=user, tenant=tenant)

    @app.route("/login/sso", methods=["GET", "POST"])
    def sso_login():
        tenant_id = (
            request.form.get("tenant_id")
            or request.args.get("tenant_id")
            or session.get("tenant_id")
            or app.config["TMS_DEFAULT_TENANT_ID"]
        )
        tenant = get_tenant_by_id(tenant_id)
        if not tenant:
            flash("Tenant not found for SSO.", "error")
            return redirect(url_for("login"))
        context = build_saml_stub_context(
            tenant,
            issuer=url_for("saml_acs", _external=True),
            acs_url=url_for("saml_acs", _external=True),
        )
        note_audit(tenant["tenant_id"], "", "SAML_STUB_VIEW", "tenants", tenant["tenant_id"], {"saml_client_ready": context["saml_client_ready"]}, ip=_request_ip_address())
        return render_template("sso_stub.html", **context)

    @app.route("/saml/acs", methods=["GET", "POST"])
    def saml_acs():
        tenant_id = request.values.get("tenant_id") or app.config["TMS_DEFAULT_TENANT_ID"]
        tenant = get_tenant_by_id(tenant_id)
        email = request.values.get("email", "").strip().lower()
        if app.config.get("TESTING") and tenant and email:
            from .database import get_user_by_email

            user = get_user_by_email(email, tenant["tenant_id"])
            if not user:
                abort(401, description="SSO stub could not find that user.")
            note_audit(tenant["tenant_id"], user["id"], "SAML_STUB_LOGIN", "users", user["id"], {"email": email}, ip=_request_ip_address())
            return finalize_authenticated_user(user, tenant, "SAML SSO stub completed.")
        abort(501, description="SAML ACS stub is available for configured enterprise tenants.")

    @app.route("/logout", methods=["POST"])
    def logout():
        clear_login_state()
        flash("Signed out.", "info")
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        metrics = {
            "active_loads": len(SAMPLE_LOADS),
            "priority_loads": sum(load["priority"] == "High" for load in SAMPLE_LOADS),
            "watchlist": sum(load["status"] in {"Customs Hold", "Awaiting Pickup"} for load in SAMPLE_LOADS),
        }
        return render_template("dashboard.html", metrics=metrics, loads=SAMPLE_LOADS)

    @app.route("/dispatch-board")
    @roles_required("admin", "dispatcher")
    def dispatch_board():
        return render_template("dispatch_board.html", loads=SAMPLE_LOADS)

    @app.route("/reports")
    @login_required
    def reports():
        grouped = {role: 0 for role in ROLE_CHOICES}
        for user in list_users(g.current_user["tenant_id"]):
            grouped[user["role"]] += 1
        return render_template("reports.html", grouped=grouped, loads=SAMPLE_LOADS)

    @app.route("/admin/users", methods=["GET", "POST"])
    @roles_required("admin")
    def admin_users():
        if request.method == "POST":
            action = request.form.get("action", "")
            target_user_id = int(request.form.get("user_id", "0"))
            if action == "set_role":
                role = request.form.get("role", "")
                if role not in ROLE_CHOICES:
                    abort(400, description="Invalid role selection.")
                update_role(target_user_id, role, actor=g.current_user["id"], ip=_request_ip_address())
                flash("User role updated.", "success")
            elif action == "reset_mfa":
                reset_totp(target_user_id, actor=g.current_user["id"], ip=_request_ip_address())
                flash("MFA reset. The user will re-enroll on next login.", "success")
            else:
                abort(400, description="Unknown admin action.")
            return redirect(url_for("admin_users"))
        return render_template("admin_users.html", users=list_users(g.current_user["tenant_id"]))

    @app.route("/admin/tenants", methods=["GET", "POST"])
    @app.route("/tms/admin/tenants", methods=["GET", "POST"])
    @roles_required("admin")
    def admin_tenants():
        form_values = {
            "company_name": "",
            "plan": "starter",
            "max_users": "5",
            "data_region": "ca-central",
            "allowed_ip_cidrs": "",
            "session_timeout_minutes": "30",
            "saml_entity_id": "",
            "saml_sso_url": "",
            "saml_metadata_url": "",
            "saml_x509_cert": "",
        }
        if request.method == "POST":
            action = request.form.get("action", "")
            tenant_id = request.form.get("tenant_id", "")
            if action == "create":
                try:
                    create_tenant(
                        company_name=request.form.get("company_name", ""),
                        plan=request.form.get("plan", "starter"),
                        max_users=request.form.get("max_users", "5"),
                        data_region=request.form.get("data_region", "ca-central"),
                        allowed_ip_cidrs=request.form.get("allowed_ip_cidrs", ""),
                        session_timeout_minutes=request.form.get("session_timeout_minutes", "30"),
                        saml_entity_id=request.form.get("saml_entity_id", ""),
                        saml_sso_url=request.form.get("saml_sso_url", ""),
                        saml_metadata_url=request.form.get("saml_metadata_url", ""),
                        saml_x509_cert=request.form.get("saml_x509_cert", ""),
                        actor=g.current_user["id"],
                        ip=_request_ip_address(),
                    )
                    flash("Tenant created.", "success")
                    return redirect(url_for("admin_tenants"))
                except ValueError as exc:
                    flash(str(exc), "error")
                    form_values.update(request.form)
            elif action in {"activate", "suspend", "delete"}:
                target_status = {"activate": "active", "suspend": "suspended", "delete": "deleted"}[action]
                update_tenant_status(tenant_id, target_status, actor=g.current_user["id"], ip=_request_ip_address())
                flash("Tenant updated.", "success")
                return redirect(url_for("admin_tenants"))
            else:
                abort(400, description="Unknown tenant action.")
        return render_template("admin_tenants.html", tenants=list_tenants(include_deleted=True), form_values=form_values)

    @app.route("/admin/audit")
    @app.route("/tms/admin/audit")
    @roles_required("admin")
    def admin_audit():
        filters = {
            "tenant_id": request.args.get("tenant_id", ""),
            "user_id": request.args.get("user_id", ""),
            "action": request.args.get("action", ""),
            "start_date": request.args.get("start_date", ""),
            "end_date": request.args.get("end_date", ""),
        }
        entries = list_audit_entries(**filters)
        return render_template("admin_audit.html", entries=entries, filters=filters, tenants=list_tenants(include_deleted=True))

    @app.route("/admin/audit/export")
    @app.route("/tms/admin/audit/export")
    @roles_required("admin")
    def admin_audit_export():
        filters = {
            "tenant_id": request.args.get("tenant_id", ""),
            "user_id": request.args.get("user_id", ""),
            "action": request.args.get("action", ""),
            "start_date": request.args.get("start_date", ""),
            "end_date": request.args.get("end_date", ""),
        }
        entries = list_audit_entries(**filters)
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=("id", "tenant_id", "user_id", "action", "table_name", "record_id", "ip", "created_at", "changes_json"),
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "id": entry["id"],
                    "tenant_id": entry["tenant_id"],
                    "user_id": entry["user_id"],
                    "action": entry["action"],
                    "table_name": entry["table_name"],
                    "record_id": entry["record_id"],
                    "ip": entry["ip"],
                    "created_at": entry["created_at"],
                    "changes_json": json.dumps(entry["changes"], sort_keys=True),
                }
            )
        response = Response(output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=tms-sandbox-audit.csv"
        return response

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "app": "tms-sandbox"}), 200

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def render_error(error):
        return (
            render_template(
                "error.html",
                status_code=getattr(error, "code", 500),
                message=getattr(error, "description", "Unexpected error."),
            ),
            getattr(error, "code", 500),
        )

    return app
