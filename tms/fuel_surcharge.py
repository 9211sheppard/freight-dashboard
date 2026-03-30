"""Fuel Surcharge Calculator — DOE index-based FSC."""
import sqlite3, os
from datetime import datetime

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_fsc_tables():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS fsc_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            effective_date TEXT NOT NULL,
            doe_price REAL NOT NULL,      -- DOE national diesel average $/gallon
            fsc_pct REAL NOT NULL,        -- Fuel surcharge percentage
            fsc_per_mile REAL DEFAULT 0,  -- Alternative: per-mile rate
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fsc_brackets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            price_min REAL NOT NULL,
            price_max REAL NOT NULL,
            fsc_pct REAL NOT NULL
        );
        """)

        # Seed FSC brackets if empty (standard DOE-based bracket table)
        if conn.execute("SELECT COUNT(*) FROM fsc_brackets").fetchone()[0] == 0:
            brackets = [
                (0.00, 1.25, 0.0),
                (1.25, 1.50, 3.0),
                (1.50, 1.75, 4.5),
                (1.75, 2.00, 6.0),
                (2.00, 2.25, 7.5),
                (2.25, 2.50, 9.0),
                (2.50, 2.75, 10.5),
                (2.75, 3.00, 12.0),
                (3.00, 3.25, 13.5),
                (3.25, 3.50, 15.0),
                (3.50, 3.75, 16.5),
                (3.75, 4.00, 18.0),
                (4.00, 4.25, 19.5),
                (4.25, 4.50, 21.0),
                (4.50, 4.75, 22.5),
                (4.75, 5.00, 24.0),
                (5.00, 5.25, 25.5),
                (5.25, 5.50, 27.0),
                (5.50, 9.99, 28.5),
            ]
            conn.executemany("INSERT INTO fsc_brackets (price_min, price_max, fsc_pct) VALUES (?,?,?)", brackets)
        conn.commit()
    finally:
        conn.close()

init_fsc_tables()

def get_current_fsc_pct(doe_price: float = None) -> float:
    """Get FSC% for a given DOE price (or latest logged price)."""
    conn = get_db()
    try:
        if doe_price is None:
            latest = conn.execute("SELECT doe_price FROM fsc_rates ORDER BY effective_date DESC LIMIT 1").fetchone()
            doe_price = latest["doe_price"] if latest else 3.80  # default
        row = conn.execute(
            "SELECT fsc_pct FROM fsc_brackets WHERE price_min <= ? AND price_max > ? LIMIT 1",
            (doe_price, doe_price)
        ).fetchone()
        return row["fsc_pct"] if row else 28.5
    finally:
        conn.close()

def log_doe_price(doe_price: float, effective_date: str = None, notes: str = ""):
    """Log a new DOE diesel price and compute the FSC."""
    conn = get_db()
    try:
        fsc_pct = get_current_fsc_pct(doe_price)
        fsc_per_mile = round(doe_price * fsc_pct / 100 / 6.5, 4)  # ~6.5 mpg average truck
        date = effective_date or datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO fsc_rates (effective_date, doe_price, fsc_pct, fsc_per_mile, notes) VALUES (?,?,?,?,?)",
            (date, doe_price, fsc_pct, fsc_per_mile, notes)
        )
        conn.commit()
        return fsc_pct
    finally:
        conn.close()

def get_fsc_history():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM fsc_rates ORDER BY effective_date DESC LIMIT 52").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_fsc_brackets():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM fsc_brackets ORDER BY price_min").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def calculate_fsc_for_shipment(base_rate: float, doe_price: float = None) -> dict:
    """Calculate FSC amount for a shipment."""
    pct = get_current_fsc_pct(doe_price)
    amount = round(base_rate * pct / 100, 2)
    return {"fsc_pct": pct, "fsc_amount": amount, "total": round(base_rate + amount, 2)}

def get_latest_doe_price():
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM fsc_rates ORDER BY effective_date DESC LIMIT 1").fetchone()
        return dict(row) if row else {"doe_price": 3.80, "fsc_pct": 18.0, "effective_date": "Not set"}
    finally:
        conn.close()
