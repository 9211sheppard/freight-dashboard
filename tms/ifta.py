"""IFTA (International Fuel Tax Agreement) reporting module."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_ifta_tables():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS ifta_fuel_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER DEFAULT NULL,
            vehicle_id TEXT DEFAULT '',
            purchase_date TEXT NOT NULL,
            state_province TEXT NOT NULL,   -- 2-letter code: CA, TX, ON, etc.
            gallons REAL NOT NULL,
            price_per_gallon REAL DEFAULT 0,
            total_cost REAL DEFAULT 0,
            fuel_type TEXT DEFAULT 'Diesel',  -- Diesel, Gasoline, LNG, CNG
            receipt_number TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            quarter TEXT DEFAULT '',   -- e.g. '2025-Q1'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ifta_mileage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER DEFAULT NULL,
            vehicle_id TEXT DEFAULT '',
            trip_date TEXT NOT NULL,
            shipment_ref TEXT DEFAULT '',
            state_province TEXT NOT NULL,
            miles REAL NOT NULL,
            quarter TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ifta_quarterly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quarter TEXT NOT NULL UNIQUE,  -- e.g. '2025-Q1'
            total_miles REAL DEFAULT 0,
            total_gallons REAL DEFAULT 0,
            avg_mpg REAL DEFAULT 0,
            status TEXT DEFAULT 'Draft',  -- Draft, Filed, Amended
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            filed_at TIMESTAMP DEFAULT NULL,
            notes TEXT DEFAULT ''
        );
        """)
        conn.commit()
    finally:
        conn.close()

# Run on import
init_ifta_tables()

FUEL_TYPES = ["Diesel", "Gasoline", "LNG", "CNG", "Electric"]

# IFTA tax rates per gallon by jurisdiction (simplified — real rates change quarterly)
# These are approximate 2024 rates in USD/gallon
IFTA_TAX_RATES = {
    "AL": 0.260, "AK": 0.080, "AZ": 0.180, "AR": 0.245, "CA": 0.800,
    "CO": 0.205, "CT": 0.402, "DE": 0.220, "FL": 0.349, "GA": 0.315,
    "ID": 0.320, "IL": 0.455, "IN": 0.310, "IA": 0.325, "KS": 0.240,
    "KY": 0.246, "LA": 0.200, "ME": 0.312, "MD": 0.427, "MA": 0.240,
    "MI": 0.272, "MN": 0.285, "MS": 0.183, "MO": 0.195, "MT": 0.299,
    "NE": 0.299, "NV": 0.270, "NH": 0.222, "NJ": 0.418, "NM": 0.210,
    "NY": 0.440, "NC": 0.385, "ND": 0.230, "OH": 0.385, "OK": 0.190,
    "OR": 0.380, "PA": 0.777, "RI": 0.340, "SC": 0.260, "SD": 0.280,
    "TN": 0.270, "TX": 0.200, "UT": 0.317, "VT": 0.318, "VA": 0.262,
    "WA": 0.494, "WV": 0.357, "WI": 0.329, "WY": 0.240,
    # Canadian provinces
    "AB": 0.130, "BC": 0.330, "MB": 0.142, "NB": 0.215, "NL": 0.240,
    "NS": 0.154, "ON": 0.143, "PE": 0.154, "QC": 0.202, "SK": 0.150,
}

def get_current_quarter():
    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"

def add_fuel_purchase(data: dict):
    conn = get_db()
    try:
        quarter = data.get("quarter") or get_current_quarter()
        total = float(data.get("gallons", 0)) * float(data.get("price_per_gallon", 0))
        conn.execute(
            """INSERT INTO ifta_fuel_purchases
               (driver_id, vehicle_id, purchase_date, state_province, gallons,
                price_per_gallon, total_cost, fuel_type, receipt_number, notes, quarter)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get("driver_id") or None, data.get("vehicle_id", ""),
             data.get("purchase_date", ""), data.get("state_province", "").upper(),
             float(data.get("gallons", 0)), float(data.get("price_per_gallon", 0)),
             data.get("total_cost") or total,
             data.get("fuel_type", "Diesel"), data.get("receipt_number", ""),
             data.get("notes", ""), quarter)
        )
        conn.commit()
    finally:
        conn.close()

def add_mileage_log(data: dict):
    conn = get_db()
    try:
        quarter = data.get("quarter") or get_current_quarter()
        conn.execute(
            """INSERT INTO ifta_mileage_logs
               (driver_id, vehicle_id, trip_date, shipment_ref, state_province, miles, quarter)
               VALUES (?,?,?,?,?,?,?)""",
            (data.get("driver_id") or None, data.get("vehicle_id", ""),
             data.get("trip_date", ""), data.get("shipment_ref", ""),
             data.get("state_province", "").upper(),
             float(data.get("miles", 0)), quarter)
        )
        conn.commit()
    finally:
        conn.close()

def get_quarterly_summary(quarter: str) -> dict:
    """Calculate IFTA tax owed/refund per jurisdiction for a quarter."""
    conn = get_db()
    try:
        # Total miles and gallons this quarter
        total_miles = conn.execute(
            "SELECT COALESCE(SUM(miles),0) FROM ifta_mileage_logs WHERE quarter=?", (quarter,)
        ).fetchone()[0]
        total_gallons = conn.execute(
            "SELECT COALESCE(SUM(gallons),0) FROM ifta_fuel_purchases WHERE quarter=?", (quarter,)
        ).fetchone()[0]
        avg_mpg = (total_miles / total_gallons) if total_gallons > 0 else 0

        # Miles per jurisdiction
        miles_by_state = {}
        for row in conn.execute(
            "SELECT state_province, SUM(miles) as m FROM ifta_mileage_logs WHERE quarter=? GROUP BY state_province",
            (quarter,)
        ).fetchall():
            miles_by_state[row["state_province"]] = row["m"]

        # Gallons purchased per jurisdiction
        gallons_by_state = {}
        for row in conn.execute(
            "SELECT state_province, SUM(gallons) as g FROM ifta_fuel_purchases WHERE quarter=? GROUP BY state_province",
            (quarter,)
        ).fetchall():
            gallons_by_state[row["state_province"]] = row["g"]

        # Calculate per jurisdiction
        jurisdictions = sorted(set(list(miles_by_state.keys()) + list(gallons_by_state.keys())))
        rows = []
        total_owed = 0
        for state in jurisdictions:
            miles = miles_by_state.get(state, 0)
            gallons_purchased = gallons_by_state.get(state, 0)
            gallons_consumed = (miles / avg_mpg) if avg_mpg > 0 else 0
            tax_rate = IFTA_TAX_RATES.get(state, 0.25)
            tax_owed = gallons_consumed * tax_rate
            tax_paid = gallons_purchased * tax_rate
            net = tax_owed - tax_paid  # positive = owe, negative = refund
            total_owed += net
            rows.append({
                "state": state,
                "miles": round(miles, 1),
                "gallons_consumed": round(gallons_consumed, 3),
                "gallons_purchased": round(gallons_purchased, 3),
                "tax_rate": tax_rate,
                "tax_owed": round(tax_owed, 2),
                "tax_paid": round(tax_paid, 2),
                "net": round(net, 2),
            })

        # Sort by net descending (highest liability first)
        rows.sort(key=lambda x: x["net"], reverse=True)

        return {
            "quarter": quarter,
            "total_miles": round(total_miles, 1),
            "total_gallons": round(total_gallons, 3),
            "avg_mpg": round(avg_mpg, 2),
            "jurisdictions": rows,
            "total_net": round(total_owed, 2),
        }
    finally:
        conn.close()

def get_all_quarters():
    conn = get_db()
    try:
        fuel_q = [r[0] for r in conn.execute("SELECT DISTINCT quarter FROM ifta_fuel_purchases WHERE quarter != '' ORDER BY quarter DESC").fetchall()]
        mile_q = [r[0] for r in conn.execute("SELECT DISTINCT quarter FROM ifta_mileage_logs WHERE quarter != '' ORDER BY quarter DESC").fetchall()]
        quarters = sorted(set(fuel_q + mile_q), reverse=True)
        if not quarters:
            quarters = [get_current_quarter()]
        return quarters
    finally:
        conn.close()

def get_fuel_purchases(quarter=None):
    conn = get_db()
    try:
        if quarter:
            rows = conn.execute("SELECT * FROM ifta_fuel_purchases WHERE quarter=? ORDER BY purchase_date DESC", (quarter,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM ifta_fuel_purchases ORDER BY purchase_date DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_mileage_logs(quarter=None):
    conn = get_db()
    try:
        if quarter:
            rows = conn.execute("SELECT * FROM ifta_mileage_logs WHERE quarter=? ORDER BY trip_date DESC", (quarter,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM ifta_mileage_logs ORDER BY trip_date DESC LIMIT 100").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
