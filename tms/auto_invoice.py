"""Autonomous invoicing — POD received → invoice generated → queued for sending."""
import sqlite3, os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'contacts.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_auto_invoice_tables():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS auto_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL UNIQUE,
            shipment_ref TEXT NOT NULL,
            customer_name TEXT DEFAULT '',
            customer_email TEXT DEFAULT '',
            billing_address TEXT DEFAULT '',
            line_items TEXT DEFAULT '[]',   -- JSON: [{desc, qty, rate, amount}]
            subtotal REAL DEFAULT 0,
            fuel_surcharge REAL DEFAULT 0,
            fuel_surcharge_pct REAL DEFAULT 0,
            taxes REAL DEFAULT 0,
            total REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            due_date TEXT DEFAULT '',
            payment_terms TEXT DEFAULT 'Net 30',
            status TEXT DEFAULT 'Draft',   -- Draft, Sent, Viewed, Paid, Overdue
            pdf_path TEXT DEFAULT '',
            sent_at TIMESTAMP DEFAULT NULL,
            viewed_at TIMESTAMP DEFAULT NULL,
            paid_at TIMESTAMP DEFAULT NULL,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
    finally:
        conn.close()

init_auto_invoice_tables()

import json, random, string

def generate_invoice_number():
    now = datetime.now()
    return f"INV-{now.year}{now.month:02d}-{''.join(random.choices(string.digits, k=4))}"

def create_auto_invoice(shipment_ref: str, customer_name: str = "", customer_email: str = "",
                         base_rate: float = 0, fuel_surcharge_pct: float = 0,
                         extra_line_items: list = None, payment_terms: str = "Net 30") -> str:
    """Create invoice for a shipment. Returns invoice_number."""
    conn = get_db()
    try:
        # Check if invoice already exists
        existing = conn.execute("SELECT invoice_number FROM auto_invoices WHERE shipment_ref=?", (shipment_ref,)).fetchone()
        if existing:
            return existing["invoice_number"]

        inv_num = generate_invoice_number()

        # Build line items
        line_items = [{"desc": f"Freight charges — {shipment_ref}", "qty": 1, "rate": base_rate, "amount": base_rate}]
        if extra_line_items:
            line_items.extend(extra_line_items)

        subtotal = sum(i["amount"] for i in line_items)
        fsc_amount = round(subtotal * fuel_surcharge_pct / 100, 2)
        total = subtotal + fsc_amount
        due = (datetime.now() + timedelta(days=30 if payment_terms=="Net 30" else 15)).strftime("%Y-%m-%d")

        conn.execute(
            """INSERT INTO auto_invoices
               (invoice_number, shipment_ref, customer_name, customer_email,
                line_items, subtotal, fuel_surcharge, fuel_surcharge_pct, total,
                due_date, payment_terms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (inv_num, shipment_ref, customer_name, customer_email,
             json.dumps(line_items), subtotal, fsc_amount, fuel_surcharge_pct,
             total, due, payment_terms)
        )
        conn.commit()
        return inv_num
    finally:
        conn.close()

def get_all_invoices():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM auto_invoices ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_invoice(invoice_number):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM auto_invoices WHERE invoice_number=?", (invoice_number,)).fetchone()
        if not row:
            return None
        inv = dict(row)
        inv["line_items"] = json.loads(inv.get("line_items","[]"))
        return inv
    finally:
        conn.close()

def mark_invoice_sent(invoice_number):
    conn = get_db()
    try:
        conn.execute("UPDATE auto_invoices SET status='Sent', sent_at=CURRENT_TIMESTAMP WHERE invoice_number=?", (invoice_number,))
        conn.commit()
    finally:
        conn.close()

def mark_invoice_paid(invoice_number):
    conn = get_db()
    try:
        conn.execute("UPDATE auto_invoices SET status='Paid', paid_at=CURRENT_TIMESTAMP WHERE invoice_number=?", (invoice_number,))
        conn.commit()
    finally:
        conn.close()

def get_invoice_stats():
    conn = get_db()
    try:
        total_outstanding = conn.execute("SELECT COALESCE(SUM(total),0) FROM auto_invoices WHERE status IN ('Draft','Sent')").fetchone()[0]
        total_paid = conn.execute("SELECT COALESCE(SUM(total),0) FROM auto_invoices WHERE status='Paid'").fetchone()[0]
        overdue_count = conn.execute("SELECT COUNT(*) FROM auto_invoices WHERE status='Sent' AND due_date < date('now')").fetchone()[0]
        total_count = conn.execute("SELECT COUNT(*) FROM auto_invoices").fetchone()[0]
        # Mark overdue
        conn.execute("UPDATE auto_invoices SET status='Overdue' WHERE status='Sent' AND due_date < date('now')")
        conn.commit()
        return {
            "total_outstanding": round(total_outstanding, 2),
            "total_paid": round(total_paid, 2),
            "overdue_count": overdue_count,
            "total_count": total_count,
        }
    finally:
        conn.close()
