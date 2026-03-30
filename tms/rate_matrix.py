"""Rate Matrix Builder — custom tariff rate cards by lane and weight break."""
import sqlite3, os, json

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_rate_matrix_tables():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS rate_matrices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matrix_name TEXT NOT NULL,
            service_type TEXT DEFAULT 'LTL',   -- LTL, FTL, Expedited
            equipment_type TEXT DEFAULT 'Dry Van',
            effective_date TEXT DEFAULT '',
            expiry_date TEXT DEFAULT '',
            currency TEXT DEFAULT 'USD',
            status TEXT DEFAULT 'Active',   -- Active, Inactive, Expired
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rate_matrix_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matrix_id INTEGER NOT NULL,
            origin_zone TEXT NOT NULL,    -- state code, region, zip prefix, or 'ALL'
            destination_zone TEXT NOT NULL,
            min_weight REAL DEFAULT 0,
            max_weight REAL DEFAULT 99999,
            rate_per_cwt REAL DEFAULT 0,   -- per hundredweight
            rate_flat REAL DEFAULT 0,       -- flat rate
            rate_per_mile REAL DEFAULT 0,
            min_charge REAL DEFAULT 0,
            fuel_surcharge_included INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            FOREIGN KEY (matrix_id) REFERENCES rate_matrices(id) ON DELETE CASCADE
        );
        """)
        conn.commit()
    finally:
        conn.close()

init_rate_matrix_tables()

def create_matrix(name, service_type="LTL", equipment_type="Dry Van",
                  effective_date="", expiry_date="", notes="") -> int:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO rate_matrices (matrix_name, service_type, equipment_type, effective_date, expiry_date, notes) VALUES (?,?,?,?,?,?)",
            (name, service_type, equipment_type, effective_date, expiry_date, notes)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()

def add_rate_entry(matrix_id: int, data: dict):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO rate_matrix_entries
               (matrix_id, origin_zone, destination_zone, min_weight, max_weight,
                rate_per_cwt, rate_flat, rate_per_mile, min_charge, fuel_surcharge_included, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (matrix_id, data.get("origin_zone","ALL"), data.get("destination_zone","ALL"),
             float(data.get("min_weight",0)), float(data.get("max_weight",99999)),
             float(data.get("rate_per_cwt",0)), float(data.get("rate_flat",0)),
             float(data.get("rate_per_mile",0)), float(data.get("min_charge",0)),
             1 if data.get("fuel_surcharge_included") else 0,
             data.get("notes",""))
        )
        conn.commit()
    finally:
        conn.close()

def get_all_matrices():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT m.*, COUNT(e.id) as entry_count FROM rate_matrices m LEFT JOIN rate_matrix_entries e ON e.matrix_id=m.id GROUP BY m.id ORDER BY m.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_matrix(matrix_id: int):
    conn = get_db()
    try:
        m = conn.execute("SELECT * FROM rate_matrices WHERE id=?", (matrix_id,)).fetchone()
        if not m:
            return None, []
        entries = conn.execute("SELECT * FROM rate_matrix_entries WHERE matrix_id=? ORDER BY origin_zone, destination_zone, min_weight", (matrix_id,)).fetchall()
        return dict(m), [dict(e) for e in entries]
    finally:
        conn.close()

def lookup_rate(origin_zone: str, destination_zone: str, weight_lbs: float,
                service_type: str = "LTL") -> dict:
    """Find best rate from active matrices for this lane + weight."""
    conn = get_db()
    try:
        # Try exact match, then ALL origin, then ALL destination
        for orig in [origin_zone, "ALL"]:
            for dest in [destination_zone, "ALL"]:
                row = conn.execute(
                    """SELECT e.*, m.matrix_name, m.fuel_surcharge_included
                       FROM rate_matrix_entries e
                       JOIN rate_matrices m ON m.id = e.matrix_id
                       WHERE m.status='Active' AND m.service_type=?
                       AND e.origin_zone IN (?,?) AND e.destination_zone IN (?,?)
                       AND e.min_weight <= ? AND e.max_weight >= ?
                       ORDER BY e.rate_flat DESC LIMIT 1""",
                    (service_type, orig, "ALL", dest, "ALL", weight_lbs, weight_lbs)
                ).fetchone()
                if row:
                    r = dict(row)
                    # Calculate total
                    cwt = weight_lbs / 100
                    total = max(r["min_charge"], r["rate_flat"] + r["rate_per_cwt"] * cwt)
                    r["calculated_rate"] = round(total, 2)
                    return r
        return {}
    finally:
        conn.close()

def delete_rate_entry(entry_id: int):
    conn = get_db()
    try:
        conn.execute("DELETE FROM rate_matrix_entries WHERE id=?", (entry_id,))
        conn.commit()
    finally:
        conn.close()
