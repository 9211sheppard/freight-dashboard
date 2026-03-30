"""ELD (Electronic Logging Device) integration framework.
Supports: Samsara, KeepTruckin (Motive), Omnitracs, PeopleNet
Real API calls require credentials in env vars.
"""
import os, sqlite3
from datetime import datetime

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_eld_tables():
    conn = get_db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS eld_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,   -- samsara, motive, omnitracs
            api_key TEXT DEFAULT '',
            org_id TEXT DEFAULT '',
            status TEXT DEFAULT 'Disconnected',
            last_sync TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS eld_hos_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER DEFAULT NULL,
            external_driver_id TEXT DEFAULT '',
            provider TEXT DEFAULT '',
            log_date TEXT DEFAULT '',
            duty_status TEXT DEFAULT '',   -- off_duty, sleeper, driving, on_duty
            hours_driving REAL DEFAULT 0,
            hours_on_duty REAL DEFAULT 0,
            hours_remaining REAL DEFAULT 0,
            violations INTEGER DEFAULT 0,
            vehicle_id TEXT DEFAULT '',
            synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.commit()
    finally:
        conn.close()

init_eld_tables()

ELD_PROVIDERS = [
    {"key": "samsara", "name": "Samsara", "url": "https://api.samsara.com", "env_key": "SAMSARA_API_KEY"},
    {"key": "motive", "name": "Motive (KeepTruckin)", "url": "https://api.keeptruckin.com", "env_key": "MOTIVE_API_KEY"},
    {"key": "omnitracs", "name": "Omnitracs", "url": "https://api.omnitracs.com", "env_key": "OMNITRACS_API_KEY"},
    {"key": "peoplenet", "name": "PeopleNet", "url": "https://api.peoplenet.com", "env_key": "PEOPLENET_API_KEY"},
]

def get_eld_connections():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM eld_connections").fetchall()
        connected = {r["provider"]: dict(r) for r in rows}
        result = []
        for p in ELD_PROVIDERS:
            entry = connected.get(p["key"], {"provider": p["key"], "status": "Disconnected"})
            entry["name"] = p["name"]
            entry["env_key"] = p["env_key"]
            entry["api_configured"] = bool(os.environ.get(p["env_key"], ''))
            result.append(entry)
        return result
    finally:
        conn.close()

def fetch_samsara_hos(api_key: str) -> list:
    """Fetch HOS data from Samsara API."""
    try:
        import requests
        resp = requests.get(
            "https://api.samsara.com/fleet/hos/clocks",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception:
        pass
    return []

def fetch_motive_hos(api_key: str) -> list:
    """Fetch HOS data from Motive API."""
    try:
        import requests
        resp = requests.get(
            "https://api.keeptruckin.com/v1/hos_clocks",
            headers={"X-Api-Key": api_key},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("hos_clocks", [])
    except Exception:
        pass
    return []

def sync_eld_provider(provider: str) -> dict:
    """Sync HOS data from a provider. Returns summary."""
    api_key = os.environ.get(
        next((p["env_key"] for p in ELD_PROVIDERS if p["key"] == provider), ""),
        ""
    )
    if not api_key:
        return {"ok": False, "error": "API key not configured"}

    if provider == "samsara":
        data = fetch_samsara_hos(api_key)
    elif provider == "motive":
        data = fetch_motive_hos(api_key)
    else:
        return {"ok": False, "error": "Provider not yet implemented"}

    conn = get_db()
    try:
        for d in data:
            conn.execute(
                """INSERT INTO eld_hos_logs
                   (external_driver_id, provider, log_date, duty_status,
                    hours_driving, hours_on_duty, hours_remaining)
                   VALUES (?,?,?,?,?,?,?)""",
                (str(d.get("id", d.get("driver_id",""))), provider,
                 datetime.now().strftime("%Y-%m-%d"),
                 d.get("duty_status", d.get("status","")),
                 float(d.get("driving_ms", d.get("time_since_last_reset_ms",0)) / 3600000),
                 float(d.get("on_duty_ms", 0) / 3600000),
                 max(0, 11.0 - float(d.get("driving_ms", 0) / 3600000)))
            )
        conn.execute(
            "UPDATE eld_connections SET status='Connected', last_sync=CURRENT_TIMESTAMP WHERE provider=?",
            (provider,)
        )
        conn.commit()
        return {"ok": True, "synced": len(data)}
    finally:
        conn.close()

def get_hos_for_driver(driver_id: int) -> dict:
    """Get latest HOS log for a driver."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM eld_hos_logs WHERE driver_id=? ORDER BY synced_at DESC LIMIT 1",
            (driver_id,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()
