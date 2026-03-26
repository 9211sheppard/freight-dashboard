"""
app.py  —  Freight Intelligence Dashboard
Run with:  python app.py
Then open: http://127.0.0.1:5000
"""

import csv
import hashlib
import io
import os
import re
import subprocess
import sys
import webbrowser
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

# ── Sentry error tracking (production only) ──────────────────────────────────
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=SENTRY_DSN, integrations=[FlaskIntegration()],
                        traces_sample_rate=0.1, send_default_pii=False)
        print("[sentry] Error tracking enabled.")
    except ImportError:
        print("[sentry] sentry-sdk not installed — skipping.")

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, Response,
)

import urllib.request
import urllib.parse
import json as _json

from config import (
    SECRET_KEY, PASSWORD, DB_PATH, CSV_SOURCES, DATA_DIR,
    API_RATE_LIMIT, LOGIN_RATE_LIMIT, MAX_UPLOAD_SIZE_MB,
    SESSION_LIFETIME_HOURS,
)
from carrier_api import ORIGIN_PORTS, DEST_PORTS, has_any_api_keys_configured
from schedule_sync_api import ensure_schedule_schema, start_background_sync
import mailer as _mailer
from database import init_db, get_db, init_lanes_db, init_rates_db, init_users_db, init_contact_intelligence_db, init_email_outreach_db
from email_inspectors import init_inspection_log_db
from predictive_eta import init_predictive_db, enrich_schedules_with_predictions
from reliability import init_reliability_db, enrich_schedules_with_reliability, get_carrier_leaderboard, get_lane_leaderboard, compute_reliability_scores
from record_arrivals import mark_arrived
import contact_engine as _ce
from import_csv import import_all_csvs, import_csv
import rate_engine
import rate_engine_v2
import auth as _auth
import quotes as _quotes
import helpbot as _helpbot
from permissions import feature_required

if getattr(sys, 'frozen', False):
    # When running as a PyInstaller .exe, templates and static files
    # are extracted into sys._MEIPASS — tell Flask where to find them.
    _bundle = sys._MEIPASS
    app = Flask(__name__,
                template_folder=os.path.join(_bundle, 'templates'),
                static_folder=os.path.join(_bundle, 'static'))
else:
    app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0   # disable static file caching
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_SIZE_MB * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=SESSION_LIFETIME_HOURS)
if not app.debug:
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_NAME'] = '__Host-session'
ensure_schedule_schema()
_get_tms_tracking_context = None

# ── TMS Blueprint ─────────────────────────────────────────────────────────────
try:
    from tms import portal as portal_blueprint, public as public_blueprint, tms as tms_blueprint
    from tms.tms_db import get_tracking_page_context, init_tms_db
    init_tms_db()
    _get_tms_tracking_context = get_tracking_page_context
    app.register_blueprint(tms_blueprint)
    app.register_blueprint(portal_blueprint)
    app.register_blueprint(public_blueprint)
    print("[TMS] Loaded OK — available at /tms and /portal/login")
except Exception as _tms_err:
    print(f"[TMS] Failed to load: {_tms_err}")

# ── Microservices Gateway ─────────────────────────────────────────────────────
# Register all 12 microservice blueprints.
# In monolith mode (current), they run as blueprints under this single Flask app.
# Each service wraps its own business logic, models, and inter-service client.
# To split into independent services later, each can be deployed separately.
try:
    from gateway import register_all_services
    register_all_services(app)
    print("[microservices] All 12 services registered successfully:")
    print("  1. Auth & Permissions    7. Documents & OCR")
    print("  2. Contact Engine        8. Billing & Invoicing")
    print("  3. Email & Mailer        9. Compliance & Audit")
    print("  4. Rate Engine          10. Scrapers & Data Sync")
    print("  5. TMS Core             11. AI & Support")
    print("  6. Carrier & Fleet      12. Admin & Monitoring")
except Exception as _svc_err:
    print(f"[microservices] Gateway registration failed: {_svc_err}")

STARTUP_TIME = str(int(time.time()))          # changes on every restart → cache-busting


@app.route("/track/<ref>")
def public_tracking(ref):
    if _get_tms_tracking_context is None:
        return render_template(
            "error.html",
            code=503,
            message="Shipment tracking is temporarily unavailable.",
        ), 503

    context = _get_tms_tracking_context(ref)
    if not context:
        return render_template("tms/tracking.html", shipment=None, ref=ref), 404

    return render_template("tms/tracking.html", **context)

# ─────────────────────────────────────────────────────────────────────────────
#  CSV auto-sync state  (shared between watcher thread + request handlers)
# ─────────────────────────────────────────────────────────────────────────────
_sync_lock = threading.Lock()
_sync_state = {
    "last_sync":    None,   # datetime of last successful import
    "file_mtimes":  {},     # {path: mtime} for each source CSV
    "row_count":    0,
}

CHECK_INTERVAL = 604800   # seconds between auto-checks (1 week)


def _run_import():
    """Import ALL CSVs and update sync state. Thread-safe."""
    try:
        import_all_csvs()
        conn  = get_db()
        count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        conn.close()
        # Record current mtime for every configured source file
        new_mtimes = {}
        for src in CSV_SOURCES:
            p = src["path"]
            if os.path.exists(p):
                new_mtimes[p] = os.path.getmtime(p)
        with _sync_lock:
            _sync_state["last_sync"]   = datetime.now()
            _sync_state["file_mtimes"] = new_mtimes
            _sync_state["row_count"]   = count
    except Exception as exc:
        print(f"[auto-sync] Import error: {exc}")


def _csv_watcher():
    """Background thread: re-import whenever any source CSV file changes."""
    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            changed = False
            for src in CSV_SOURCES:
                p = src["path"]
                if not os.path.exists(p):
                    continue
                current_mtime = os.path.getmtime(p)
                with _sync_lock:
                    known_mtime = _sync_state["file_mtimes"].get(p)
                if known_mtime is None or current_mtime != known_mtime:
                    changed = True
                    break
            if changed:
                print("[auto-sync] CSV changed — reimporting all…")
                _run_import()
                print(f"[auto-sync] Done. {_sync_state['row_count']} contacts loaded.")
        except Exception as exc:
            print(f"[auto-sync] Watcher error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
#  Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        if session.get("user_role") != "admin":
            return jsonify({"ok": False, "error": "Admin access required."}), 403
        return f(*args, **kwargs)
    return decorated


def _get_onboarding_status(user_id):
    """Return onboarding completion state for a logged-in user."""
    if not user_id:
        return {"completed": True, "step": None}

    conn = get_db()
    try:
        row = conn.execute(
            """SELECT COALESCE(onboarding_completed, 0) AS onboarding_completed,
                      onboarding_step
               FROM users
               WHERE id = ?""",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {"completed": True, "step": None}

    return {
        "completed": bool(row["onboarding_completed"]),
        "step": row["onboarding_step"],
    }


def _post_login_redirect(user_id):
    """Send new users to onboarding before the dashboard."""
    status = _get_onboarding_status(user_id)
    if not status["completed"]:
        return redirect(url_for("onboarding_page"))
    return redirect(url_for("dashboard"))


# ─────────────────────────────────────────────────────────────────────────────
#  Health Check (Railway / load balancer)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/health")
def health_endpoint():
    from health import full_health_check
    result = full_health_check()
    code = 200 if result["status"] in ("healthy", "degraded") else 503
    return jsonify(result), code


@app.route("/status")
def status_page():
    """Public status page — no login required."""
    import datetime as _dt
    from health import full_health_check
    health = full_health_check()
    return render_template("status.html", health=health, now=_dt.datetime.utcnow())


# ─────────────────────────────────────────────────────────────────────────────
#  Admin Panel (admin only — internal team and customers never see this)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/admin")
@admin_required
def admin_panel_page():
    import admin_panel as _ap
    metrics = _ap.get_saas_metrics()
    tenants = _ap.list_tenants()
    users = _ap.get_all_users()
    spin_stats = _ap.get_spin_stats()
    referral_stats = _ap.get_referral_stats()
    ticket_stats = _ap.get_ticket_overview()
    health = _ap.run_health_check()
    # Pitch scores
    conn = get_db()
    try:
        pitch_scores = [dict(r) for r in conn.execute(
            "SELECT * FROM pitch_scores ORDER BY created_at DESC"
        ).fetchall()]
    except Exception:
        pitch_scores = []
    finally:
        conn.close()
    return render_template("admin.html",
                           metrics=metrics, tenants=tenants, users=users,
                           spin_stats=spin_stats, referral_stats=referral_stats,
                           ticket_stats=ticket_stats, health=health,
                           pitch_scores=pitch_scores,
                           sv=STARTUP_TIME)


@app.route("/api/admin/spin-stats")
@admin_required
def api_spin_stats():
    import admin_panel as _ap
    return jsonify(_ap.get_spin_stats())


@app.route("/api/admin/referral-stats")
@admin_required
def api_referral_stats():
    import admin_panel as _ap
    return jsonify(_ap.get_referral_stats())


# ── Spin-to-Win API (used during registration) ───────────────────────────────

@app.route("/api/spin", methods=["POST"])
@login_required
def api_spin_wheel():
    import admin_panel as _ap
    tenant_id = session.get("tenant_id", 1)
    user_id = session.get("user_id")
    prize = _ap.spin_the_wheel()
    _ap.record_spin(tenant_id, user_id, prize)
    return jsonify({"ok": True, "prize": prize})


# ── Referral API ──────────────────────────────────────────────────────────────

@app.route("/api/referral/code", methods=["POST"])
@login_required
def api_get_referral_code():
    import admin_panel as _ap
    tenant_id = session.get("tenant_id", 1)
    user_id = session.get("user_id")
    result = _ap.create_referral_code(tenant_id, user_id)
    return jsonify(result)


@app.route("/api/referral/validate")
def api_validate_referral():
    import admin_panel as _ap
    code = request.args.get("code", "")
    result = _ap.validate_referral_code(code)
    return jsonify(result)


# ─────────────────────────────────────────────────────────────────────────────
#  Investor & Technical Review Pages (token-gated — admin generates temp links)
# ─────────────────────────────────────────────────────────────────────────────

import secrets as _secrets

# In-memory temp link store: {token: {"page": str, "expires": datetime, "uses": int, "max_uses": int}}
_temp_links = {}


@app.route("/api/admin/temp-link", methods=["POST"])
@admin_required
def api_create_temp_link():
    """Admin creates a temporary access link for pitch/invest/review."""
    data = request.get_json() or {}
    page = data.get("page", "pitch")
    if page not in ("pitch", "invest", "review"):
        return jsonify({"ok": False, "error": "Page must be pitch, invest, or review"}), 400
    hours = data.get("hours", 24)
    max_uses = data.get("max_uses", 3)
    token = _secrets.token_urlsafe(32)
    _temp_links[token] = {
        "page": page,
        "expires": datetime.now() + timedelta(hours=hours),
        "uses": 0,
        "max_uses": max_uses,
    }
    base = request.host_url.rstrip("/")
    return jsonify({"ok": True, "url": f"{base}/{page}?token={token}", "token": token,
                    "expires_hours": hours, "max_uses": max_uses})


@app.route("/api/admin/temp-links")
@admin_required
def api_list_temp_links():
    """List all active temp links."""
    now = datetime.now()
    active = []
    for token, info in list(_temp_links.items()):
        if info["expires"] > now and info["uses"] < info["max_uses"]:
            active.append({"token": token[:8] + "...", "page": info["page"],
                           "uses": info["uses"], "max_uses": info["max_uses"],
                           "expires": info["expires"].isoformat()})
    return jsonify(active)


def _check_temp_token(page_name):
    """Check if request has a valid temp token. Returns token info dict or None."""
    token = request.args.get("token", "")
    if not token:
        return None
    info = _temp_links.get(token)
    if not info:
        return None
    if info["page"] != page_name:
        return None
    if datetime.now() > info["expires"]:
        del _temp_links[token]
        return None
    if info["uses"] >= info["max_uses"]:
        return None
    info["uses"] += 1
    return {
        "expires_iso": info["expires"].isoformat(),
        "remaining_uses": info["max_uses"] - info["uses"],
        "max_uses": info["max_uses"],
    }


@app.route("/invest")
def invest_page():
    if session.get("user_role") == "admin":
        return render_template("invest.html", token_info=None)
    token_info = _check_temp_token("invest")
    if token_info:
        return render_template("invest.html", token_info=token_info)
    return redirect(url_for("index"))


@app.route("/review")
def review_page():
    if session.get("user_role") == "admin":
        return render_template("review.html", token_info=None)
    token_info = _check_temp_token("review")
    if token_info:
        return render_template("review.html", token_info=token_info)
    return redirect(url_for("index"))
    return redirect(url_for("index"))


# ─────────────────────────────────────────────────────────────────────────────
#  Billing Routes (Stripe)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/billing")
@login_required
def billing_page():
    from billing import is_configured, STRIPE_PUBLISHABLE_KEY
    from tenant import get_tenant, check_subscription
    tenant_id = session.get("tenant_id", 1)
    tenant = get_tenant(tenant_id)
    sub = check_subscription(tenant_id)
    return render_template("billing.html",
                           tenant=tenant, subscription=sub,
                           stripe_configured=is_configured(),
                           stripe_key=STRIPE_PUBLISHABLE_KEY,
                           user=_auth.current_user(session))


@app.route("/api/billing/checkout", methods=["POST"])
@login_required
def billing_checkout():
    from billing import create_checkout_session
    tenant_id = session.get("tenant_id", 1)
    email = session.get("user_email", "")
    base = request.host_url.rstrip("/")
    result = create_checkout_session(
        tenant_id, email,
        success_url=f"{base}/billing?success=1",
        cancel_url=f"{base}/billing?cancelled=1",
    )
    return jsonify(result)


@app.route("/api/billing/portal", methods=["POST"])
@login_required
def billing_portal():
    from billing import create_portal_session
    tenant_id = session.get("tenant_id", 1)
    base = request.host_url.rstrip("/")
    result = create_portal_session(tenant_id, return_url=f"{base}/billing")
    return jsonify(result)


@app.route("/api/billing/webhook", methods=["POST"])
def billing_webhook():
    from billing import handle_webhook
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    result = handle_webhook(payload, sig)
    return jsonify(result), 200 if result.get("ok") else 400


# ─────────────────────────────────────────────────────────────────────────────
#  Quotes & Invoices
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/quotes", methods=["POST"])
@feature_required("quotes", "write")
def api_create_quote():
    data = request.get_json() or {}
    tenant_id = session.get("tenant_id", 1)
    user_id = session.get("user_id")
    result = _quotes.create_quote(tenant_id, user_id, data)
    return jsonify(result), 201 if result.get("ok") else 400

@app.route("/api/quotes")
@feature_required("quotes")
def api_list_quotes():
    tenant_id = session.get("tenant_id", 1)
    doc_type = request.args.get("type")
    status = request.args.get("status")
    rows = _quotes.list_quotes(tenant_id, doc_type=doc_type, status=status)
    return jsonify(rows)

@app.route("/api/quotes/<int:qid>")
@login_required
def api_get_quote(qid):
    tenant_id = session.get("tenant_id", 1)
    q = _quotes.get_quote(qid, tenant_id)
    if not q:
        return jsonify({"error": "Not found"}), 404
    return jsonify(q)

@app.route("/api/quotes/<int:qid>", methods=["PATCH"])
@login_required
def api_update_quote(qid):
    data = request.get_json() or {}
    tenant_id = session.get("tenant_id", 1)
    result = _quotes.update_quote(qid, tenant_id, data)
    return jsonify(result)

@app.route("/api/quotes/<int:qid>", methods=["DELETE"])
@feature_required("quotes", "delete")
def api_delete_quote(qid):
    tenant_id = session.get("tenant_id", 1)
    result = _quotes.delete_quote(qid, tenant_id)
    return jsonify(result)

@app.route("/api/quotes/<int:qid>/pdf")
@login_required
def api_quote_pdf(qid):
    tenant_id = session.get("tenant_id", 1)
    q = _quotes.get_quote(qid, tenant_id)
    if not q:
        return jsonify({"error": "Not found"}), 404
    pdf_bytes = _quotes.generate_pdf(q)
    content_type = "application/pdf"
    if pdf_bytes[:5] == b"<!DOC":
        content_type = "text/html"
    return Response(pdf_bytes, mimetype=content_type,
                    headers={"Content-Disposition": f"inline; filename={q['doc_number']}.pdf"})

@app.route("/api/quotes/<int:qid>/html")
@login_required
def api_quote_html(qid):
    tenant_id = session.get("tenant_id", 1)
    q = _quotes.get_quote(qid, tenant_id)
    if not q:
        return jsonify({"error": "Not found"}), 404
    html = _quotes.render_quote_html(q)
    return Response(html, mimetype="text/html")

@app.route("/api/quotes/from-rate", methods=["POST"])
@login_required
def api_quote_from_rate():
    data = request.get_json() or {}
    tenant_id = session.get("tenant_id", 1)
    user_id = session.get("user_id")
    result = _quotes.quote_from_rate(
        tenant_id, user_id,
        rate_id=int(data.get("rate_id", 0)),
        client_name=data.get("client_name", ""),
        client_email=data.get("client_email", ""),
        client_company=data.get("client_company", ""),
        margin_pct=float(data.get("margin_pct", 15)),
    )
    return jsonify(result), 201 if result.get("ok") else 400


# ─────────────────────────────────────────────────────────────────────────────
#  Admin Dashboard (system-wide view)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/admin/dashboard")
@login_required
def api_admin_dashboard():
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403
    from health import full_health_check, get_system_stats
    health = full_health_check()
    stats = get_system_stats()
    conn = get_db()
    try:
        # Revenue metrics
        tenants = conn.execute("""
            SELECT plan, subscription_status, COUNT(*) as cnt
            FROM tenants GROUP BY plan, subscription_status
        """).fetchall()
        # Recent signups
        recent = conn.execute("""
            SELECT t.name, t.slug, t.plan, t.subscription_status, t.created_at,
                   COUNT(u.id) as user_count
            FROM tenants t LEFT JOIN users u ON u.tenant_id = t.id
            GROUP BY t.id ORDER BY t.created_at DESC LIMIT 20
        """).fetchall()
        # Quote stats
        quote_stats = conn.execute("""
            SELECT doc_type, status, COUNT(*) as cnt, COALESCE(SUM(total),0) as total_value
            FROM quotes GROUP BY doc_type, status
        """).fetchall()
    finally:
        conn.close()

    active_paid = sum(r["cnt"] for r in tenants if r["subscription_status"] == "active" and r["plan"] == "pro")
    trial = sum(r["cnt"] for r in tenants if r["plan"] == "trial")
    mrr = active_paid * 49.99

    return jsonify({
        "health": health,
        "stats": stats,
        "revenue": {
            "active_paid": active_paid,
            "trial": trial,
            "mrr": round(mrr, 2),
            "arr": round(mrr * 12, 2),
        },
        "tenants_by_plan": [dict(r) for r in tenants],
        "recent_tenants": [dict(r) for r in recent],
        "quote_stats": [dict(r) for r in quote_stats],
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────

_rate_limit_store = {}  # {ip: [timestamps]}
_RATE_LIMIT_CLEANUP_COUNTER = 0

def _check_rate_limit(ip: str, max_requests: int = 60, window: int = 60) -> bool:
    """In-memory rate limiter with periodic cleanup."""
    global _RATE_LIMIT_CLEANUP_COUNTER
    now = time.time()

    # Periodic cleanup to prevent unbounded memory growth
    _RATE_LIMIT_CLEANUP_COUNTER += 1
    if _RATE_LIMIT_CLEANUP_COUNTER >= 500:
        _RATE_LIMIT_CLEANUP_COUNTER = 0
        stale_keys = [k for k, v in _rate_limit_store.items() if not v or now - v[-1] > 300]
        for k in stale_keys:
            _rate_limit_store.pop(k, None)

    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = []
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < window]
    if len(_rate_limit_store[ip]) >= max_requests:
        return False
    _rate_limit_store[ip].append(now)
    return True


# ─────────────────────────────────────────────────────────────────────────────
#  CSRF Protection
# ─────────────────────────────────────────────────────────────────────────────
import secrets as _secrets

def _generate_csrf_token():
    """Generate or retrieve CSRF token from session."""
    token = session.get("_csrf_token")
    if not token:
        token = _secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token

@app.context_processor
def _inject_csrf():
    """Make csrf_token(), csp_nonce, and security config available in all templates."""
    from config import HCAPTCHA_SITE_KEY, GOOGLE_CLIENT_ID, MICROSOFT_CLIENT_ID
    import oauth as _oauth
    return {
        "csrf_token": _generate_csrf_token,
        "csp_nonce": getattr(g, "csp_nonce", ""),
        "hcaptcha_site_key": HCAPTCHA_SITE_KEY,
        "google_oauth_enabled": _oauth.google_enabled(),
        "microsoft_oauth_enabled": _oauth.microsoft_enabled(),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Security: before_request hooks
# ─────────────────────────────────────────────────────────────────────────────
from flask import g

# Paths that are exempt from CSRF checks
_CSRF_EXEMPT_PATHS = frozenset([
    "/api/billing/webhook",     # Stripe uses signature verification
    "/api/pitch/score",         # Public endpoint
    "/r/",                      # Public click tracking
])

@app.before_request
def _security_before_request():
    """Combined security checks: request ID, CSP nonce, rate limiting, API key auth, CSRF, session fingerprint, timeout."""

    # ── 0. Request ID + CSP nonce (every request) ───────────────────────
    import uuid
    g.request_id = str(uuid.uuid4())
    g.csp_nonce = _secrets.token_urlsafe(16)

    path = request.path

    # ── 0.5. WAF / DDoS protection layer ─────────────────────────────
    from waf import get_real_ip, is_ip_banned, check_ddos
    ip = get_real_ip(request)
    g.real_ip = ip

    if is_ip_banned(ip):
        return jsonify({"error": "Access denied."}), 403

    if not check_ddos(ip):
        return jsonify({"error": "Too many requests. Try again later."}), 429

    # ── 1. Rate limiting (application-level, on top of WAF) ──────────
    if path == "/login" and request.method == "POST":
        if not _check_rate_limit(ip, max_requests=LOGIN_RATE_LIMIT, window=300):
            return jsonify({"error": "Too many login attempts. Try again in a few minutes."}), 429
    elif path.startswith("/api/"):
        if not _check_rate_limit(ip, max_requests=API_RATE_LIMIT, window=60):
            resp = jsonify({"error": "Rate limit exceeded. Try again shortly."})
            resp.headers["Retry-After"] = "60"
            return resp, 429

    # ── 2. API key authentication ───────────────────────────────────────
    g.api_user = None
    g.is_api_request = False
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer fid_"):
        from api_auth import validate_api_key
        api_key = auth_header[7:]  # Strip "Bearer "
        api_user = validate_api_key(api_key)
        if api_user:
            g.api_user = api_user
            g.is_api_request = True
        else:
            return jsonify({"ok": False, "error": "Invalid or expired API key."}), 401

    # ── 3. CSRF validation on state-changing requests ───────────────────
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        # Skip CSRF for API key authenticated requests
        if g.is_api_request:
            pass
        # Skip CSRF for exempt paths
        elif any(path.startswith(p) for p in _CSRF_EXEMPT_PATHS):
            pass
        # Skip CSRF for JSON API requests that have session auth
        # (browser JS sends X-CSRF-Token header)
        elif request.is_json or request.content_type and "json" in request.content_type:
            csrf_header = request.headers.get("X-CSRF-Token", "")
            csrf_session = session.get("_csrf_token", "")
            if csrf_session and csrf_header:
                if not _secrets.compare_digest(csrf_header, csrf_session):
                    return jsonify({"ok": False, "error": "Invalid CSRF token."}), 403
        else:
            # Form submissions must include csrf_token
            csrf_form = request.form.get("csrf_token", "")
            csrf_session = session.get("_csrf_token", "")
            if csrf_session and csrf_form:
                if not _secrets.compare_digest(csrf_form, csrf_session):
                    return jsonify({"ok": False, "error": "Invalid CSRF token."}), 403

    # ── 4. Session timeout check ────────────────────────────────────────
    if session.get("logged_in") and not g.is_api_request:
        created = session.get("_created_at")
        if not created:
            # Legacy session without timestamp — force re-login
            _auth.clear_session(session)
            if path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Session expired. Please log in again."}), 401
            return redirect(url_for("login"))
        try:
            created_dt = datetime.fromisoformat(created)
            if datetime.now() - created_dt > timedelta(hours=SESSION_LIFETIME_HOURS):
                _auth.clear_session(session)
                if path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Session expired. Please log in again."}), 401
                return redirect(url_for("login"))
        except (ValueError, TypeError):
            _auth.clear_session(session)
            return redirect(url_for("login"))

        # ── 5. Session fingerprint validation (detect hijacking) ──────
        stored_fp = session.get("_fingerprint")
        if stored_fp:
            current_fp = hashlib.sha256(
                (request.headers.get("User-Agent", "") +
                 request.headers.get("Accept-Language", "")).encode()
            ).hexdigest()
            if current_fp != stored_fp:
                from audit import log_event
                log_event(session.get("tenant_id"), session.get("user_id"),
                          "session_hijack_detected",
                          details=f"fingerprint mismatch",
                          ip=request.remote_addr or "")
                _auth.clear_session(session)
                if path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Session invalidated. Please log in again."}), 401
                return redirect(url_for("login"))

        # ── 6. Single-session enforcement (detect password sharing) ───
        if not _auth.validate_session_token(session):
            _auth.clear_session(session)
            if path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Session ended — your account was logged in elsewhere."}), 401
            return redirect(url_for("login"))

        # ── 7. MFA enforcement (admin can force all users to set up MFA)
        if path not in ("/logout", "/api/auth/mfa/setup", "/api/auth/mfa/enable"):
            tenant_id = session.get("tenant_id", 1)
            user_id = session.get("user_id")
            if _auth.check_mfa_enforced(tenant_id) and not _auth.is_user_mfa_enabled(user_id):
                if path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "MFA is required. Please set up two-factor authentication.", "mfa_required": True}), 403
                return redirect(url_for("mfa_setup_required"))


# ─────────────────────────────────────────────────────────────────────────────
#  Security Headers
# ─────────────────────────────────────────────────────────────────────────────

@app.after_request
def _set_security_headers(response):
    """Add security headers to all responses."""
    nonce = getattr(g, "csp_nonce", "")
    req_id = getattr(g, "request_id", "")

    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if req_id:
        response.headers['X-Request-ID'] = req_id
    if not app.debug:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    # CSP with nonces (replaces unsafe-inline)
    hcaptcha_src = ""
    try:
        from config import HCAPTCHA_SITE_KEY
        if HCAPTCHA_SITE_KEY:
            hcaptcha_src = " https://hcaptcha.com https://*.hcaptcha.com"
    except Exception:
        pass
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' https://js.stripe.com https://cdn.jsdelivr.net{hcaptcha_src}; "
        f"style-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net{hcaptcha_src}; "
        "img-src 'self' data: https:; "
        f"frame-src https://js.stripe.com{hcaptcha_src}; "
        f"connect-src 'self' https://api.stripe.com{hcaptcha_src}; "
        "font-src 'self' https://cdn.jsdelivr.net"
    )
    return response


# ─────────────────────────────────────────────────────────────────────────────
#  AI Help Bot
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/helpbot/ask", methods=["POST"])
@feature_required("helpbot")
def api_helpbot_ask():
    data = request.get_json() or {}
    question = data.get("question", "").strip()
    tenant_id = session.get("tenant_id", 1)
    user_id = session.get("user_id")
    result = _helpbot.ask(question, tenant_id=tenant_id, user_id=user_id)
    return jsonify(result)

@app.route("/api/helpbot/stats")
@login_required
def api_helpbot_stats():
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403
    return jsonify(_helpbot.get_helpbot_stats())


# ─────────────────────────────────────────────────────────────────────────────
#  Transactional Emails (welcome, trial ending, payment failed)
# ─────────────────────────────────────────────────────────────────────────────

TRANSACTIONAL_TEMPLATES = {
    "welcome": {
        "subject": "Welcome to Freight Intelligence — Your 14-Day Trial Starts Now",
        "body": """<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#0047AB;">Welcome aboard!</h2>
<p>Your 14-day free trial is active. Here's what you can do right now:</p>
<ul>
<li><strong>Import contacts</strong> — Upload your CSV or browse our network database</li>
<li><strong>Run rate cycles</strong> — Collect and benchmark quotes from agents</li>
<li><strong>Track vessels</strong> — Predictive ETAs and carrier reliability scoring</li>
<li><strong>Score agents</strong> — See who responds fastest with the best rates</li>
</ul>
<p><a href="{base_url}/dashboard" style="background:#0047AB;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;display:inline-block;">Open Dashboard</a></p>
<p style="color:#666;font-size:13px;">No credit card required. Full access for 14 days.</p>
</div>""",
    },
    "trial_ending": {
        "subject": "Your Trial Ends in 3 Days — Keep Your Data",
        "body": """<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#0047AB;">Your trial ends in 3 days</h2>
<p>Your contacts, rates, and agent scores are safe — but you'll lose access when the trial ends.</p>
<p>Upgrade to Pro ($49.99/mo) to keep everything:</p>
<ul>
<li>Up to 50,000 contacts</li>
<li>Up to 50 team members</li>
<li>Unlimited rate cycles</li>
<li>All features forever</li>
</ul>
<p><a href="{base_url}/billing" style="background:#0047AB;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;display:inline-block;">Upgrade Now</a></p>
</div>""",
    },
    "payment_failed": {
        "subject": "Action Required — Payment Failed",
        "body": """<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#dc3545;">Payment failed</h2>
<p>We couldn't process your payment for Freight Intelligence ($49.99/mo).</p>
<p>Please update your payment method to keep your account active. Your data is safe — you have 7 days to resolve this.</p>
<p><a href="{base_url}/billing" style="background:#dc3545;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;display:inline-block;">Update Payment</a></p>
</div>""",
    },
    "payment_success": {
        "subject": "Payment Confirmed — You're All Set",
        "body": """<div style="font-family:Inter,sans-serif;max-width:600px;margin:0 auto;">
<h2 style="color:#198754;">Payment confirmed!</h2>
<p>Your Freight Intelligence subscription is active. $49.99 has been charged to your card.</p>
<p>View your invoice and manage your subscription anytime from the billing page.</p>
<p><a href="{base_url}/billing" style="background:#0047AB;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;display:inline-block;">View Billing</a></p>
</div>""",
    },
}


def _send_transactional(to_email: str, template_name: str, base_url: str = ""):
    """Send a transactional email using a predefined template."""
    tmpl = TRANSACTIONAL_TEMPLATES.get(template_name)
    if not tmpl:
        return {"ok": False, "error": f"Unknown template: {template_name}"}
    subject = tmpl["subject"]
    body = tmpl["body"].replace("{base_url}", base_url)
    try:
        _mailer.send(to=to_email, subject=subject, body_html=body)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  Support Tickets
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/support/ticket", methods=["POST"])
@login_required
def create_support_ticket():
    from tenant import create_ticket
    data = request.get_json() or {}
    tenant_id = session.get("tenant_id", 1)
    user_id = session.get("user_id")
    result = create_ticket(
        tenant_id, user_id,
        category=data.get("category", "general"),
        subject=data.get("subject", ""),
        description=data.get("description", ""),
    )
    return jsonify(result)


@app.route("/api/support/tickets")
@login_required
def list_support_tickets():
    from tenant import get_tickets
    tenant_id = session.get("tenant_id", 1)
    status_filter = request.args.get("status")
    tickets = get_tickets(tenant_id, status=status_filter)
    return jsonify({"tickets": tickets})


# ─────────────────────────────────────────────────────────────────────────────
#  System Admin (super-admin only)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/admin/health")
@admin_required
def admin_health():
    from health import full_health_check, get_system_stats
    return jsonify({
        "health": full_health_check(),
        "stats": get_system_stats(),
    })


@app.route("/api/admin/bounces")
@admin_required
def admin_bounces():
    """Return all recorded bounces and optionally trigger a new scan."""
    from bounce_monitor import get_all_bounces, check_bounces
    action = request.args.get("action", "")
    if action == "scan":
        result = check_bounces()
        return jsonify({"ok": True, "scan_result": result, "bounces": get_all_bounces()})
    return jsonify({"ok": True, "bounces": get_all_bounces()})


@app.route("/api/admin/bounces/scan", methods=["POST"])
@admin_required
def admin_bounces_scan():
    """Trigger a bounce scan now."""
    from bounce_monitor import check_bounces
    result = check_bounces()
    return jsonify({"ok": True, **result})




# ─────────────────────────────────────────────────────────────────────────────
#  Error Handlers (user-friendly error pages)
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(400)
def bad_request(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Bad request"}), 400
    return render_template("error.html", code=400, message="Bad request"), 400


@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Access denied"}), 403
    return render_template("error.html", code=403, message="Access denied"), 403


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Not found"}), 404
    return render_template("error.html", code=404, message="Page not found"), 404


@app.errorhandler(413)
def request_too_large(e):
    return jsonify({"ok": False, "error": f"File too large. Maximum size is {MAX_UPLOAD_SIZE_MB} MB."}), 413


@app.errorhandler(429)
def rate_limited(e):
    resp = jsonify({"ok": False, "error": "Rate limit exceeded. Try again shortly."})
    resp.headers["Retry-After"] = "60"
    return resp, 429


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Internal server error"}), 500
    return render_template("error.html", code=500,
                           message="Something went wrong. Our team has been notified."), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Auth routes  (per-user email + password)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page for visitors, dashboard redirect for logged-in users."""
    if session.get("logged_in"):
        return _post_login_redirect(session.get("user_id"))
    return render_template("landing.html")


def _build_session_fingerprint():
    """Build a session fingerprint from browser characteristics."""
    return hashlib.sha256(
        (request.headers.get("User-Agent", "") +
         request.headers.get("Accept-Language", "")).encode()
    ).hexdigest()


def _send_login_notification(user, ip):
    """Send email notification for new device/IP login (non-blocking)."""
    try:
        conn = get_db()
        # Check if this IP has been seen before for this user
        seen = conn.execute(
            "SELECT COUNT(*) FROM user_logins WHERE user_id = ? AND ip_address = ?",
            (user["id"], ip)
        ).fetchone()[0]
        # Check user preference
        row = conn.execute(
            "SELECT COALESCE(login_notifications_enabled, 1) as notif FROM users WHERE id = ?",
            (user["id"],)
        ).fetchone()
        conn.close()
        if seen <= 1 and row and row["notif"]:  # <= 1 because current login already inserted
            ua = request.headers.get("User-Agent", "Unknown browser")[:100]
            _auth._send_email(
                to=user["email"],
                subject="New login to your Freight Intelligence account",
                body=(
                    f"Hi {user['name']},\n\n"
                    f"We detected a new login to your account:\n\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n"
                    f"IP: {ip}\n"
                    f"Browser: {ua}\n\n"
                    f"If this wasn't you, change your password immediately.\n\n"
                    f"— Freight Intelligence Security"
                ),
            )
    except Exception:
        pass  # Non-blocking — never crash login for notifications


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return _post_login_redirect(session.get("user_id"))

    error = None
    paywall = False
    if request.method == "POST":
        # hCaptcha verification
        from validators import verify_captcha
        captcha_token = request.form.get("h-captcha-response", "")
        if not verify_captcha(captcha_token):
            error = "Please complete the security check."
            return render_template("login.html", error=error, paywall=False)

        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        ip       = request.remote_addr or ""

        result = _auth.login_user(email, password, ip=ip)
        if result["ok"]:
            if result.get("mfa_required"):
                session["_mfa_pending"]  = True
                session["_mfa_user"]     = result["user"]
                return redirect(url_for("mfa_verify_page"))
            _auth.set_session(session, result["user"],
                              ip=ip, user_agent=request.headers.get("User-Agent", ""))
            session["_fingerprint"] = _build_session_fingerprint()
            _send_login_notification(result["user"], ip)
            return _post_login_redirect(result["user"]["id"])
        error = result["error"]
        paywall = result.get("paywall", False)

    return render_template("login.html", error=error, paywall=paywall)


@app.route("/mfa-verify", methods=["GET", "POST"])
def mfa_verify_page():
    """MFA verification page shown after successful password check."""
    if not session.get("_mfa_pending"):
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        user = session.get("_mfa_user")
        if not user:
            return redirect(url_for("login"))

        result = _auth.verify_mfa(user["id"], code)
        if result["ok"]:
            session.pop("_mfa_pending", None)
            session.pop("_mfa_user", None)
            _auth.set_session(session, user,
                              ip=request.remote_addr or "",
                              user_agent=request.headers.get("User-Agent", ""))
            session["_fingerprint"] = _build_session_fingerprint()
            _send_login_notification(user, request.remote_addr or "")
            return _post_login_redirect(user["id"])
        error = result["error"]

    return render_template("mfa_verify.html", error=error)


# ─────────────────────────────────────────────────────────────────────────────
#  Adaptive Pitch Page (token-gated — admin generates temp links)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/pitch")
def pitch_page():
    if session.get("user_role") == "admin":
        return render_template("pitch.html", token_info=None)
    token_info = _check_temp_token("pitch")
    if token_info:
        return render_template("pitch.html", token_info=token_info)
    return redirect(url_for("index"))


@app.route("/api/pitch/profiles")
def api_pitch_profiles():
    """Serve profession profiles as JSON (fallback if static file fails)."""
    import json
    try:
        with open(os.path.join(BASE_DIR, "pitch_profiles.json"), "r") as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({"default": {"label": "Business Professional", "icon": "bi-briefcase",
                                     "analogies": {}, "scoring_questions": {}}})


@app.route("/api/pitch/score", methods=["POST"])
def api_pitch_score():
    """Save a visitor's pitch score and feedback."""
    import json as _json
    data = request.get_json() or {}
    now = datetime.now().isoformat()
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO pitch_scores
               (visitor_name, profession_key, profession_label, score,
                risk_answer, advice_answer, fund_answer, scoring_answers,
                ip_address, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data.get("name", ""), data.get("profession", ""),
             data.get("profession_label", ""), data.get("score", 5),
             data.get("risk_answer", ""), data.get("advice_answer", ""),
             data.get("fund_answer", ""),
             _json.dumps(data.get("scoring_answers", [])),
             request.remote_addr or "", request.headers.get("User-Agent", "")[:200],
             now)
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("logged_in"):
        return _post_login_redirect(session.get("user_id"))

    error   = None
    success = None
    if request.method == "POST":
        # hCaptcha verification
        from validators import verify_captcha, check_password_breach
        captcha_token = request.form.get("h-captcha-response", "")
        if not verify_captcha(captcha_token):
            error = "Please complete the security check."
            return render_template("register.html", error=error, success=None)

        name          = request.form.get("name", "").strip()
        email         = request.form.get("email", "").strip()
        company_name  = request.form.get("company_name", "").strip()
        password      = request.form.get("password", "")
        confirm       = request.form.get("confirm", "")
        referral_code = request.form.get("referral_code", "").strip()

        if password != confirm:
            error = "Passwords do not match."
        else:
            # Check for breached password (advisory warning)
            breached, count = check_password_breach(password)
            breach_warning = ""
            if breached:
                breach_warning = f"Warning: This password has appeared in {count:,} data breaches. Consider using a different one."

            result = _auth.register_user(name, email, password,
                                         role="customer", company_name=company_name)
            if result["ok"]:
                # Process referral code if provided
                if referral_code:
                    try:
                        import admin_panel as _ap
                        _ap.complete_referral(referral_code, result["tenant_id"], email)
                    except Exception:
                        pass  # Don't block registration if referral fails

                # Auto-login after registration
                login_result = _auth.login_user(email, password, ip=request.remote_addr or "")
                if login_result["ok"]:
                    _auth.set_session(session, login_result["user"],
                                          ip=request.remote_addr or "",
                                          user_agent=request.headers.get("User-Agent", ""))
                    session["show_spin"] = True  # Flag to show spin wheel
                    return redirect(url_for("spin_page"))
                success = "Account created! Please log in."
            else:
                error = result["error"]

    return render_template("register.html", error=error, success=success)


@app.route("/spin")
@login_required
def spin_page():
    """Spin-to-win page shown after registration."""
    if not session.pop("show_spin", False):
        # If they navigate here directly without registering, skip to dashboard
        return redirect(url_for("dashboard"))
    return render_template("spin.html", sv=STARTUP_TIME)


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    sent  = False
    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        base_url = request.url_root.rstrip("/")
        _auth.request_password_reset(email, base_url)
        sent = True   # always show "check your email" (no enumeration)
    return render_template("forgot_password.html", sent=sent, error=error)


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token   = request.args.get("token", "") or request.form.get("token", "")
    error   = None
    success = False
    if request.method == "POST":
        new_pw  = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if new_pw != confirm:
            error = "Passwords do not match."
        else:
            result = _auth.reset_password(token, new_pw)
            if result["ok"]:
                success = True
            else:
                error = result["error"]
    return render_template("reset_password.html", token=token, error=error, success=success)


@app.route("/logout")
def logout():
    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "logout",
              ip=request.remote_addr or "")
    _auth.clear_session(session)
    return redirect(url_for("login"))


# ─────────────────────────────────────────────────────────────────────────────
#  Auth API  (JSON — for JS calls)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/auth/me")
def api_auth_me():
    if not session.get("logged_in"):
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": _auth.current_user(session)})


@app.route("/api/auth/change-password", methods=["POST"])
@login_required
def api_change_password():
    data       = request.get_json() or {}
    user_id    = session.get("user_id")
    old_pw     = data.get("old_password", "")
    new_pw     = data.get("new_password", "")
    result     = _auth.change_password(user_id, old_pw, new_pw)
    return jsonify(result)


@app.route("/api/admin/users")
@login_required
def api_admin_users():
    if session.get("user_role") != "admin":
        return jsonify({"ok": False, "error": "Admin only."}), 403
    return jsonify(_auth.list_users())


@app.route("/api/admin/users/<int:user_id>/role", methods=["PATCH"])
@login_required
def api_admin_set_role(user_id):
    if session.get("user_role") != "admin":
        return jsonify({"ok": False, "error": "Admin only."}), 403
    role   = (request.get_json() or {}).get("role", "user")
    result = _auth.set_user_role(user_id, role)
    return jsonify(result)


@app.route("/api/admin/activity")
@login_required
def api_admin_activity():
    if session.get("user_role") != "admin":
        return jsonify({"ok": False, "error": "Admin only."}), 403
    conn = get_db()
    try:
        users = conn.execute("""
            SELECT id, name, email, role, last_login,
                   COALESCE(login_count, 0) as login_count
            FROM users ORDER BY last_login DESC
        """).fetchall()
        recent = conn.execute("""
            SELECT ul.user_id, u.name, ul.login_at, ul.ip_address
            FROM user_logins ul JOIN users u ON ul.user_id = u.id
            ORDER BY ul.login_at DESC LIMIT 50
        """).fetchall()
        return jsonify({
            "users": [dict(r) for r in users],
            "recent_logins": [dict(r) for r in recent]
        })
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  User Invite  (admin only)
# ─────────────────────────────────────────────────────────────────────────────

def _graph_token():
    """Fetch an OAuth2 client-credentials token from Microsoft Graph."""
    from config import GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    url  = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     GRAPH_CLIENT_ID,
        "client_secret": GRAPH_CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return _json.loads(r.read())["access_token"]


def _graph_request(method, path, body=None, token=None):
    """Make a Microsoft Graph API call. Returns parsed JSON response."""
    if token is None:
        token = _graph_token()
    url     = f"https://graph.microsoft.com/v1.0{path}"
    payload = _json.dumps(body).encode() if body else None
    req     = urllib.request.Request(url, data=payload, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type",  "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return _json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise RuntimeError(f"Graph {method} {path} → {e.code}: {err_body}")


@app.route("/api/users/invite", methods=["POST"])
@login_required
def api_users_invite():
    if session.get("user_role") != "admin":
        return jsonify({"ok": False, "error": "Admin access required."}), 403

    data  = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Valid email address required."}), 400

    import secrets as _secrets
    import string  as _string
    from config import GRAPH_TENANT_ID, EMAIL_FROM

    dashboard_url = "https://flashcargo-dashboard-5000.use.devtunnels.ms"

    # ── 1. Generate a 12-char password ────────────────────────────────────
    alphabet = _string.ascii_letters + _string.digits + "!@#$%"
    password = "".join(_secrets.choice(alphabet) for _ in range(12))

    # ── 2. Create Flask dashboard account ─────────────────────────────────
    name   = email.split("@")[0].replace(".", " ").replace("_", " ").title()
    result = _auth.register_user(name, email, password, role="user")
    if not result["ok"]:
        # If already exists, still send the welcome email with a new password reset
        if "already exists" not in result.get("error", ""):
            return jsonify({"ok": False, "error": result["error"]}), 400

    try:
        token = _graph_token()

        # ── 3. Send Azure B2B guest invite ─────────────────────────────────
        try:
            _graph_request("POST", "/invitations", body={
                "invitedUserEmailAddress": email,
                "inviteRedirectUrl":       dashboard_url,
                "sendInvitationMessage":   False,   # we send our own email below
            }, token=token)
        except Exception as inv_err:
            print(f"[invite] B2B invite warning (non-fatal): {inv_err}")
            # Continue — some tenants block B2B invites; email still goes out

        # ── 4. Send welcome email via Graph API ────────────────────────────
        body_html = f"""
<p>Hi {name},</p>
<p>You have been invited to the <strong>Flash Cargo Freight Dashboard</strong>.</p>
<p><strong>Login URL:</strong> <a href="{dashboard_url}">{dashboard_url}</a><br>
<strong>Username:</strong> {email}<br>
<strong>Password:</strong> {password}</p>
<p>Please log in and change your password as soon as possible.</p>
<p>— Flash Cargo Team</p>
"""
        _graph_request("POST", f"/users/{EMAIL_FROM}/sendMail", body={
            "message": {
                "subject": "Your Flash Cargo Dashboard Access",
                "body":    {"contentType": "HTML", "content": body_html},
                "toRecipients": [{"emailAddress": {"address": email}}],
            },
            "saveToSentItems": True,
        }, token=token)

    except Exception as e:
        # Roll back the created user if Graph calls fail entirely
        print(f"[invite] Graph error: {e}")
        return jsonify({"ok": False, "error": f"Account created but email failed: {e}"}), 500

    return jsonify({"ok": True, "message": f"Invite sent to {email}"})


# ─────────────────────────────────────────────────────────────────────────────
#  OAuth2 / SSO routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/auth/google")
def auth_google():
    import oauth as _oauth
    if not _oauth.google_enabled():
        return redirect(url_for("login"))
    state = _secrets.token_urlsafe(32)
    session["_oauth_state"] = state
    return redirect(_oauth.get_google_auth_url(state))


@app.route("/auth/google/callback")
def auth_google_callback():
    import oauth as _oauth
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    if not state or state != session.pop("_oauth_state", ""):
        return redirect(url_for("login"))
    result = _oauth.handle_google_callback(code)
    if not result["ok"]:
        return render_template("login.html", error=result["error"], paywall=False)
    login_result = _oauth.oauth_login_or_register(
        result["email"], result["name"], "google", ip=request.remote_addr or ""
    )
    if login_result["ok"]:
        _auth.set_session(session, login_result["user"],
                                          ip=request.remote_addr or "",
                                          user_agent=request.headers.get("User-Agent", ""))
        session["_fingerprint"] = _build_session_fingerprint()
        if login_result.get("new_user"):
            session["show_spin"] = True
            return redirect(url_for("spin_page"))
        return _post_login_redirect(login_result["user"]["id"])
    return render_template("login.html", error=login_result.get("error", "OAuth failed."), paywall=False)


@app.route("/auth/microsoft")
def auth_microsoft():
    import oauth as _oauth
    if not _oauth.microsoft_enabled():
        return redirect(url_for("login"))
    state = _secrets.token_urlsafe(32)
    session["_oauth_state"] = state
    return redirect(_oauth.get_microsoft_auth_url(state))


@app.route("/auth/microsoft/callback")
def auth_microsoft_callback():
    import oauth as _oauth
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    if not state or state != session.pop("_oauth_state", ""):
        return redirect(url_for("login"))
    result = _oauth.handle_microsoft_callback(code)
    if not result["ok"]:
        return render_template("login.html", error=result["error"], paywall=False)
    login_result = _oauth.oauth_login_or_register(
        result["email"], result["name"], "microsoft", ip=request.remote_addr or ""
    )
    if login_result["ok"]:
        _auth.set_session(session, login_result["user"],
                                          ip=request.remote_addr or "",
                                          user_agent=request.headers.get("User-Agent", ""))
        session["_fingerprint"] = _build_session_fingerprint()
        if login_result.get("new_user"):
            session["show_spin"] = True
            return redirect(url_for("spin_page"))
        return _post_login_redirect(login_result["user"]["id"])
    return render_template("login.html", error=login_result.get("error", "OAuth failed."), paywall=False)


# ─────────────────────────────────────────────────────────────────────────────
#  Security.txt (RFC 9116)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/.well-known/security.txt")
def security_txt():
    from config import SECURITY_CONTACT_EMAIL, BUG_BOUNTY_ENABLED, BUG_BOUNTY_URL
    lines = [
        f"Contact: mailto:{SECURITY_CONTACT_EMAIL}",
        f"Preferred-Languages: en",
        f"Canonical: {request.url_root.rstrip('/')}/.well-known/security.txt",
        f"Policy: {request.url_root.rstrip('/')}/security",
        f"Expires: 2027-12-31T23:59:59Z",
    ]
    if BUG_BOUNTY_ENABLED and BUG_BOUNTY_URL:
        lines.append(f"Acknowledgments: {BUG_BOUNTY_URL}")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


# ─────────────────────────────────────────────────────────────────────────────
#  Security API routes (MFA, permissions, audit, API keys, IP allowlist)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/mfa-setup-required")
@login_required
def mfa_setup_required():
    """Page shown when admin enforces MFA and user hasn't set it up yet."""
    if _auth.is_user_mfa_enabled(session.get("user_id")):
        return redirect(url_for("dashboard"))
    return render_template("mfa_setup_required.html")


@app.route("/api/admin/enforce-mfa", methods=["POST"])
@admin_required
def api_enforce_mfa():
    """Admin toggle: force all users in tenant to enable MFA."""
    data = request.get_json() or {}
    enabled = 1 if data.get("enabled") else 0
    conn = get_db()
    try:
        conn.execute(
            "UPDATE tenants SET mfa_enforced = ? WHERE id = ?",
            (enabled, session.get("tenant_id", 1))
        )
        conn.commit()
        from audit import log_event
        log_event(session.get("tenant_id"), session.get("user_id"),
                  "mfa_enforcement_toggled", details=f"enabled={enabled}")
        return jsonify({"ok": True, "mfa_enforced": bool(enabled)})
    finally:
        conn.close()


@app.route("/api/admin/enforce-single-session", methods=["POST"])
@admin_required
def api_enforce_single_session():
    """Admin toggle: enforce single active session per user."""
    data = request.get_json() or {}
    enabled = 1 if data.get("enabled") else 0
    conn = get_db()
    try:
        conn.execute(
            "UPDATE tenants SET single_session_enforced = ? WHERE id = ?",
            (enabled, session.get("tenant_id", 1))
        )
        conn.commit()
        from audit import log_event
        log_event(session.get("tenant_id"), session.get("user_id"),
                  "single_session_enforcement_toggled", details=f"enabled={enabled}")
        return jsonify({"ok": True, "single_session_enforced": bool(enabled)})
    finally:
        conn.close()


@app.route("/api/admin/active-sessions")
@admin_required
def api_active_sessions():
    """View all active sessions for the tenant — see who's logged in right now."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT s.user_id, u.name, u.email, s.ip_address, s.user_agent, "
            "s.created_at, s.last_seen "
            "FROM active_sessions s JOIN users u ON s.user_id = u.id "
            "WHERE u.tenant_id = ? ORDER BY s.last_seen DESC",
            (session.get("tenant_id", 1),)
        ).fetchall()
        return jsonify({"sessions": [dict(r) for r in rows]})
    finally:
        conn.close()


@app.route("/api/admin/kill-session/<int:target_user_id>", methods=["POST"])
@admin_required
def api_kill_session(target_user_id):
    """Admin force-logout a specific user."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM active_sessions WHERE user_id = ?", (target_user_id,))
        conn.commit()
        from audit import log_event
        log_event(session.get("tenant_id"), session.get("user_id"),
                  "session_killed_by_admin", resource=f"user:{target_user_id}")
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/auth/mfa/setup", methods=["GET"])
@login_required
def api_mfa_setup():
    result = _auth.setup_mfa(session.get("user_id"))
    return jsonify(result)


@app.route("/api/auth/mfa/enable", methods=["POST"])
@login_required
def api_mfa_enable():
    data = request.get_json() or {}
    code = data.get("code", "")
    result = _auth.enable_mfa(session.get("user_id"), code)
    return jsonify(result)


@app.route("/api/auth/mfa/disable", methods=["POST"])
@login_required
def api_mfa_disable():
    data = request.get_json() or {}
    password = data.get("password", "")
    result = _auth.disable_mfa(session.get("user_id"), password)
    return jsonify(result)


@app.route("/api/auth/api-keys", methods=["GET"])
@login_required
def api_list_keys():
    from api_auth import list_api_keys
    keys = list_api_keys(session.get("user_id"), session.get("tenant_id", 1))
    return jsonify({"keys": keys})


@app.route("/api/auth/api-keys", methods=["POST"])
@login_required
def api_create_key():
    from api_auth import create_api_key
    data = request.get_json() or {}
    result = create_api_key(
        user_id=session.get("user_id"),
        tenant_id=session.get("tenant_id", 1),
        name=data.get("name", ""),
        permissions=data.get("permissions"),
        expires_days=data.get("expires_days"),
    )
    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "api_key_created",
              details=f"name={data.get('name', '')}")
    return jsonify(result)


@app.route("/api/auth/api-keys/<int:key_id>", methods=["DELETE"])
@login_required
def api_revoke_key(key_id):
    from api_auth import revoke_api_key
    result = revoke_api_key(key_id, session.get("user_id"), session.get("tenant_id", 1))
    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "api_key_revoked",
              details=f"key_id={key_id}")
    return jsonify(result)


@app.route("/api/admin/permissions/<int:target_user_id>", methods=["GET"])
@admin_required
def api_get_permissions(target_user_id):
    from permissions import get_user_permissions
    perms = get_user_permissions(target_user_id, session.get("tenant_id", 1))
    return jsonify({"permissions": perms})


@app.route("/api/admin/permissions/<int:target_user_id>", methods=["PATCH"])
@admin_required
def api_set_permissions(target_user_id):
    from permissions import bulk_set_permissions
    data = request.get_json() or {}
    result = bulk_set_permissions(
        admin_user_id=session.get("user_id"),
        target_user_id=target_user_id,
        tenant_id=session.get("tenant_id", 1),
        permissions_map=data,
    )
    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "permissions_changed",
              resource=f"user:{target_user_id}",
              details=str(data)[:500])
    return jsonify(result)


@app.route("/api/admin/permissions/templates", methods=["GET"])
@admin_required
def api_list_permission_templates():
    from permissions import list_templates
    templates = list_templates(session.get("tenant_id", 1))
    return jsonify({"templates": templates})


@app.route("/api/admin/permissions/templates", methods=["POST"])
@admin_required
def api_save_permission_template():
    from permissions import save_template
    data = request.get_json() or {}
    result = save_template(
        tenant_id=session.get("tenant_id", 1),
        name=data.get("name", ""),
        permissions=data.get("permissions", {}),
        created_by=session.get("user_id"),
    )
    return jsonify(result)


@app.route("/api/admin/audit")
@admin_required
def api_audit_log():
    from audit import get_audit_log
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 50, type=int), 200)
    result = get_audit_log(
        tenant_id=session.get("tenant_id", 1),
        page=page,
        per_page=per_page,
        action_filter=request.args.get("action"),
        user_id_filter=request.args.get("user_id", type=int),
        date_from=request.args.get("from"),
        date_to=request.args.get("to"),
    )
    return jsonify(result)


@app.route("/api/admin/audit/user/<int:target_user_id>")
@admin_required
def api_user_audit(target_user_id):
    from audit import get_user_audit
    events = get_user_audit(target_user_id, session.get("tenant_id", 1))
    return jsonify({"events": events})


@app.route("/api/admin/ip-allowlist", methods=["GET"])
@admin_required
def api_list_ip_allowlist():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, ip_address, label, created_at FROM ip_allowlist WHERE tenant_id = ?",
            (session.get("tenant_id", 1),)
        ).fetchall()
        tenant = conn.execute(
            "SELECT COALESCE(ip_restriction_enabled, 0) as ip_restriction_enabled FROM tenants WHERE id = ?",
            (session.get("tenant_id", 1),)
        ).fetchone()
        return jsonify({
            "entries": [dict(r) for r in rows],
            "enabled": bool(tenant and tenant["ip_restriction_enabled"]),
        })
    finally:
        conn.close()


@app.route("/api/admin/ip-allowlist", methods=["POST"])
@admin_required
def api_add_ip_allowlist():
    data = request.get_json() or {}
    ip_addr = data.get("ip_address", "").strip()
    label = data.get("label", "").strip()
    if not ip_addr:
        return jsonify({"ok": False, "error": "IP address is required."}), 400
    # Validate IP/CIDR
    import ipaddress
    try:
        ipaddress.ip_network(ip_addr, strict=False)
    except ValueError:
        return jsonify({"ok": False, "error": "Invalid IP address or CIDR notation."}), 400
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO ip_allowlist (tenant_id, ip_address, label, created_by, created_at) VALUES (?,?,?,?,?)",
            (session.get("tenant_id", 1), ip_addr, label,
             session.get("user_id"), datetime.now().isoformat())
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/admin/ip-allowlist/<int:entry_id>", methods=["DELETE"])
@admin_required
def api_delete_ip_allowlist(entry_id):
    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM ip_allowlist WHERE id = ? AND tenant_id = ?",
            (entry_id, session.get("tenant_id", 1))
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/admin/ip-allowlist/toggle", methods=["POST"])
@admin_required
def api_toggle_ip_restriction():
    data = request.get_json() or {}
    enabled = 1 if data.get("enabled") else 0
    conn = get_db()
    try:
        conn.execute(
            "UPDATE tenants SET ip_restriction_enabled = ? WHERE id = ?",
            (enabled, session.get("tenant_id", 1))
        )
        conn.commit()
        from audit import log_event
        log_event(session.get("tenant_id"), session.get("user_id"),
                  "ip_restriction_toggled", details=f"enabled={enabled}")
        return jsonify({"ok": True})
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Compliance & WAF Admin routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/admin/compliance/status")
@admin_required
def api_compliance_status():
    from compliance import get_compliance_status
    return jsonify(get_compliance_status(session.get("tenant_id", 1)))


@app.route("/api/admin/compliance/access-review")
@admin_required
def api_access_review():
    from compliance import get_access_review_report
    from audit import log_event
    report = get_access_review_report(session.get("tenant_id", 1))
    log_event(session.get("tenant_id"), session.get("user_id"), "access_review_generated")
    return jsonify(report)


@app.route("/api/admin/compliance/export-user-data/<int:target_user_id>")
@admin_required
def api_export_user_data(target_user_id):
    from compliance import export_user_data
    return jsonify(export_user_data(target_user_id, session.get("tenant_id", 1)))


@app.route("/api/admin/compliance/anonymize/<int:target_user_id>", methods=["POST"])
@admin_required
def api_anonymize_user(target_user_id):
    from compliance import anonymize_user
    return jsonify(anonymize_user(session.get("user_id"), target_user_id, session.get("tenant_id", 1)))


@app.route("/api/admin/compliance/purge-old-logs", methods=["POST"])
@admin_required
def api_purge_old_logs():
    from compliance import purge_old_audit_logs, purge_old_login_records
    audit_result = purge_old_audit_logs()
    login_result = purge_old_login_records()
    return jsonify({"audit": audit_result, "logins": login_result})


@app.route("/api/admin/waf/status")
@admin_required
def api_waf_status():
    from waf import get_banned_ips, get_top_requesters
    from config import CLOUDFLARE_ENABLED, BEHIND_PROXY, DDOS_RATE_LIMIT, DDOS_BAN_THRESHOLD
    return jsonify({
        "cloudflare_enabled": CLOUDFLARE_ENABLED,
        "behind_proxy": BEHIND_PROXY,
        "ddos_rate_limit": DDOS_RATE_LIMIT,
        "ddos_ban_threshold": DDOS_BAN_THRESHOLD,
        "banned_ips": get_banned_ips(),
        "top_requesters": get_top_requesters(),
    })


@app.route("/api/admin/waf/ban", methods=["POST"])
@admin_required
def api_waf_ban_ip():
    from waf import ban_ip
    data = request.get_json() or {}
    ip_addr = data.get("ip", "").strip()
    minutes = data.get("minutes", 60)
    if not ip_addr:
        return jsonify({"ok": False, "error": "IP address required."}), 400
    ban_ip(ip_addr, minutes)
    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "ip_manually_banned",
              details=f"ip={ip_addr}, minutes={minutes}")
    return jsonify({"ok": True})


@app.route("/api/admin/waf/unban", methods=["POST"])
@admin_required
def api_waf_unban_ip():
    from waf import unban_ip
    data = request.get_json() or {}
    ip_addr = data.get("ip", "").strip()
    if not ip_addr:
        return jsonify({"ok": False, "error": "IP address required."}), 400
    unban_ip(ip_addr)
    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "ip_unbanned",
              details=f"ip={ip_addr}")
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
#  Bug Bounty / Responsible Disclosure
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/security")
def security_page():
    """Public security page with responsible disclosure policy."""
    from config import SECURITY_CONTACT_EMAIL, BUG_BOUNTY_ENABLED, BUG_BOUNTY_URL
    return render_template("security_policy.html",
                           contact_email=SECURITY_CONTACT_EMAIL,
                           bug_bounty_enabled=BUG_BOUNTY_ENABLED,
                           bug_bounty_url=BUG_BOUNTY_URL)


# ─────────────────────────────────────────────────────────────────────────────
#  Main dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/onboarding")
@login_required
def onboarding_page():
    """First-run setup wizard."""
    if not session.get("user_id"):
        return redirect(url_for("dashboard"))

    status = _get_onboarding_status(session.get("user_id"))
    if status["completed"]:
        return redirect(url_for("dashboard"))

    return render_template(
        "onboarding.html",
        active_tab=None,
        hide_tab_strip=True,
        sv=STARTUP_TIME,
    )


@app.route("/api/onboarding/complete", methods=["POST"])
@login_required
def api_onboarding_complete():
    """Mark onboarding as completed for the current user."""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    final_step = data.get("step") or "complete"

    conn = get_db()
    try:
        conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_step = ?
               WHERE id = ?""",
            (final_step, user_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/help")
@login_required
def help_page():
    """Render the in-app help and documentation page."""
    return render_template("help.html", active_tab="help", sv=STARTUP_TIME)


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", sv=STARTUP_TIME, current_user=_auth.current_user(session))


# ─────────────────────────────────────────────────────────────────────────────
#  API — search / filter
# ─────────────────────────────────────────────────────────────────────────────

def _build_query(args, select="id, network, company_name, contact_name, email, phone_number, country, city, verified_status, verified_score, website_url, linkedin_url", paginate=False):
    country   = args.get("country",   "").strip()
    company   = args.get("company",   "").strip()
    name      = args.get("name",      "").strip()
    network   = args.get("network",   "").strip()
    has_email = args.get("has_email", "") == "1"
    has_phone = args.get("has_phone", "") == "1"
    sort_by   = args.get("sort",      "company_name")
    sort_dir  = args.get("dir",       "asc").lower()

    if sort_by  not in ("company_name", "country"):
        sort_by = "company_name"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "asc"

    sql    = f"SELECT {select} FROM contacts WHERE 1=1"
    params = []

    if country:
        sql += " AND country LIKE ? COLLATE NOCASE"
        params.append(f"%{country}%")
    if company:
        sql += " AND company_name LIKE ? COLLATE NOCASE"
        params.append(f"%{company}%")
    if name:
        sql += " AND contact_name LIKE ? COLLATE NOCASE"
        params.append(f"%{name}%")
    verify = args.get("verify", "").strip()
    if network:
        sql += " AND UPPER(network) = UPPER(?)"
        params.append(network)
    if verify:
        sql += " AND verified_status = ?"
        params.append(verify)
    if has_email:
        sql += " AND email IS NOT NULL AND TRIM(email) != ''"
    if has_phone:
        sql += " AND phone_number IS NOT NULL AND TRIM(phone_number) != ''"

    sql += f" ORDER BY {sort_by} COLLATE NOCASE {sort_dir.upper()}"

    if paginate:
        page = max(1, int(args.get("page", 1)))
        per_page = min(200, max(10, int(args.get("per_page", 50))))
        offset = (page - 1) * per_page
        sql += f" LIMIT {per_page} OFFSET {offset}"

    return sql, params


@app.route("/api/search")
@login_required
def api_search():
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(200, max(10, int(request.args.get("per_page", 50))))

    # Get paginated results
    sql, params = _build_query(request.args, paginate=True)
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()

    # Get total count for the same filters (without pagination)
    count_sql, count_params = _build_query(request.args, select="COUNT(*) AS total")
    total = conn.execute(count_sql, count_params).fetchone()["total"]
    conn.close()

    results = [dict(r) for r in rows]
    total_pages = max(1, -(-total // per_page))  # ceiling division
    return jsonify({
        "count": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "results": results,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  API — stats
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/version")
def api_version():
    return jsonify({"v": STARTUP_TIME})


@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_db()
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  COUNT(DISTINCT CASE
                      WHEN TRIM(COALESCE(country, '')) <> '' THEN TRIM(country)
                  END) AS countries,
                  COUNT(DISTINCT CASE
                      WHEN TRIM(COALESCE(network, '')) <> '' THEN TRIM(network)
                  END) AS networks
           FROM contacts"""
    ).fetchone()
    conn.close()
    return jsonify({
        "total": row["total"],
        "countries": row["countries"],
        "networks": row["networks"],
    })


@app.route("/api/verify-stats")
@login_required
def api_verify_stats():
    conn = get_db()
    rows = conn.execute(
        """SELECT verified_status, COUNT(*) as n
           FROM contacts GROUP BY verified_status"""
    ).fetchall()
    conn.close()
    counts = {r["verified_status"]: r["n"] for r in rows}
    total  = sum(counts.values())
    return jsonify({
        "total":      total,
        "verified":   counts.get("verified",   0),
        "review":     counts.get("review",     0),
        "flagged":    counts.get("flagged",     0),
        "unverified": counts.get("unverified", 0),
    })


# ─────────────────────────────────────────────────────────────────────────────
#  API — export CSV
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/export")
@feature_required("contacts", "export")
def api_export():
    sql, params = _build_query(request.args)
    conn  = get_db()
    rows  = conn.execute(sql, params).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["network", "company_name", "contact_name", "email", "phone_number", "country", "city"])
    for row in rows:
        writer.writerow([
            row["network"],
            row["company_name"],
            row["contact_name"],
            row["email"],
            row["phone_number"],
            row["country"],
            row["city"],
        ])

    from audit import log_event
    log_event(session.get("tenant_id"), session.get("user_id"), "data_exported",
              details=f"rows={len(rows)}", ip=request.remote_addr or "")

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts_export.csv"},
    )


# ─────────────────────────────────────────────────────────────────────────────
#  API — sync status & manual refresh
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/sync-status")
@login_required
def api_sync_status():
    with _sync_lock:
        s = dict(_sync_state)
    last = s["last_sync"]
    return jsonify({
        "row_count":   s["row_count"],
        "last_sync":   last.strftime("%Y-%m-%d %H:%M:%S") if last else None,
        "check_every": CHECK_INTERVAL,
    })


@app.route("/api/refresh", methods=["POST"])
@login_required
def api_refresh():
    """Manually trigger a CSV reimport right now."""
    if not os.path.exists(CSV_PATH):
        return jsonify({"ok": False, "error": f"CSV not found at {CSV_PATH}"})
    _run_import()
    with _sync_lock:
        s = dict(_sync_state)
    last = s["last_sync"]
    return jsonify({
        "ok":        True,
        "row_count": s["row_count"],
        "last_sync": last.strftime("%Y-%m-%d %H:%M:%S") if last else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  API — upload CSV from browser
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/upload-csv", methods=["POST"])
@feature_required("contacts", "write")
def api_upload_csv():
    from validators import sanitize_filename
    from werkzeug.utils import secure_filename as _secure_filename

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file received."})

    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "No filename."})

    safe_name = sanitize_filename(_secure_filename(f.filename))
    if not safe_name.lower().endswith(".csv"):
        return jsonify({"ok": False, "error": "File must be a .csv"})

    # Validate file content looks like text/CSV (not binary)
    header_bytes = f.read(512)
    f.seek(0)
    try:
        header_bytes.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return jsonify({"ok": False, "error": "File does not appear to be a valid CSV."})

    # Detect network from filename (whitelisted network names only)
    _ALLOWED_NETWORKS = {"WFA", "WWPC", "FIATA", "FREIGHTNET", "AHK-JAPAN", "IMPORT"}
    name_lower = safe_name.lower()
    if "wfa" in name_lower:
        network = "WFA"
    elif "wwpc" in name_lower:
        network = "WWPC"
    elif "fiata" in name_lower:
        network = "FIATA"
    elif "freightnet" in name_lower:
        network = "FREIGHTNET"
    elif "ahk" in name_lower:
        network = "AHK-JAPAN"
    else:
        network = "IMPORT"

    # Save into the app's data folder with safe path
    os.makedirs(DATA_DIR, exist_ok=True)
    save_name = f"upload_{network.lower().replace('-', '_')}.csv"
    save_path = os.path.join(DATA_DIR, save_name)
    # Verify resolved path is within DATA_DIR (prevent path traversal)
    if not os.path.realpath(save_path).startswith(os.path.realpath(DATA_DIR)):
        return jsonify({"ok": False, "error": "Invalid file path."}), 400
    f.save(save_path)

    try:
        result = import_csv(save_path, network_override=network)
        conn   = get_db()
        count  = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        conn.close()
        with _sync_lock:
            _sync_state["last_sync"]  = datetime.now()
            _sync_state["row_count"]  = count

        from audit import log_event
        log_event(session.get("tenant_id"), session.get("user_id"), "csv_imported",
                  resource=f"network:{network}", details=f"imported={result['imported']}",
                  ip=request.remote_addr or "")

        return jsonify({
            "ok":        True,
            "network":   network,
            "imported":  result["imported"],
            "row_count": count,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": "Import failed. Please check the CSV format."})


# ─────────────────────────────────────────────────────────────────────────────
#  Lanes — CSV import & API routes
# ─────────────────────────────────────────────────────────────────────────────

# ── Carrier → Alliance mapping (2025/2026) ────────────────────────────────
CARRIER_ALLIANCES = {
    # Gemini Cooperation (Maersk + Hapag-Lloyd, launched Feb 2025)
    "maersk":       "Gemini",
    "hapag-lloyd":  "Gemini",
    "hapag":        "Gemini",
    # Ocean Alliance (CMA CGM, COSCO, OOCL, Evergreen)
    "cma cgm":      "Ocean",
    "cma-cgm":      "Ocean",
    "cosco":        "Ocean",
    "oocl":         "Ocean",
    "evergreen":    "Ocean",
    # Premier Alliance (ONE, HMM, Yang Ming — formerly THE Alliance)
    "one":          "Premier",
    "hmm":          "Premier",
    "yang ming":    "Premier",
    # Independent
    "msc":          "Independent",
    "zim":          "Independent",
    "pil":          "Independent",
    "wan hai":      "Independent",
}

def carrier_alliance(carrier_name):
    """Return alliance name for a carrier, or empty string if unknown."""
    if not carrier_name:
        return ""
    key = carrier_name.strip().lower()
    for k, alliance in CARRIER_ALLIANCES.items():
        if k in key:
            return alliance
    return ""


def _migrate_lanes_carrier():
    """Add carrier, source, service, confidence, alliance, frequency columns if missing."""
    conn = get_db()
    from database import _get_existing_columns
    cols = _get_existing_columns(conn, "lanes")
    for col, default in [
        ("carrier",    "''"),
        ("source",     "'maersk'"),
        ("service",    "''"),
        ("confidence", "''"),
        ("alliance",   "''"),
        ("frequency",  "''"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE lanes ADD COLUMN {col} TEXT DEFAULT {default}")
    conn.commit()
    conn.close()


def import_lanes_csv(path):
    """Read maersk_lanes.csv and (re)populate maersk rows in the lanes table."""
    conn = get_db()
    conn.execute("DELETE FROM lanes WHERE source='maersk' OR source IS NULL OR source=''")
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute(
                """INSERT INTO lanes
                   (lane_key, origin_name, destination_name, lane_status,
                    last_checked, sailing_id, etd, eta, vessel, transit, route, booking_url,
                    carrier, alliance, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row.get("lane_key", ""),
                    row.get("origin_name", ""),
                    row.get("destination_name", ""),
                    row.get("lane_status", "active"),
                    row.get("last_checked", ""),
                    row.get("sailing_id", ""),
                    row.get("etd", ""),
                    row.get("eta", ""),
                    row.get("vessel", ""),
                    row.get("transit", ""),
                    row.get("route", ""),
                    row.get("point_to_point_url", ""),
                    "Maersk",
                    carrier_alliance("Maersk"),
                    "maersk",
                )
            )
    conn.commit()
    conn.close()
    print(f"[lanes] Imported Maersk lanes from {path}")


SCHEDULES_PATH = os.path.join(DATA_DIR, "shipping_schedules.csv")
_schedules_mtime = 0.0


def import_schedules_csv(path):
    """Read shipping_schedules.csv — supports both legacy and rich column formats."""
    global _schedules_mtime
    conn = get_db()
    conn.execute("DELETE FROM lanes WHERE source='schedules'")
    imported = 0
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        # Detect format: rich = has 'origin_port' / 'departure_date'
        rich = "origin_port" in headers or "departure_date" in headers
        for row in reader:
            if rich:
                origin      = (row.get("origin_port") or row.get("origin", "")).strip()
                destination = (row.get("destination_port") or row.get("destination", "")).strip()
                etd         = (row.get("departure_date") or row.get("etd", "")).strip()
                eta         = (row.get("arrival_date")   or row.get("eta", "")).strip()
                transit     = (row.get("transit_days")   or row.get("transit_time", "")).strip()
                vessel      = row.get("vessel_name", "").strip()
                service     = row.get("service", "").strip()
                confidence  = row.get("confidence", "").strip()
                carrier     = row.get("carrier", "").strip()
            else:
                origin      = row.get("origin", "").strip()
                destination = row.get("destination", "").strip()
                etd         = row.get("etd", "").strip()
                eta         = row.get("eta", "").strip()
                transit     = row.get("transit_time", "").strip()
                vessel      = row.get("vessel_name", "").strip()
                service     = ""
                confidence  = ""
                carrier     = row.get("carrier", "").strip()
            # Skip placeholder/low-confidence rows with no real vessel or service
            if confidence == "low" and not vessel and not service:
                continue
            if not origin or not destination:
                continue
            frequency = row.get("frequency", "").strip() if rich else ""
            alliance  = carrier_alliance(carrier)
            conn.execute(
                """INSERT INTO lanes
                   (carrier, alliance, origin_name, destination_name, lane_status,
                    etd, eta, vessel, transit, service, frequency, confidence, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (carrier, alliance, origin, destination, "active",
                 etd, eta, vessel, transit, service, frequency, confidence, "schedules")
            )
            imported += 1
    conn.commit()
    conn.close()
    _schedules_mtime = os.path.getmtime(path)
    print(f"[schedules] Imported {imported} sailings from {path}")


def _schedules_watcher():
    """Background thread — checks every 48h if shipping_schedules.csv changed."""
    global _schedules_mtime
    INTERVAL = 48 * 3600  # 48 hours
    while True:
        time.sleep(INTERVAL)
        try:
            if os.path.exists(SCHEDULES_PATH):
                mtime = os.path.getmtime(SCHEDULES_PATH)
                if mtime > _schedules_mtime:
                    print("[schedules] File updated — reimporting…")
                    import_schedules_csv(SCHEDULES_PATH)
                    print("[schedules] Auto-import complete.")
        except Exception as e:
            print(f"[schedules] Watcher error: {e}")


@app.route("/lanes")
@login_required
def lanes():
    return render_template("lanes.html", sv=STARTUP_TIME)


@app.route("/api/lanes/options")
@login_required
def api_lanes_options():
    conn = get_db()
    origins = [r[0] for r in conn.execute(
        "SELECT DISTINCT origin_name FROM lanes WHERE origin_name != '' ORDER BY origin_name"
    ).fetchall()]
    destinations = [r[0] for r in conn.execute(
        "SELECT DISTINCT destination_name FROM lanes WHERE destination_name != '' ORDER BY destination_name"
    ).fetchall()]
    carriers = [r[0] for r in conn.execute(
        "SELECT DISTINCT carrier FROM lanes WHERE carrier != '' ORDER BY carrier"
    ).fetchall()]
    conn.close()
    return jsonify({"origins": origins, "destinations": destinations, "carriers": carriers})


@app.route("/api/lanes/search")
@login_required
def api_lanes_search():
    origin      = request.args.get("origin",      "").strip()
    destination = request.args.get("destination", "").strip()
    vessel_q    = request.args.get("vessel",      "").strip()
    carrier_q   = request.args.get("carrier",     "").strip()
    lane_group  = request.args.get("lane_group",  "").strip()

    conn = get_db()

    # If lane_group selected, query vessel_schedules (richer, Codex-sourced data)
    if lane_group:
        sql    = """SELECT id, origin AS origin_name, destination AS destination_name,
                           'active' AS lane_status, NULL AS last_checked, NULL AS sailing_id,
                           etd, eta, vessel_name AS vessel, transit_time AS transit,
                           NULL AS route, NULL AS booking_url, carrier, 'schedules' AS source,
                           service, NULL AS confidence, NULL AS alliance, NULL AS frequency,
                           NULL AS locode_origin, NULL AS locode_dest
                    FROM vessel_schedules WHERE lane = ?"""
        params = [lane_group]
        if carrier_q:
            sql += " AND LOWER(carrier) LIKE LOWER(?)"
            params.append(f"%{carrier_q}%")
        if origin:
            sql += " AND LOWER(origin) LIKE LOWER(?)"
            params.append(f"%{origin}%")
        if destination:
            sql += " AND LOWER(destination) LIKE LOWER(?)"
            params.append(f"%{destination}%")
        if vessel_q:
            sql += " AND LOWER(vessel_name) LIKE LOWER(?)"
            params.append(f"%{vessel_q}%")
        sql += " ORDER BY etd ASC LIMIT 500"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    # Default: query lanes table
    sql    = "SELECT * FROM lanes WHERE 1=1"
    params = []
    if origin:
        sql += " AND LOWER(origin_name) = LOWER(?)"
        params.append(origin)
    if destination:
        sql += " AND LOWER(destination_name) = LOWER(?)"
        params.append(destination)
    if vessel_q:
        sql += " AND LOWER(vessel) LIKE LOWER(?)"
        params.append(f"%{vessel_q}%")
    if carrier_q:
        sql += " AND LOWER(carrier) = LOWER(?)"
        params.append(carrier_q)

    sql += " ORDER BY CASE WHEN lane_status='active' AND etd != '' THEN 0 ELSE 1 END, etd ASC LIMIT 500"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────────────────────────────────────
#  Port → Region mapping  (used by new unified schedules UI)
# ─────────────────────────────────────────────────────────────────────────────

def _build_port_like_clause(ports, column):
    """Return (sql_fragment, params) for matching a column against a list of port names."""
    if not ports:
        return "1=0", []
    clauses = " OR ".join([f"LOWER({column}) LIKE LOWER(?)" for _ in ports])
    params  = [f"%{p}%" for p in ports]
    return f"({clauses})", params


@app.route("/schedules")
@login_required
def schedules_page():
    return render_template("schedules.html", active_tab="schedules", sv=STARTUP_TIME)


@app.route("/api/schedules/search")
@login_required
def api_schedules_search():
    ensure_schedule_schema()
    origin_region = request.args.get("origin_region", "").strip()
    dest_region   = request.args.get("dest_region",   "").strip()
    carrier_q     = request.args.get("carrier",       "").strip()
    vessel_q      = request.args.get("vessel",        "").strip()

    # Legacy params (old schedules.html still in use on /api/schedules/search)
    lane_q   = request.args.get("lane",   "").strip()
    origin_q = request.args.get("origin", "").strip()
    dest_q   = request.args.get("dest",   "").strip()

    sql    = "SELECT * FROM vessel_schedules WHERE 1=1"
    params = []

    if origin_region and origin_region in ORIGIN_PORTS:
        frag, p = _build_port_like_clause(ORIGIN_PORTS[origin_region], "origin")
        sql    += f" AND {frag}"
        params += p
    elif origin_q:
        sql    += " AND LOWER(origin) LIKE LOWER(?)"
        params.append(f"%{origin_q}%")

    if dest_region and dest_region in DEST_PORTS:
        frag, p = _build_port_like_clause(DEST_PORTS[dest_region], "destination")
        sql    += f" AND {frag}"
        params += p
    elif dest_q:
        sql    += " AND LOWER(destination) LIKE LOWER(?)"
        params.append(f"%{dest_q}%")

    if lane_q:
        sql    += " AND lane = ?"
        params.append(lane_q)
    if carrier_q:
        sql    += " AND LOWER(carrier) LIKE LOWER(?)"
        params.append(f"%{carrier_q}%")
    if vessel_q:
        sql    += " AND LOWER(vessel_name) LIKE LOWER(?)"
        params.append(f"%{vessel_q}%")

    sql += " ORDER BY etd ASC LIMIT 500"
    conn  = get_db()
    rows  = conn.execute(sql, params).fetchall()
    conn.close()
    row_dicts = [dict(r) for r in rows]
    row_dicts = enrich_schedules_with_predictions(row_dicts)
    row_dicts = enrich_schedules_with_reliability(row_dicts)
    return jsonify(row_dicts)


@app.route("/api/schedules/lane-status")
@login_required
def api_schedules_lane_status():
    """Return availability map: { origin_region: { dest_region: bool } }"""
    ensure_schedule_schema()
    conn = get_db()
    result = {}
    for origin_region, origin_ports in ORIGIN_PORTS.items():
        result[origin_region] = {}
        for dest_region, dest_ports in DEST_PORTS.items():
            if not origin_ports or not dest_ports:
                result[origin_region][dest_region] = False
                continue
            orig_frag, orig_p = _build_port_like_clause(origin_ports, "origin")
            dest_frag, dest_p = _build_port_like_clause(dest_ports,   "destination")
            sql = (f"SELECT COUNT(*) FROM vessel_schedules "
                   f"WHERE {orig_frag} AND {dest_frag} LIMIT 1")
            count = conn.execute(sql, orig_p + dest_p).fetchone()[0]
            result[origin_region][dest_region] = count > 0
    conn.close()
    return jsonify(result)


@app.route("/api/schedules/options")
@login_required
def api_schedules_options():
    ensure_schedule_schema()
    conn     = get_db()
    lanes    = [r[0] for r in conn.execute("SELECT DISTINCT lane FROM vessel_schedules ORDER BY lane").fetchall()]
    carriers = [r[0] for r in conn.execute("SELECT DISTINCT carrier FROM vessel_schedules ORDER BY carrier").fetchall()]
    origins  = [r[0] for r in conn.execute("SELECT DISTINCT origin FROM vessel_schedules ORDER BY origin").fetchall()]
    conn.close()
    return jsonify({"lanes": lanes, "carriers": carriers, "origins": origins})


@app.route("/api/schedules/record-arrival", methods=["POST"])
@login_required
def api_record_arrival():
    """Record actual arrival for a sailing. Body: { schedule_id, actual_eta }"""
    payload = request.get_json(silent=True) or {}
    schedule_id = payload.get("schedule_id")
    actual_eta = str(payload.get("actual_eta", "")).strip()

    if not schedule_id or not actual_eta:
        return jsonify({"ok": False, "error": "schedule_id and actual_eta are required"}), 400

    try:
        result = mark_arrived(int(schedule_id), actual_eta)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True, "arrival": result})


@app.route("/api/schedules/delay-stats")
@login_required
def api_delay_stats():
    """Return delay stats summary. Optional filters: carrier, origin, destination."""
    init_predictive_db()
    carrier_q = request.args.get("carrier", "").strip()
    origin_q = request.args.get("origin", "").strip()
    destination_q = request.args.get("destination", "").strip()

    sql = "SELECT * FROM delay_stats WHERE 1=1"
    params = []

    if carrier_q:
        sql += " AND LOWER(carrier) LIKE LOWER(?)"
        params.append(f"%{carrier_q}%")
    if origin_q:
        sql += " AND LOWER(origin) LIKE LOWER(?)"
        params.append(f"%{origin_q}%")
    if destination_q:
        sql += " AND LOWER(destination) LIKE LOWER(?)"
        params.append(f"%{destination_q}%")

    sql += " ORDER BY sample_count DESC, avg_delay_hours DESC, carrier ASC, origin ASC, destination ASC LIMIT 500"
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/schedules/reliability/leaderboard")
@login_required
def api_reliability_leaderboard():
    """Return carrier reliability leaderboard."""
    period = request.args.get("period", "90d")
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    return jsonify(get_carrier_leaderboard(period, limit))


@app.route("/api/schedules/reliability/lane")
@login_required
def api_reliability_lane():
    """Return per-port-pair reliability for a lane."""
    origin_region = request.args.get("origin_region", "")
    dest_region = request.args.get("dest_region", "")
    period = request.args.get("period", "90d")
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        limit = 20
    return jsonify(get_lane_leaderboard(origin_region, dest_region, period, limit))


@app.route("/api/schedules/reliability/recompute", methods=["POST"])
@login_required
def api_reliability_recompute():
    """Trigger reliability score recomputation in a background thread."""
    threading.Thread(target=compute_reliability_scores, daemon=True).start()
    return jsonify({"status": "started", "message": "Recomputing reliability scores..."})


@app.route("/api/schedules/stats")
@login_required
def api_schedules_stats():
    ensure_schedule_schema()
    init_predictive_db()
    init_reliability_db()
    conn = get_db()
    total    = conn.execute("SELECT COUNT(*) FROM vessel_schedules").fetchone()[0]
    carriers = conn.execute("SELECT COUNT(DISTINCT carrier) FROM vessel_schedules").fetchone()[0]

    # Count lanes that have data (origin+destination combos matching our regions)
    lane_count  = conn.execute("SELECT COUNT(DISTINCT lane) FROM vessel_schedules").fetchone()[0]

    # Last updated timestamp
    last_row = conn.execute(
        "SELECT COALESCE(last_checked, imported_at) FROM vessel_schedules "
        "WHERE COALESCE(last_checked, imported_at) IS NOT NULL "
        "ORDER BY COALESCE(last_checked, imported_at) DESC LIMIT 1"
    ).fetchone()
    last_updated = "—"
    if last_row and last_row[0]:
        try:
            dt = datetime.fromisoformat(str(last_row[0]).replace("T", " "))
            last_updated = f"{dt.strftime('%b')} {dt.day}"
        except Exception:
            last_updated = str(last_row[0])[:10]

    source_counts = {"csv": 0, "api": 0}
    for source_name, count in conn.execute(
        """
        SELECT COALESCE(NULLIF(data_source, ''), 'csv') AS source_name, COUNT(*)
        FROM vessel_schedules
        GROUP BY source_name
        """
    ).fetchall():
        source_counts[str(source_name)] = count

    source_lane_counts = {"csv": 0, "api": 0}
    for source_name, count in conn.execute(
        """
        SELECT COALESCE(NULLIF(data_source, ''), 'csv') AS source_name, COUNT(DISTINCT lane)
        FROM vessel_schedules
        GROUP BY source_name
        """
    ).fetchall():
        source_lane_counts[str(source_name)] = count

    try:
        gaps = conn.execute("SELECT COUNT(*) FROM schedule_gaps").fetchone()[0]
    except Exception:
        gaps = 0

    try:
        predictions_available = conn.execute("SELECT COUNT(*) FROM delay_stats").fetchone()[0] > 0
        avg_delay_hours = conn.execute(
            """
            SELECT ROUND(AVG(delay_hours), 2)
            FROM voyage_actuals
            WHERE delay_hours IS NOT NULL
              AND actual_eta IS NOT NULL
              AND substr(COALESCE(actual_eta, scheduled_eta), 1, 10) >= ?
            """,
            ((datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d"),),
        ).fetchone()[0]
    except Exception:
        predictions_available = False
        avg_delay_hours = None

    try:
        reliability_available = conn.execute("SELECT COUNT(*) FROM reliability_scores").fetchone()[0] > 0
    except Exception:
        reliability_available = False

    top_carrier = None
    top_carrier_pct = None
    leaderboard = get_carrier_leaderboard("90d", 1) if reliability_available else []
    if leaderboard:
        top_carrier = leaderboard[0]["carrier"]
        top_carrier_pct = float(leaderboard[0]["on_time_pct"] or 0)

    by_lane = conn.execute(
        "SELECT lane, COUNT(*), COUNT(DISTINCT carrier) FROM vessel_schedules GROUP BY lane ORDER BY lane"
    ).fetchall()
    conn.close()
    return jsonify({
        "total":          total,
        "carriers":       carriers,
        "lanes":          lane_count,
        "lanes_with_data": lane_count,
        "gaps":           gaps,
        "last_updated":   last_updated,
        "data_sources":   source_counts,
        "source_lanes":   source_lane_counts,
        "predictions_available": predictions_available,
        "avg_delay_hours": avg_delay_hours,
        "reliability_available": reliability_available,
        "top_carrier": top_carrier,
        "top_carrier_pct": top_carrier_pct,
        "by_lane": [{"lane": r[0], "sailings": r[1], "carriers": r[2]} for r in by_lane],
    })


@app.route("/api/schedules/sync", methods=["POST"])
@login_required
def api_schedules_sync():
    """Trigger manual schedule sync from carrier APIs."""
    if session.get("user_role") != "admin":
        return jsonify({"ok": False, "error": "Admin access required."}), 403
    start_background_sync()
    return jsonify({"status": "started", "message": "Syncing schedules from carrier APIs..."})

@app.route("/api/lanes/stats")
@login_required
def api_lanes_stats():
    conn = get_db()
    total  = conn.execute("SELECT COUNT(*) FROM lanes").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM lanes WHERE lane_status='active'").fetchone()[0]
    origins = conn.execute(
        "SELECT COUNT(DISTINCT origin_name) FROM lanes WHERE origin_name != ''"
    ).fetchone()[0]
    destinations = conn.execute(
        "SELECT COUNT(DISTINCT destination_name) FROM lanes WHERE destination_name != ''"
    ).fetchone()[0]
    conn.close()
    return jsonify({
        "total": total,
        "active": active,
        "origins": origins,
        "destinations": destinations,
    })




# ─────────────────────────────────────────────────────────────────────────────
#  Email client detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect_email_clients():
    """Scan common install paths + Windows registry for email clients."""
    clients = []

    # ── Gmail (always available — opens in browser) ───────────────────────
    clients.append({
        "id":   "gmail",
        "name": "Gmail",
        "type": "web",
        "url":  "https://mail.google.com/mail/?view=cm&fs=1&to={email}",
    })

    # ── Microsoft Outlook (desktop) ───────────────────────────────────────
    outlook_exe = None
    outlook_paths = [
        r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files\Microsoft Office\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\Office16\OUTLOOK.EXE",
        r"C:\Program Files\Microsoft Office\Office15\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\Office15\OUTLOOK.EXE",
        r"C:\Program Files\Microsoft Office\Office14\OUTLOOK.EXE",
    ]
    # Also check Windows registry
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\OUTLOOK.EXE"
        )
        reg_path = winreg.QueryValue(key, None)
        winreg.CloseKey(key)
        if reg_path:
            outlook_paths.insert(0, reg_path.strip('"'))
    except Exception:
        pass
    for p in outlook_paths:
        if os.path.exists(p):
            outlook_exe = p
            break
    if outlook_exe:
        clients.append({
            "id":   "outlook",
            "name": "Microsoft Outlook",
            "type": "desktop",
            "path": outlook_exe,
        })

    # ── Mozilla Thunderbird ───────────────────────────────────────────────
    tb_exe = None
    tb_paths = [
        r"C:\Program Files\Mozilla Thunderbird\thunderbird.exe",
        r"C:\Program Files (x86)\Mozilla Thunderbird\thunderbird.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Thunderbird\thunderbird.exe"),
    ]
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\thunderbird.exe"
        )
        reg_path = winreg.QueryValue(key, None)
        winreg.CloseKey(key)
        if reg_path:
            tb_paths.insert(0, reg_path.strip('"'))
    except Exception:
        pass
    for p in tb_paths:
        if os.path.exists(p):
            tb_exe = p
            break
    if tb_exe:
        clients.append({
            "id":   "thunderbird",
            "name": "Mozilla Thunderbird",
            "type": "desktop",
            "path": tb_exe,
        })

    # ── eM Client ─────────────────────────────────────────────────────────
    em_paths = [
        r"C:\Program Files\eM Client\MailClient.exe",
        r"C:\Program Files (x86)\eM Client\MailClient.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\eM Client\MailClient.exe"),
        os.path.expandvars(r"%APPDATA%\eM Client\MailClient.exe"),
    ]
    for p in em_paths:
        if os.path.exists(p):
            clients.append({
                "id":   "emclient",
                "name": "eM Client",
                "type": "desktop",
                "path": p,
            })
            break

    # ── Windows Mail (built-in) ───────────────────────────────────────────
    # Detect via registry: Windows Mail registers a shell open command
    winmail_found = False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\HxMail.exe"
        )
        winreg.CloseKey(key)
        winmail_found = True
    except Exception:
        pass
    if winmail_found:
        clients.append({
            "id":   "winmail",
            "name": "Windows Mail",
            "type": "mailto",
        })

    # ── Default mail app fallback ─────────────────────────────────────────
    clients.append({
        "id":   "default",
        "name": "Default Mail App",
        "type": "mailto",
    })

    return clients


_SAFE_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@app.route("/api/email-clients")
@login_required
def api_email_clients():
    return jsonify(_detect_email_clients())


@app.route("/api/compose-email")
@login_required
def api_compose_email():
    """Launch a desktop email client with a pre-filled To: address."""
    client_id = request.args.get("client", "").strip()
    email     = request.args.get("email",  "").strip()

    if not email or not _SAFE_EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Invalid email address"})

    clients = _detect_email_clients()
    client  = next((c for c in clients if c["id"] == client_id), None)

    if not client or client.get("type") != "desktop":
        return jsonify({"ok": False, "error": "Desktop client not found"})

    path = client.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "error": "Application executable not found"})

    try:
        if client_id == "outlook":
            subprocess.Popen([path, "/c", "ipm.note", "/m", email])
        elif client_id == "thunderbird":
            subprocess.Popen([path, "-compose", f"to='{email}'"])
        else:
            # eM Client and others understand mailto:
            subprocess.Popen([path, f"mailto:{email}"])
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
#  Rates — rate request & response system
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/rates")
@login_required
def rates():
    from config import GRAPH_CLIENT_SECRET
    return render_template("rates.html", sv=STARTUP_TIME, email_configured=bool(GRAPH_CLIENT_SECRET))


@app.route("/api/rates")
@feature_required("rates")
def api_rates():
    """List rates with optional filters: carrier, origin, destination, cycle, verified."""
    carrier     = request.args.get("carrier",     "").strip()
    origin      = request.args.get("origin",      "").strip()
    destination = request.args.get("destination", "").strip()
    cycle       = request.args.get("cycle",       "").strip()
    verified    = request.args.get("verified",    "").strip()

    sql    = """
        SELECT r.*, c.company_name, c.country, c.contact_name
        FROM rates r
        LEFT JOIN contacts c ON c.id = r.contact_id
        WHERE 1=1
    """
    params = []

    if carrier:
        sql += " AND LOWER(r.carrier) LIKE LOWER(?)"
        params.append(f"%{carrier}%")
    if origin:
        sql += " AND LOWER(r.origin) LIKE LOWER(?)"
        params.append(f"%{origin}%")
    if destination:
        sql += " AND LOWER(r.destination) LIKE LOWER(?)"
        params.append(f"%{destination}%")
    if cycle:
        sql += " AND r.cycle = ?"
        params.append(cycle)
    if verified in ("0", "1"):
        sql += " AND r.verified = ?"
        params.append(int(verified))

    sql += " ORDER BY r.parsed_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/rates/stats")
@login_required
def api_rates_stats():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM rates").fetchone()[0]
    conn.close()

    conn = get_db()
    req_total = conn.execute("SELECT COUNT(*) FROM rate_requests").fetchone()[0]
    req_resp  = conn.execute(
        "SELECT COUNT(*) FROM rate_requests WHERE responded = 1"
    ).fetchone()[0]
    avg_quality = conn.execute(
        "SELECT AVG(response_quality) FROM rate_requests WHERE responded = 1"
    ).fetchone()[0] or 0
    pending = conn.execute(
        "SELECT COUNT(*) FROM rate_requests WHERE responded = 0"
    ).fetchone()[0]
    conn.close()

    response_rate = round(req_resp / req_total * 100, 1) if req_total else 0

    return jsonify({
        "rates_collected": total,
        "avg_response_rate": response_rate,
        "avg_quality_score": round(avg_quality, 1),
        "pending_responses": pending,
    })


@app.route("/api/rates/options")
@login_required
def api_rates_options():
    """Return distinct filter values for the rates table."""
    conn = get_db()
    carriers = [r[0] for r in conn.execute(
        "SELECT DISTINCT carrier FROM rates WHERE carrier != '' ORDER BY carrier"
    ).fetchall()]
    origins = [r[0] for r in conn.execute(
        "SELECT DISTINCT origin FROM rates WHERE origin != '' ORDER BY origin"
    ).fetchall()]
    destinations = [r[0] for r in conn.execute(
        "SELECT DISTINCT destination FROM rates WHERE destination != '' ORDER BY destination"
    ).fetchall()]
    cycles = [r[0] for r in conn.execute(
        "SELECT DISTINCT cycle FROM rates WHERE cycle != '' ORDER BY cycle DESC"
    ).fetchall()]
    conn.close()
    return jsonify({
        "carriers":     carriers,
        "origins":      origins,
        "destinations": destinations,
        "cycles":       cycles,
    })


@app.route("/api/rates/parse", methods=["POST"])
@feature_required("rates", "write")
def api_rates_parse():
    """Parse an email body for rate data.
    Body JSON: {email_body: str, contact_id: int, cycle: str}
    """
    data       = request.get_json() or {}
    email_body = data.get("email_body", "").strip()
    contact_id = data.get("contact_id")
    cycle      = data.get("cycle", "").strip()

    if not email_body:
        return jsonify({"ok": False, "error": "email_body is required."})
    if not contact_id:
        return jsonify({"ok": False, "error": "contact_id is required."})
    if not cycle:
        # Default to current cycle if not provided
        cycle = rate_engine._build_cycle_for_date(datetime.now())

    result = rate_engine.parse_rate_response(email_body, int(contact_id), cycle)
    return jsonify({"ok": True, **result})


@app.route("/api/rates/verify/<int:rate_id>", methods=["PATCH"])
@login_required
def api_rate_verify(rate_id):
    """Toggle verified flag on a rate record."""
    data     = request.get_json() or {}
    verified = int(bool(data.get("verified", 1)))
    conn     = get_db()
    conn.execute("UPDATE rates SET verified = ? WHERE id = ?", (verified, rate_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "verified": verified})


# ─────────────────────────────────────────────────────────────────────────────
#  Contact Intelligence API
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/contacts/<int:contact_id>/intelligence")
@login_required
def api_contact_intelligence(contact_id):
    """Full intelligence card for a contact — behavioral profile, interests, call prep."""
    card = _ce.get_intelligence_card(contact_id)
    if not card:
        return jsonify({"ok": False, "error": "Contact not found"}), 404
    return jsonify({"ok": True, **card})


@app.route("/api/contacts/<int:contact_id>/interests", methods=["POST"])
@login_required
def api_contact_interests(contact_id):
    """Store confirmed interests for a contact.
    Body JSON: {interests: ["football", "cooking", ...]}
    Or: {reply_text: "raw reply text to parse"}
    """
    data = request.get_json() or {}
    if "reply_text" in data:
        interests = _ce.parse_interests_from_reply(data["reply_text"])
    else:
        interests = data.get("interests", [])
    _ce.store_interests(contact_id, interests)
    return jsonify({"ok": True, "interests": interests})


@app.route("/api/contacts/<int:contact_id>/responded", methods=["POST"])
@login_required
def api_contact_responded(contact_id):
    """Record that a contact responded. Updates behavioral scoring.
    Body JSON: {sent_at: "2026-03-21T10:00:00"}
    """
    data    = request.get_json() or {}
    sent_at = data.get("sent_at", "")
    result  = _ce.record_response(contact_id, sent_at)
    return jsonify({"ok": True, **result})


@app.route("/api/contacts/<int:contact_id>/profile")
@login_required
def api_contact_profile(contact_id):
    """Return the raw contact profile (behavioral + interests)."""
    profile = _ce.get_or_create_profile(contact_id)
    return jsonify({"ok": True, "profile": profile})


@app.route("/api/test-email", methods=["POST"])
@login_required
def api_test_email():
    """Send a test email to pricing@flashcargoglobal.com to verify Graph API works."""
    try:
        _mailer.test_connection()
        return jsonify({"ok": True, "message": "Test email sent to pricing@flashcargoglobal.com"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/rates/gaps")
@login_required
def api_rates_gaps():
    """Return full gap analysis report."""
    report = rate_engine.gap_report()
    return jsonify(report)


@app.route("/api/rate-requests")
@login_required
def api_rate_requests():
    """List all rate requests with contact info."""
    cycle = request.args.get("cycle", "").strip()

    sql = """
        SELECT rr.*, c.company_name, c.country, c.contact_name, c.email
        FROM rate_requests rr
        LEFT JOIN contacts c ON c.id = rr.contact_id
        WHERE 1=1
    """
    params = []
    if cycle:
        sql += " AND rr.cycle = ?"
        params.append(cycle)
    sql += " ORDER BY rr.sent_at DESC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/rate-requests/send", methods=["POST"])
@login_required
def api_rate_requests_send():
    """Manually trigger a send cycle.
    Body JSON: {cycle: str}  (optional — defaults to current schedule cycle)
    """
    data  = request.get_json() or {}
    cycle = data.get("cycle", "").strip()

    if not cycle:
        cycle = rate_engine._build_cycle_for_date(datetime.now())

    result = rate_engine.send_rate_requests(cycle)
    return jsonify({"ok": True, "cycle": cycle, **result})


@app.route("/api/rate-requests/preview-email", methods=["POST"])
@login_required
def api_rate_requests_preview():
    """Preview the email that would be sent to a contact.
    Body JSON: {contact_id: int}
    """
    data       = request.get_json() or {}
    contact_id = data.get("contact_id")
    if not contact_id:
        return jsonify({"ok": False, "error": "contact_id is required."})

    conn    = get_db()
    contact = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (int(contact_id),)
    ).fetchone()
    conn.close()

    if not contact:
        return jsonify({"ok": False, "error": "Contact not found."})

    try:
        result = rate_engine.build_request_email(dict(contact))
        return jsonify({"ok": True, **result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
#  Rates — new cycle-based API
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/rates/cycles")
@login_required
def api_rates_cycles():
    """List all rate cycles with basic stats."""
    conn   = get_db()
    cycles = conn.execute(
        "SELECT * FROM rate_cycles ORDER BY valid_from DESC"
    ).fetchall()
    conn.close()
    result = []
    for c in cycles:
        d = dict(c)
        try:
            stats = rate_engine.get_cycle_stats(d["id"])
            d.update(stats)
        except Exception:
            pass
        result.append(d)
    return jsonify(result)


@app.route("/api/rates/cycle/<int:cycle_id>/stats")
@login_required
def api_rates_cycle_stats(cycle_id):
    """Stats for one cycle."""
    stats = rate_engine.get_cycle_stats(cycle_id)
    return jsonify(stats)


@app.route("/api/rates/cycle", methods=["POST"])
@login_required
def api_rates_cycle_create():
    """Create a new cycle.
    Body JSON: {month: int, year: int, cycle_num: int}
    """
    data      = request.get_json() or {}
    month     = int(data.get("month", 0))
    year      = int(data.get("year",  0))
    cycle_num = int(data.get("cycle_num", 1))

    if not (1 <= month <= 12) or year < 2024:
        return jsonify({"ok": False, "error": "Invalid month or year."})
    if cycle_num not in (1, 2):
        return jsonify({"ok": False, "error": "cycle_num must be 1 or 2."})

    try:
        cycle = rate_engine.generate_cycle(month, year, cycle_num)
        return jsonify({"ok": True, "cycle": cycle})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/rates/outreach")
@login_required
def api_rates_outreach():
    """Outreach status for current/latest cycle.
    Optional ?cycle_id= filter.
    """
    cycle_id = request.args.get("cycle_id", "").strip()

    sql = """
        SELECT ro.*,
               c.company_name, c.contact_name, c.country, c.email, c.network
        FROM rate_outreach ro
        LEFT JOIN contacts c ON c.id = ro.contact_id
        WHERE 1=1
    """
    params = []
    if cycle_id:
        sql += " AND ro.cycle_id = ?"
        params.append(int(cycle_id))
    else:
        # Default to latest cycle
        sql += """ AND ro.cycle_id = (
            SELECT id FROM rate_cycles ORDER BY valid_from DESC LIMIT 1
        )"""

    sql += " ORDER BY ro.contact_company ASC"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/rates/<int:rate_id>", methods=["PATCH"])
@login_required
def api_rate_patch(rate_id):
    """Manually update a rate."""
    data   = request.get_json() or {}
    fields = []
    params = []
    allowed = ["carrier", "origin", "destination", "rate_20ft", "rate_40ft",
               "valid_from", "valid_to", "etd", "vessel", "currency", "notes", "verified"]
    for col in allowed:
        if col in data:
            fields.append(f"{col} = ?")
            params.append(data[col])
    if not fields:
        return jsonify({"ok": False, "error": "Nothing to update."})
    params.append(rate_id)
    conn = get_db()
    conn.execute(f"UPDATE rates SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/rates/<int:rate_id>", methods=["DELETE"])
@feature_required("rates", "delete")
def api_rate_delete(rate_id):
    """Delete a rate record."""
    conn = get_db()
    conn.execute("DELETE FROM rates WHERE id = ?", (rate_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/rates/gaps/by-region")
@login_required
def api_rates_gaps_by_region():
    """Gap report grouped by region and field, sorted by occurrences desc."""
    conn = get_db()
    rows = conn.execute(
        """SELECT rg.region, rg.gap_field, SUM(rg.occurrences) as total_occurrences,
                  MAX(rg.last_seen) as last_seen
           FROM rate_gaps rg
           WHERE rg.gap_field != '' AND rg.gap_field IS NOT NULL
           GROUP BY rg.region, rg.gap_field
           ORDER BY total_occurrences DESC"""
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/contacts-ids")
@login_required
def api_contacts_ids():
    """Return contacts with id exposed — used by parse email modal."""
    conn = get_db()
    rows = conn.execute(
        """SELECT id, company_name, contact_name, email, country, network
           FROM contacts
           WHERE email IS NOT NULL AND TRIM(email) != ''
           ORDER BY company_name ASC"""
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────────────────────────────────────
#  Learning — progress tracker + admin leaderboard
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/learning/progress", methods=["GET"])
@feature_required("learning")
def api_learning_progress():
    """Return learning progress for all users (admin) or current user."""
    conn = get_db()
    rows = conn.execute("""
        SELECT lp.user_id, lp.book, lp.lesson, lp.score, lp.completed_at,
               u.name, u.email
        FROM learning_progress lp
        LEFT JOIN users u ON u.id = lp.user_id
        ORDER BY lp.completed_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/learning/progress", methods=["POST"])
@feature_required("learning", "write")
def api_learning_record():
    """Record a completed lesson.
    Body JSON: {user_id: int, book: str, lesson: str, score: int}
    """
    data    = request.get_json() or {}
    user_id = data.get("user_id")
    book    = data.get("book", "").strip()
    lesson  = data.get("lesson", "").strip()
    score   = int(data.get("score", 10))

    if not user_id or not book or not lesson:
        return jsonify({"ok": False, "error": "user_id, book, and lesson are required."})

    now = datetime.now().isoformat()[:16]
    conn = get_db()
    conn.execute("""
        INSERT INTO learning_progress (user_id, book, lesson, score, completed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, book, lesson) DO UPDATE SET score=excluded.score, completed_at=excluded.completed_at
    """, (user_id, book, lesson, score, now))

    # Update streak
    streak_row = conn.execute(
        "SELECT * FROM learning_streaks WHERE user_id = ?", (user_id,)
    ).fetchone()
    yesterday = (datetime.now().date() - __import__("datetime").timedelta(days=1)).isoformat()
    last_activity = streak_row["last_activity"][:10] if streak_row and streak_row["last_activity"] else ""
    today = datetime.now().date().isoformat()
    if not streak_row:
        conn.execute(
            "INSERT INTO learning_streaks (user_id, current_streak, longest_streak, last_activity) VALUES (?,1,1,?)",
            (user_id, now)
        )
    elif last_activity == yesterday:
        new_streak = streak_row["current_streak"] + 1
        longest    = max(new_streak, streak_row["longest_streak"])
        conn.execute(
            "UPDATE learning_streaks SET current_streak=?, longest_streak=?, last_activity=? WHERE user_id=?",
            (new_streak, longest, now, user_id)
        )
    elif last_activity != today:
        conn.execute(
            "UPDATE learning_streaks SET current_streak=1, last_activity=? WHERE user_id=?",
            (now, user_id)
        )

    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/learning/leaderboard")
@login_required
def api_learning_leaderboard():
    """Admin-only leaderboard ranked by lessons completed and avg score."""
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id, u.name, u.email,
               COUNT(lp.id)   AS lessons_done,
               COALESCE(AVG(lp.score), 0) AS avg_score,
               ls.current_streak,
               ls.longest_streak,
               MAX(lp.completed_at) AS last_active
        FROM users u
        LEFT JOIN learning_progress lp ON lp.user_id = u.id
        LEFT JOIN learning_streaks  ls ON ls.user_id  = u.id
        GROUP BY u.id
        ORDER BY lessons_done DESC, avg_score DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────────────────────────────────────
#  Rate Intelligence V2 — benchmarks, agent scores, nudges, self-recovery
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/v2/rates/benchmarks")
@login_required
def api_v2_benchmarks():
    """Return all current rate benchmarks."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM rate_benchmarks ORDER BY calculated_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/v2/rates/run-cycle", methods=["POST"])
@feature_required("rates", "write")
def api_v2_run_cycle():
    """Run full intelligence cycle for a given cycle_id."""
    data     = request.get_json() or {}
    cycle_id = data.get("cycle_id")
    if not cycle_id:
        return jsonify({"ok": False, "error": "cycle_id required."})
    try:
        result = rate_engine_v2.run_intelligence_cycle(int(cycle_id))
        return jsonify({"ok": True, **result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/v2/rates/agent-scores")
@login_required
def api_v2_agent_scores():
    """Return all agent scores with contact info."""
    conn = get_db()
    rows = conn.execute("""
        SELECT a.*, c.company_name, c.country, c.network, c.email
        FROM agent_scores a
        LEFT JOIN contacts c ON c.id = a.contact_id
        ORDER BY a.overall_score DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/v2/rates/rfq-candidates")
@login_required
def api_v2_rfq_candidates():
    """Return best agents for a lane.
    ?origin=CNSHA&destination=USLAX&carrier=Maersk
    """
    origin      = request.args.get("origin",      "").strip().upper()
    destination = request.args.get("destination", "").strip().upper()
    carrier     = request.args.get("carrier",     "").strip() or None
    if not origin or not destination:
        return jsonify({"ok": False, "error": "origin and destination required."})
    candidates = rate_engine_v2.get_rfq_candidates(origin, destination, carrier)
    return jsonify(candidates)


@app.route("/api/v2/rates/trend")
@login_required
def api_v2_trend():
    """Rate trend for a lane.
    ?origin=CNSHA&destination=USLAX&carrier=Maersk&days=30
    """
    origin      = request.args.get("origin",      "").strip().upper()
    destination = request.args.get("destination", "").strip().upper()
    carrier     = request.args.get("carrier",     "").strip() or None
    days        = int(request.args.get("days", 30))
    result = rate_engine_v2.get_trend(origin, destination, carrier, days)
    return jsonify(result)


@app.route("/api/v2/rates/nudge-response", methods=["POST"])
@login_required
def api_v2_nudge_response():
    """Record agent's response to a nudge.
    Body JSON: {contact_id, cycle_id, new_rate_20ft?, new_rate_40ft?, responded}
    """
    data         = request.get_json() or {}
    contact_id   = data.get("contact_id")
    cycle_id     = data.get("cycle_id")
    new_rate_20  = data.get("new_rate_20ft")
    new_rate_40  = data.get("new_rate_40ft")
    responded    = bool(data.get("responded", True))
    if not contact_id or not cycle_id:
        return jsonify({"ok": False, "error": "contact_id and cycle_id required."})
    try:
        result = rate_engine_v2.handle_nudge_response(
            int(contact_id), int(cycle_id), new_rate_20, new_rate_40, responded
        )
        return jsonify({"ok": True, **result})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/v2/rates/flags")
@login_required
def api_v2_rate_flags():
    """Return all active rate flags."""
    conn = get_db()
    rows = conn.execute("""
        SELECT rf.*, c.company_name, c.country, c.network
        FROM rate_flags rf
        LEFT JOIN contacts c ON c.id = rf.contact_id
        WHERE rf.auto_recovered = 0
        ORDER BY rf.flagged_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/v2/rates/best-match")
@login_required
def api_v2_best_match():
    """Best agent match for a lane."""
    origin      = request.args.get("origin",      "").strip().upper()
    destination = request.args.get("destination", "").strip().upper()
    carrier     = request.args.get("carrier",     "").strip() or None
    result = rate_engine_v2.get_best_match(origin, destination, carrier)
    return jsonify(result or {})


# ─────────────────────────────────────────────────────────────────────────────
#  Intro outreach routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/r/<token>/<selection>")
def intro_click_track(token, selection):
    """One-click lane/carrier tracking from intro email buttons. No login required."""
    import intro_mailer as _im
    result = _im.record_click(token, selection)

    is_carrier = selection.startswith("carrier-")
    label = selection.replace("carrier-", "").replace("-", " ").title()
    if selection == "all":
        label = "All Destinations"

    category = "Shipping Line" if is_carrier else "Lane"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Flash Cargo Global — Confirmed</title>
  <style>
    body {{font-family:Arial,sans-serif;background:#f4f4f4;display:flex;align-items:center;
           justify-content:center;min-height:100vh;margin:0;}}
    .card {{background:#fff;border-radius:10px;padding:40px 48px;max-width:480px;
            text-align:center;box-shadow:0 4px 20px rgba(0,0,0,.08);}}
    .check {{font-size:56px;margin-bottom:16px;}}
    h2 {{color:#1a73e8;margin:0 0 12px;}}
    p {{color:#555;font-size:15px;line-height:1.6;}}
    .tag {{display:inline-block;background:#e8f0fe;color:#1a73e8;
           border-radius:20px;padding:4px 14px;font-size:13px;font-weight:600;margin-top:8px;}}
  </style>
</head>
<body>
  <div class="card">
    <div class="check">&#10003;</div>
    <h2>Got it — thank you!</h2>
    <p>We've recorded your {category.lower()} preference:</p>
    <div class="tag">{label}</div>
    <p style="margin-top:20px;">
      You can close this tab. We'll only send you rate requests
      for the lanes and carriers you've selected.
    </p>
    <p style="font-size:13px;color:#888;margin-top:24px;">
      Flash Cargo Global &mdash; Delivering confidence worldwide
    </p>
  </div>
</body>
</html>""", 200


@app.route("/api/inbox/poll", methods=["POST"])
@login_required
def api_inbox_poll():
    """Manually trigger reply inbox poll."""
    import reply_parser as _rp
    stats = _rp.poll_inbox(lookback_hours=72)
    return jsonify(stats)


@app.route("/api/intro/stats")
@login_required
def api_intro_stats():
    """Return aggregate stats for intro outreach emails."""
    import intro_mailer as _im
    return jsonify(_im.get_intro_stats())


@app.route("/api/intro/send/<int:contact_id>", methods=["POST"])
@feature_required("outreach", "write")
def api_intro_send(contact_id):
    """Send the intro email to a single contact by id."""
    import intro_mailer as _im
    conn = get_db()
    row = conn.execute(
        "SELECT id, email, contact_name, company_name, country, city FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"ok": False, "error": f"Contact {contact_id} not found."})
    contact = dict(row)
    try:
        ok = _im.send_intro(contact)
        return jsonify({"ok": ok, "contact_id": contact_id, "email": contact["email"]})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


@app.route("/api/contacts/<int:contact_id>/lane-confirmed", methods=["POST"])
@login_required
def api_lane_confirmed(contact_id):
    """Store confirmed lanes and carriers from an agent's reply."""
    data = request.get_json(silent=True) or {}
    lanes     = data.get("lanes", [])
    carriers  = data.get("carriers", [])
    notes     = data.get("notes", "")

    lanes_json    = _json.dumps(lanes)
    carriers_json = _json.dumps(carriers)
    now           = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    # Update the most recent intro_outreach row for this contact
    row = conn.execute(
        "SELECT id FROM intro_outreach WHERE contact_id = ? ORDER BY id DESC LIMIT 1",
        (contact_id,),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE intro_outreach
            SET lanes_confirmed=?, carriers_confirmed=?,
                reply_received=1, status='replied', notes=?
            WHERE id=?
            """,
            (lanes_json, carriers_json, notes, row["id"]),
        )
    else:
        # No prior intro row — create a stub record
        conn.execute(
            """
            INSERT INTO intro_outreach
                (contact_id, email, lanes_confirmed, carriers_confirmed,
                 reply_received, status, sent_at, notes)
            SELECT ?, email, ?, ?, 1, 'replied', ?, ?
            FROM contacts WHERE id=?
            """,
            (contact_id, lanes_json, carriers_json, now, notes, contact_id),
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "contact_id": contact_id,
                    "lanes": lanes, "carriers": carriers})


# ─────────────────────────────────────────────────────────────────────────────
#  Startup
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/outreach")
@login_required
def outreach_page():
    return render_template("outreach.html", active_tab="outreach")


@app.route("/api/outreach/replies")
@login_required
def api_outreach_replies():
    conn = get_db()
    rows = conn.execute("""
        SELECT
            io.id, io.email, io.country, io.sent_at, io.status,
            io.reply_received, io.lanes_confirmed, io.carriers_confirmed,
            io.lane_clicks, io.carrier_clicks,
            c.company_name, c.contact_name, c.city
        FROM intro_outreach io
        LEFT JOIN contacts c ON io.contact_id = c.id
        ORDER BY io.sent_at DESC
        LIMIT 500
    """).fetchall()
    conn.close()
    keys = ["id","email","country","sent_at","status","reply_received",
            "lanes_confirmed","carriers_confirmed","lane_clicks","carrier_clicks",
            "company_name","contact_name","city"]
    return jsonify([{k: r[k] for k in keys} for r in rows])


# ── Agents Office ────────────────────────────────────────────────────────────

_COUNTRY_FLAGS = {
    "italy": "IT", "germany": "DE", "france": "FR", "spain": "ES",
    "netherlands": "NL", "belgium": "BE", "switzerland": "CH", "austria": "AT",
    "poland": "PL", "greece": "GR", "turkey": "TR", "portugal": "PT",
    "sweden": "SE", "denmark": "DK", "norway": "NO", "finland": "FI",
    "russia": "RU", "ukraine": "UA", "czech republic": "CZ", "romania": "RO",
    "hungary": "HU", "croatia": "HR", "ireland": "IE",
    "united kingdom": "GB", "uk": "GB",
    "china": "CN", "hong kong": "HK", "taiwan": "TW", "japan": "JP",
    "south korea": "KR", "korea": "KR", "india": "IN", "singapore": "SG",
    "malaysia": "MY", "indonesia": "ID", "thailand": "TH", "vietnam": "VN",
    "philippines": "PH", "australia": "AU", "new zealand": "NZ",
    "bangladesh": "BD", "pakistan": "PK", "sri lanka": "LK",
    "usa": "US", "united states": "US", "brazil": "BR", "mexico": "MX",
    "colombia": "CO", "argentina": "AR", "chile": "CL", "peru": "PE",
    "canada": "CA", "ecuador": "EC", "venezuela": "VE",
    "costa rica": "CR", "panama": "PA",
    "uae": "AE", "united arab emirates": "AE", "saudi arabia": "SA",
    "qatar": "QA", "kuwait": "KW", "bahrain": "BH", "oman": "OM",
    "egypt": "EG", "jordan": "JO", "lebanon": "LB", "israel": "IL",
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "ghana": "GH",
    "tanzania": "TZ", "morocco": "MA",
}


def _flag_emoji(iso2):
    """Convert 2-letter ISO code to flag emoji."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2.upper())


@app.route("/agents")
@login_required
@admin_required
def agents_page():
    return render_template("agents.html", active_tab="agents")


@app.route("/api/agents/stats")
@login_required
@admin_required
def api_agents_stats():
    conn = get_db()

    # Contact counts per country
    contact_rows = conn.execute(
        "SELECT LOWER(TRIM(country)), COUNT(*) FROM contacts WHERE country IS NOT NULL AND country != '' GROUP BY LOWER(TRIM(country))"
    ).fetchall()
    contact_counts = {r[0]: r[1] for r in contact_rows}

    # Intro outreach stats per country
    outreach_rows = conn.execute(
        "SELECT LOWER(TRIM(country)), COUNT(*), SUM(CASE WHEN reply_received IS NOT NULL AND reply_received != '' THEN 1 ELSE 0 END) FROM intro_outreach WHERE country IS NOT NULL AND country != '' GROUP BY LOWER(TRIM(country))"
    ).fetchall()
    outreach_stats = {r[0]: {"sent": r[1], "replies": r[2]} for r in outreach_rows}

    # Rate outreach stats per country
    rate_rows = conn.execute(
        "SELECT LOWER(TRIM(contact_country)), COUNT(*), SUM(CASE WHEN responded_at IS NOT NULL THEN 1 ELSE 0 END) FROM rate_outreach WHERE contact_country IS NOT NULL AND contact_country != '' GROUP BY LOWER(TRIM(contact_country))"
    ).fetchall()
    rate_stats = {r[0]: {"sent": r[1], "replies": r[2]} for r in rate_rows}

    conn.close()

    # Build per-country agent data from mailer's _COUNTRY_NAMES
    seen_iso = set()
    countries = []
    for country_key, names in _mailer._COUNTRY_NAMES.items():
        iso2 = _COUNTRY_FLAGS.get(country_key, "")
        if not iso2 or iso2 in seen_iso:
            continue
        seen_iso.add(iso2)

        agents = []
        for name in names:
            alias = _mailer._strip_accents(name).lower()
            email = f"{alias}@flashcargoglobal.com" if alias in _mailer._ACTIVE_ALIASES else "pricing@flashcargoglobal.com"
            agents.append({"name": name, "email": email, "has_alias": alias in _mailer._ACTIVE_ALIASES})

        c_contacts = contact_counts.get(country_key, 0)
        o = outreach_stats.get(country_key, {"sent": 0, "replies": 0})
        r = rate_stats.get(country_key, {"sent": 0, "replies": 0})
        total_sent = o["sent"] + r["sent"]
        total_replies = o["replies"] + r["replies"]

        display_name = country_key.title()
        if country_key in ("uae",):
            display_name = "UAE"
        elif country_key in ("usa",):
            display_name = "USA"
        elif country_key in ("uk",):
            display_name = "UK"

        countries.append({
            "country": display_name,
            "country_key": country_key,
            "iso2": iso2,
            "flag": _flag_emoji(iso2),
            "agents": agents,
            "agent_count": len(agents),
            "contacts": c_contacts,
            "emails_sent": total_sent,
            "replies": total_replies,
            "response_rate": round(total_replies / total_sent * 100, 1) if total_sent > 0 else 0,
        })

    countries.sort(key=lambda x: x["contacts"], reverse=True)

    totals = {
        "total_agents": sum(c["agent_count"] for c in countries),
        "total_countries": len(countries),
        "total_contacts": sum(c["contacts"] for c in countries),
        "total_sent": sum(c["emails_sent"] for c in countries),
        "total_replies": sum(c["replies"] for c in countries),
    }
    totals["overall_response_rate"] = round(totals["total_replies"] / totals["total_sent"] * 100, 1) if totals["total_sent"] > 0 else 0

    return jsonify({"countries": countries, "totals": totals})


@app.route("/api/translate", methods=["POST"])
@login_required
def api_translate():
    """Translate text — used by dashboard to show translated replies inline."""
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    target_lang = (data.get("target_lang") or "en").strip()
    source_lang = data.get("source_lang")  # optional, auto-detect if None

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        from translation_service import translate_text, detect_language
        if not target_lang or target_lang == "auto":
            target_lang = "en"
        if not source_lang:
            source_lang = detect_language(text)
        result = translate_text(text, target_lang, source_lang=source_lang)
        return jsonify(result)
    except ImportError:
        return jsonify({"error": "translation_service not available"}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def open_browser():
    """Auto-open browser in local dev mode only."""
    if os.environ.get("PRODUCTION"):
        return
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5000")


def init_all_dbs():
    """Initialize all database tables — called on startup.

    Microservice mapping:
      Service 12 (Admin)      → init_tenants_db()
      Service 2  (Contacts)   → init_db(), init_contact_intelligence_db()
      Service 4  (Rates)      → init_rates_db(), init_lanes_db()
      Service 1  (Auth)       → init_users_db()
      Service 3  (Email)      → init_email_outreach_db(), init_bounced_emails_db()
      Service 6  (Carriers)   → init_predictive_db(), init_reliability_db(), ensure_schedule_schema()
      Service 8  (Billing)    → init_quotes_db()
      Service 11 (AI Support) → init_helpbot_db()
      Service 2  (Contacts)   → init_inspection_log_db()
    """
    from database import init_tenants_db
    init_tenants_db()
    init_db()
    init_lanes_db()
    init_rates_db()
    init_users_db()
    init_contact_intelligence_db()
    init_email_outreach_db()
    init_inspection_log_db()
    init_predictive_db()
    init_reliability_db()
    ensure_schedule_schema()
    _quotes.init_quotes_db()
    _helpbot.init_helpbot_db()
    _migrate_lanes_carrier()
    from bounce_monitor import init_bounced_emails_db
    init_bounced_emails_db()


def start_background_workers():
    """Start all background threads — called once on startup."""
    if not has_any_api_keys_configured():
        print("[schedules] No carrier API keys configured — running in CSV-only mode")

    # ── Maersk lanes import ───────────────────────────────────────────────────
    _lanes_csv = os.path.join(DATA_DIR, "maersk_lanes.csv")
    if os.path.exists(_lanes_csv):
        import_lanes_csv(_lanes_csv)
    else:
        print("[lanes] No maersk_lanes.csv found.")

    # ── Shipping schedules import ─────────────────────────────────────────────
    if os.path.exists(SCHEDULES_PATH):
        import_schedules_csv(SCHEDULES_PATH)
        threading.Thread(target=_schedules_watcher, daemon=True).start()
        print("[schedules] 48h auto-update watcher started.")
    else:
        print(f"[schedules] {SCHEDULES_PATH} not found — skipping.")

    if CSV_SOURCES:
        print("[startup] Importing all CSVs…")
        _run_import()
        print(f"[startup] {_sync_state['row_count']} total contacts loaded.")
    else:
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        conn.close()
        with _sync_lock:
            _sync_state["row_count"] = count
            _sync_state["last_sync"] = datetime.now()
        print(f"[startup] {count} contacts loaded from database.")

    # Background watcher
    threading.Thread(target=_csv_watcher, daemon=True).start()
    print(f"[startup] Auto-sync active — checking every {CHECK_INTERVAL}s for CSV changes.")

    # Rate engine scheduler
    def _run_in_app_context(fn):
        with app.app_context():
            fn()
    rate_engine.start_scheduler(_run_in_app_context)

    # Reply inbox poller
    def _poll_replies():
        while True:
            time.sleep(1800)
            try:
                import reply_parser as _rp
                stats = _rp.poll_inbox(lookback_hours=48)
                print(f"[reply_parser] poll complete: {stats}")
            except Exception as _e:
                print(f"[reply_parser] poll error: {_e}")

    threading.Thread(target=_poll_replies, daemon=True).start()
    print("[reply_parser] Inbox poller started — runs every 30 min.")


    # Bounce monitor poller
    def _poll_bounces():
        while True:
            time.sleep(3600)  # check every hour
            try:
                from bounce_monitor import check_bounces
                result = check_bounces()
                if result["new_bounces"] > 0:
                    print(f"[bounce_monitor] Found {result['new_bounces']} new bounces")
                else:
                    print("[bounce_monitor] No new bounces")
            except Exception as _e:
                print(f"[bounce_monitor] poll error: {_e}")

    threading.Thread(target=_poll_bounces, daemon=True).start()
    print("[bounce_monitor] Bounce poller started -- runs every 60 min.")

if __name__ == "__main__":
    init_all_dbs()
    start_background_workers()

    PORT = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 55)
    print("  Freight Intelligence Dashboard")
    print(f"  Local:    http://127.0.0.1:{PORT}")
    print(f"  Network:  http://0.0.0.0:{PORT}")
    print("  Press Ctrl+C to stop")
    print("=" * 55 + "\n")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False)
