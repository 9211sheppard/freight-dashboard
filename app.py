"""
app.py  —  WFA Contacts Dashboard
Run with:  python app.py
Then open: http://127.0.0.1:5000
"""

import csv
import io
import os
import re
import subprocess
import sys
import webbrowser
import threading
import time
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, Response,
)

import urllib.request
import urllib.parse
import json as _json

from config import SECRET_KEY, PASSWORD, DB_PATH, CSV_SOURCES, DATA_DIR
from config import FMCSA_KEY, EMAIL_USER
from database import init_db, get_db, init_lanes_db, init_carriers_db, init_rates_db, init_users_db
from import_csv import import_all_csvs, import_csv
import rate_engine
import rate_engine_v2
import auth as _auth

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

STARTUP_TIME = str(int(time.time()))          # changes on every restart → cache-busting

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


# ─────────────────────────────────────────────────────────────────────────────
#  Auth routes  (per-user email + password)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # ── Legacy single-password fallback (for admin during migration) ──
        if not email and password == PASSWORD:
            session["logged_in"] = True
            session["user_role"]  = "admin"
            session["user_name"]  = "Admin"
            session.permanent     = False
            return redirect(url_for("dashboard"))

        result = _auth.login_user(email, password)
        if result["ok"]:
            _auth.set_session(session, result["user"])
            return redirect(url_for("dashboard"))
        error = result["error"]

    return render_template("login.html", error=error)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    error   = None
    success = None
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")

        if password != confirm:
            error = "Passwords do not match."
        else:
            result = _auth.register_user(name, email, password)
            if result["ok"]:
                # Auto-login after registration
                login_result = _auth.login_user(email, password)
                if login_result["ok"]:
                    _auth.set_session(session, login_result["user"])
                    return redirect(url_for("dashboard"))
                success = "Account created! Please log in."
            else:
                error = result["error"]

    return render_template("register.html", error=error, success=success)


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


# ─────────────────────────────────────────────────────────────────────────────
#  Main dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", sv=STARTUP_TIME, current_user=_auth.current_user(session))


# ─────────────────────────────────────────────────────────────────────────────
#  API — search / filter
# ─────────────────────────────────────────────────────────────────────────────

def _build_query(args, select="network, company_name, contact_name, email, phone_number, country, city, verified_status, verified_score, website_url, linkedin_url"):
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
        sql += " AND LOWER(country) LIKE LOWER(?)"
        params.append(f"%{country}%")
    if company:
        sql += " AND LOWER(company_name) LIKE LOWER(?)"
        params.append(f"%{company}%")
    if name:
        sql += " AND LOWER(contact_name) LIKE LOWER(?)"
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

    sql += f" ORDER BY LOWER({sort_by}) {sort_dir.upper()}"
    return sql, params


@app.route("/api/search")
@login_required
def api_search():
    sql, params = _build_query(request.args)
    conn  = get_db()
    rows  = conn.execute(sql, params).fetchall()
    conn.close()
    results = [dict(r) for r in rows]
    return jsonify({"count": len(results), "results": results})


# ─────────────────────────────────────────────────────────────────────────────
#  API — stats
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/api/version")
def api_version():
    return jsonify({"v": STARTUP_TIME})


@app.route("/api/stats")
@login_required
def api_stats():
    conn  = get_db()
    total = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    conn.close()
    return jsonify({"total": total})


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
@login_required
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
@login_required
def api_upload_csv():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file received."})

    f = request.files["file"]
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"ok": False, "error": "File must be a .csv"})

    # Detect network from filename  (wfa_... → WFA,  wwpc_... → WWPC, else custom)
    name_lower = f.filename.lower()
    if "wfa" in name_lower:
        network = "WFA"
    elif "wwpc" in name_lower:
        network = "WWPC"
    elif "fiata" in name_lower:
        network = "FIATA"
    else:
        network = os.path.splitext(f.filename)[0].upper()

    # Save into the app's data folder
    os.makedirs(DATA_DIR, exist_ok=True)
    save_path = os.path.join(DATA_DIR, f"upload_{network.lower()}.csv")
    f.save(save_path)

    try:
        result = import_csv(save_path, network_override=network)
        conn   = get_db()
        count  = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        conn.close()
        with _sync_lock:
            _sync_state["last_sync"]  = datetime.now()
            _sync_state["row_count"]  = count
        return jsonify({
            "ok":        True,
            "network":   network,
            "imported":  result["imported"],
            "row_count": count,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(lanes)").fetchall()}
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


SCHEDULES_PATH = r"C:\Users\Owner\Desktop\shipping_schedules.csv"
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
    status      = request.args.get("status",      "all").strip().lower()
    vessel_q    = request.args.get("vessel",      "").strip()
    carrier_q   = request.args.get("carrier",     "").strip()

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

    # Sort: active lanes with etd first, then inactive
    sql += " ORDER BY CASE WHEN lane_status='active' AND etd != '' THEN 0 ELSE 1 END, etd ASC"

    conn  = get_db()
    rows  = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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
#  Carriers — FMCSA SAFER API + local DB
# ─────────────────────────────────────────────────────────────────────────────

FMCSA_BASE = "https://mobile.fmcsa.dot.gov/qc/services"

def _fmcsa_get(path):
    """Hit FMCSA SAFER REST API. Returns parsed JSON or None on failure."""
    if not FMCSA_KEY:
        return None
    sep = "&" if "?" in path else "?"
    url = f"{FMCSA_BASE}{path}{sep}webKey={FMCSA_KEY}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return _json.loads(r.read().decode())
    except Exception as e:
        print(f"[fmcsa] Error: {e}")
        return None


def _score_carrier(c):
    """Score 0–100 based on safety, fleet size, years, insurance."""
    score = 0
    # Safety rating (40 pts)
    rating = (c.get("safety_rating") or "").lower()
    if rating == "satisfactory":   score += 40
    elif rating == "":             score += 25   # not rated ≠ bad
    elif rating == "conditional":  score += 10
    # Fleet size sweet spot 5–50 (20 pts)
    trucks = c.get("fleet_trucks", 0) or 0
    if 5 <= trucks <= 50:          score += 20
    elif 51 <= trucks <= 150:      score += 10
    elif trucks > 0:               score += 5
    # Years active (20 pts)
    years = c.get("years_active", 0) or 0
    score += min(years * 2, 20)
    # Insurance on file (10 pts)
    if c.get("insured"):           score += 10
    # Active status (10 pts)
    if (c.get("status") or "").upper() == "A": score += 10
    return round(score, 1)


def _fmcsa_to_row(carrier_data):
    """Normalize FMCSA API carrier object into our DB columns."""
    c = carrier_data.get("carrier", carrier_data)
    # Derive years active from mileageYear or operatingStatus
    from datetime import datetime as _dt
    entity_type = c.get("carrierOperation", {})
    # Try to get founding year from census data
    years = 0
    try:
        out_of_service = c.get("oosDate", "")
        # Not reliable — leave as 0 if not present
    except Exception:
        pass

    row = {
        "dot_number":    str(c.get("dotNumber", "") or ""),
        "mc_number":     str(c.get("mcNumber",  "") or ""),
        "legal_name":    c.get("legalName",  "") or "",
        "dba_name":      c.get("dbaName",    "") or "",
        "city":          c.get("phyCity",    "") or "",
        "state":         c.get("phyState",   "") or "",
        "phone":         c.get("telephone",  "") or "",
        "fleet_trucks":  int(c.get("totalPowerUnits", 0) or 0),
        "fleet_drivers": int(c.get("totalDrivers",    0) or 0),
        "safety_rating": c.get("safetyRating", "") or "",
        "status":        c.get("statusCode",   "") or "",
        "years_active":  years,
        "insured":       1 if c.get("bipdInsuranceOnFile") == "Y" else 0,
        "fetched_at":    datetime.now().strftime("%Y-%m-%d"),
    }
    row["score"] = _score_carrier(row)
    return row


@app.route("/carriers")
@login_required
def carriers():
    return render_template("carriers.html", sv=STARTUP_TIME)


@app.route("/api/carriers")
@login_required
def api_carriers():
    """List all saved carriers with optional filters."""
    state  = request.args.get("state",  "").strip().upper()
    min_sc = request.args.get("min_score", "").strip()
    q      = request.args.get("q", "").strip()

    sql    = "SELECT * FROM carriers WHERE 1=1"
    params = []
    if state:
        sql += " AND UPPER(state) = ?"
        params.append(state)
    if min_sc:
        sql += " AND score >= ?"
        params.append(float(min_sc))
    if q:
        sql += " AND (LOWER(legal_name) LIKE LOWER(?) OR LOWER(dba_name) LIKE LOWER(?) OR dot_number LIKE ? OR mc_number LIKE ?)"
        params += [f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"]

    sql += " ORDER BY score DESC"
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/carriers/lookup", methods=["POST"])
@login_required
def api_carriers_lookup():
    """Look up a carrier by DOT or MC number via FMCSA and save to DB."""
    data    = request.get_json() or {}
    dot     = str(data.get("dot", "")).strip()
    mc      = str(data.get("mc",  "")).strip()

    if not FMCSA_KEY:
        return jsonify({"ok": False, "error": "No FMCSA API key configured. Add it to config.py."})
    if not dot and not mc:
        return jsonify({"ok": False, "error": "Provide a DOT or MC number."})

    result = None
    if dot:
        result = _fmcsa_get(f"/carriers/{dot}")
    elif mc:
        result = _fmcsa_get(f"/carriers/docket-number/{mc}")

    if not result:
        return jsonify({"ok": False, "error": "Carrier not found or FMCSA unreachable."})

    row = _fmcsa_to_row(result)

    conn = get_db()
    # Upsert by dot_number
    existing = conn.execute(
        "SELECT id FROM carriers WHERE dot_number = ?", (row["dot_number"],)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE carriers SET legal_name=?, dba_name=?, city=?, state=?, phone=?,
              fleet_trucks=?, fleet_drivers=?, safety_rating=?, status=?,
              insured=?, score=?, fetched_at=?
            WHERE dot_number=?""",
            (row["legal_name"], row["dba_name"], row["city"], row["state"],
             row["phone"], row["fleet_trucks"], row["fleet_drivers"],
             row["safety_rating"], row["status"], row["insured"],
             row["score"], row["fetched_at"], row["dot_number"])
        )
    else:
        conn.execute("""
            INSERT INTO carriers
              (dot_number, mc_number, legal_name, dba_name, city, state, phone,
               fleet_trucks, fleet_drivers, safety_rating, status,
               insured, score, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["dot_number"], row["mc_number"], row["legal_name"], row["dba_name"],
             row["city"], row["state"], row["phone"], row["fleet_trucks"],
             row["fleet_drivers"], row["safety_rating"], row["status"],
             row["insured"], row["score"], row["fetched_at"])
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "carrier": row})


@app.route("/api/carriers/<int:carrier_id>", methods=["DELETE"])
@login_required
def api_carrier_delete(carrier_id):
    conn = get_db()
    conn.execute("DELETE FROM carriers WHERE id = ?", (carrier_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/carriers/<int:carrier_id>", methods=["PATCH"])
@login_required
def api_carrier_patch(carrier_id):
    """Update lanes or notes for a saved carrier."""
    data = request.get_json() or {}
    fields, params = [], []
    for col in ("lanes", "notes"):
        if col in data:
            fields.append(f"{col} = ?")
            params.append(data[col])
    if not fields:
        return jsonify({"ok": False, "error": "Nothing to update."})
    params.append(carrier_id)
    conn = get_db()
    conn.execute(f"UPDATE carriers SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/carriers/stats")
@login_required
def api_carriers_stats():
    conn = get_db()
    total  = conn.execute("SELECT COUNT(*) FROM carriers").fetchone()[0]
    rated  = conn.execute("SELECT COUNT(*) FROM carriers WHERE safety_rating = 'Satisfactory'").fetchone()[0]
    states = conn.execute("SELECT COUNT(DISTINCT state) FROM carriers WHERE state != ''").fetchone()[0]
    avg_sc = conn.execute("SELECT AVG(score) FROM carriers").fetchone()[0] or 0
    conn.close()
    return jsonify({"total": total, "satisfactory": rated, "states": states, "avg_score": round(avg_sc, 1)})


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
    return render_template("rates.html", sv=STARTUP_TIME, email_configured=bool(EMAIL_USER))


@app.route("/api/rates")
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
@login_required
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
#  Startup
# ─────────────────────────────────────────────────────────────────────────────

def open_browser():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    init_db()
    init_lanes_db()
    init_carriers_db()
    init_rates_db()
    init_users_db()
    _migrate_lanes_carrier()

    # ── Maersk lanes import ───────────────────────────────────────────────────
    _lanes_csv = r"C:\Users\Owner\Desktop\maersk_lanes.csv"
    if not os.path.exists(_lanes_csv):
        _lanes_csv = os.path.join(DATA_DIR, "maersk_lanes.csv")
    if os.path.exists(_lanes_csv):
        import_lanes_csv(_lanes_csv)
        import shutil
        _lanes_dest = os.path.join(DATA_DIR, "maersk_lanes.csv")
        if os.path.abspath(_lanes_csv) != os.path.abspath(_lanes_dest):
            shutil.copy2(_lanes_csv, _lanes_dest)
    else:
        print("[lanes] No maersk_lanes.csv found.")

    # ── Shipping schedules import (India→North America, multi-carrier) ────────
    if os.path.exists(SCHEDULES_PATH):
        import_schedules_csv(SCHEDULES_PATH)
        threading.Thread(target=_schedules_watcher, daemon=True).start()
        print("[schedules] 48h auto-update watcher started.")
    else:
        print(f"[schedules] {SCHEDULES_PATH} not found — skipping.")

    if CSV_SOURCES:
        # Source machine — import CSVs as usual
        print("[startup] Importing all CSVs…")
        _run_import()
        print(f"[startup] {_sync_state['row_count']} total contacts loaded.")
    else:
        # Team member machine (no CSV files) — use existing database as-is
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        conn.close()
        with _sync_lock:
            _sync_state["row_count"] = count
            _sync_state["last_sync"] = datetime.now()
        print(f"[startup] {count} contacts loaded from database.")

    # Start background watcher thread
    threading.Thread(target=_csv_watcher, daemon=True).start()
    print(f"[startup] Auto-sync active — checking every {CHECK_INTERVAL}s for CSV changes.")

    # Start rate engine scheduler (reminders + monthly sends)
    def _run_in_app_context(fn):
        with app.app_context():
            fn()
    rate_engine.start_scheduler(_run_in_app_context)

    print("\n" + "=" * 55)
    print("  WFA Contacts Dashboard")
    print("  Local:    http://127.0.0.1:5000")
    print("  Network:  http://0.0.0.0:5000")
    print("  Press Ctrl+C to stop")
    print("=" * 55 + "\n")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
