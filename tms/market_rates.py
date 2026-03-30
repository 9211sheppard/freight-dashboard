"""Market rate benchmark — compare internal rates to spot market estimates.
Real DAT/Truckstop integration requires paid API access.
This module provides structure + mock data until API credentials are configured.
"""
import os, sqlite3, json
from datetime import datetime, timedelta
import random

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_market_rate_tables():
    conn = get_db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS market_rate_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin_state TEXT NOT NULL,
            destination_state TEXT NOT NULL,
            equipment_type TEXT DEFAULT 'Dry Van',
            rate_per_mile REAL DEFAULT 0,
            all_in_rate REAL DEFAULT 0,
            source TEXT DEFAULT 'internal',  -- dat, truckstop, internal, estimate
            snapshot_date TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.commit()
    finally:
        conn.close()

init_market_rate_tables()

# Base rate estimates by region pair (rough spot market averages $/mile)
BASE_REGION_RATES = {
    ("CA", "TX"): 2.85, ("TX", "CA"): 3.20, ("CA", "IL"): 2.95,
    ("IL", "CA"): 3.10, ("FL", "NY"): 2.75, ("NY", "FL"): 2.60,
    ("TX", "FL"): 2.40, ("FL", "TX"): 2.55, ("OH", "TX"): 2.65,
    ("TX", "OH"): 2.70, ("GA", "NY"): 2.80, ("NY", "GA"): 2.65,
    ("CA", "WA"): 2.35, ("WA", "CA"): 2.45, ("IL", "TX"): 2.50,
}

def get_market_rate_estimate(origin_state: str, dest_state: str,
                              equipment_type: str = "Dry Van",
                              miles: float = 0) -> dict:
    """
    Get market rate estimate. Uses DAT API if configured, else internal estimates.
    """
    dat_key = os.environ.get('DAT_API_KEY', '')

    if dat_key:
        return _fetch_dat_rate(origin_state, dest_state, equipment_type, dat_key)

    # Internal estimate with variance
    base = BASE_REGION_RATES.get(
        (origin_state.upper(), dest_state.upper()),
        BASE_REGION_RATES.get((dest_state.upper(), origin_state.upper()), 2.60)
    )
    # Add equipment premium
    eq_premium = {"Reefer": 0.35, "Flatbed": 0.25, "Dry Van": 0.0}.get(equipment_type, 0)
    rate = base + eq_premium
    # Add variance (+-8%)
    variance = rate * (random.uniform(-0.08, 0.08))
    rate = round(rate + variance, 2)

    all_in = round(rate * max(miles, 500), 2) if miles else 0

    return {
        "rate_per_mile": rate,
        "all_in_rate": all_in,
        "source": "estimate",
        "note": "Set DAT_API_KEY or TRUCKSTOP_API_KEY env vars for live market rates",
        "origin": origin_state,
        "destination": dest_state,
        "equipment": equipment_type
    }

def _fetch_dat_rate(origin: str, dest: str, equipment: str, api_key: str) -> dict:
    """Fetch from DAT RateView API (requires DAT subscription)."""
    try:
        import requests
        # DAT API endpoint (simplified)
        resp = requests.post(
            "https://api.dat.com/ratecalc/v2/rate",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "origin": {"stateProv": origin},
                "destination": {"stateProv": dest},
                "equipmentType": equipment.upper().replace(" ","_"),
            },
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "rate_per_mile": data.get("perMileRate", 0),
                "all_in_rate": data.get("totalRate", 0),
                "source": "dat",
                "origin": origin,
                "destination": dest,
                "equipment": equipment
            }
    except Exception:
        pass
    return get_market_rate_estimate(origin, dest, equipment)  # fallback

def compare_to_market(your_rate: float, market_rate: float) -> dict:
    """Returns how your rate compares to market."""
    if not market_rate:
        return {"diff_pct": 0, "status": "unknown"}
    diff = your_rate - market_rate
    diff_pct = round(diff / market_rate * 100, 1)
    if diff_pct < -10:
        status = "below_market"
        label = f"{abs(diff_pct)}% below market — great rate"
    elif diff_pct > 10:
        status = "above_market"
        label = f"{diff_pct}% above market — negotiate down"
    else:
        status = "at_market"
        label = "At market rate"
    return {"diff": round(diff, 2), "diff_pct": diff_pct, "status": status, "label": label}
