"""
Accessorial & Detention Billing Engine
Handles detention, TONU, layover, lumper, liftgate, fuel surcharge per load,
inside delivery, redelivery, and any custom charges.
Client plugs in APEX, Greenscreens, or any rate feed API key — we call it.
"""
import json
from datetime import datetime
from .tms_db import get_db

# Standard accessorial types
ACCESSORIAL_TYPES = {
    "detention":        {"label": "Detention",                "unit": "per_hour",  "default_rate": 75.00},
    "tonu":             {"label": "TONU (Truck Order Not Used)","unit": "flat",    "default_rate": 150.00},
    "layover":          {"label": "Layover",                  "unit": "per_day",   "default_rate": 250.00},
    "lumper":           {"label": "Lumper Service",           "unit": "flat",      "default_rate": 0.00},
    "liftgate_pickup":  {"label": "Liftgate — Pickup",        "unit": "flat",      "default_rate": 75.00},
    "liftgate_delivery":{"label": "Liftgate — Delivery",      "unit": "flat",      "default_rate": 75.00},
    "inside_delivery":  {"label": "Inside Delivery",          "unit": "flat",      "default_rate": 100.00},
    "inside_pickup":    {"label": "Inside Pickup",            "unit": "flat",      "default_rate": 100.00},
    "redelivery":       {"label": "Redelivery",               "unit": "flat",      "default_rate": 125.00},
    "residential":      {"label": "Residential Delivery",     "unit": "flat",      "default_rate": 85.00},
    "appointment":      {"label": "Appointment Fee",          "unit": "flat",      "default_rate": 50.00},
    "hazmat":           {"label": "Hazmat Handling",          "unit": "flat",      "default_rate": 175.00},
    "overweight":       {"label": "Overweight Permit",        "unit": "flat",      "default_rate": 0.00},
    "oversize":         {"label": "Oversize Permit",          "unit": "flat",      "default_rate": 0.00},
    "sort_and_seg":     {"label": "Sort & Segregate",         "unit": "flat",      "default_rate": 0.00},
    "storage":          {"label": "Storage (per day)",        "unit": "per_day",   "default_rate": 50.00},
    "fuel_surcharge":   {"label": "Fuel Surcharge",           "unit": "percentage","default_rate": 0.00},
    "custom":           {"label": "Custom Charge",            "unit": "flat",      "default_rate": 0.00},
}

# External rate intelligence providers (client plugs in API key)
RATE_FEED_PROVIDERS = {
    "greenscreens": {
        "name": "Greenscreens.ai",
        "region": "North America",
        "endpoint": "https://api.greenscreens.ai/v1/rates",
        "auth": "api_key",
        "settings_key": "greenscreens_api_key",
    },
    "apex_capital": {
        "name": "Apex Capital Rate Intelligence",
        "region": "North America",
        "endpoint": "https://api.apexcapitalcorp.com/v1/rates",
        "auth": "api_key",
        "settings_key": "apex_api_key",
    },
    "dat_rateview": {
        "name": "DAT RateView",
        "region": "North America",
        "endpoint": "https://api.dat.com/freight/v1/rate",
        "auth": "basic",
        "settings_key": "dat_username",
    },
    "freightos": {
        "name": "Freightos (Global Ocean/Air)",
        "region": "Global",
        "endpoint": "https://api.freightos.com/api/v1/rates",
        "auth": "api_key",
        "settings_key": "freightos_api_key",
    },
    "xeneta": {
        "name": "Xeneta (Ocean Benchmarking)",
        "region": "Global — Ocean",
        "endpoint": "https://api.xeneta.com/v1/rates",
        "auth": "api_key",
        "settings_key": "xeneta_api_key",
    },
    "freightquote": {
        "name": "Freightquote by C.H. Robinson",
        "region": "North America",
        "endpoint": "https://api.freightquote.com/v2/rates",
        "auth": "api_key",
        "settings_key": "freightquote_api_key",
    },
    "seko": {
        "name": "SEKO Logistics Rate API (APAC/Global)",
        "region": "Asia-Pacific / Global",
        "endpoint": "https://api.sekologistics.com/rates",
        "auth": "api_key",
        "settings_key": "seko_api_key",
    },
    "wtransnet": {
        "name": "Wtransnet Rate Index (Europe)",
        "region": "Europe",
        "endpoint": "https://api.wtransnet.com/rates",
        "auth": "api_key",
        "settings_key": "wtransnet_api_key",
    },
}


def _init_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accessorial_charges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            charge_type TEXT NOT NULL,
            description TEXT,
            quantity REAL DEFAULT 1,
            rate REAL NOT NULL,
            amount REAL NOT NULL,
            billable_to TEXT DEFAULT 'customer',
            status TEXT DEFAULT 'pending',
            approved_by TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS detention_timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            location_type TEXT NOT NULL DEFAULT 'delivery',
            arrived_at TIMESTAMP NOT NULL,
            departed_at TIMESTAMP,
            free_hours REAL DEFAULT 2.0,
            rate_per_hour REAL DEFAULT 75.00,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


# ── Accessorial charges ───────────────────────────────────────────────────────

def add_charge(shipment_ref, charge_type, rate, quantity=1,
               description=None, billable_to='customer', notes=None):
    conn = get_db()
    _init_tables(conn)
    amount = rate * quantity
    if not description:
        description = ACCESSORIAL_TYPES.get(charge_type, {}).get('label', charge_type)
    conn.execute("""
        INSERT INTO accessorial_charges
        (shipment_ref, charge_type, description, quantity, rate, amount, billable_to, notes)
        VALUES (?,?,?,?,?,?,?,?)
    """, (shipment_ref, charge_type, description, quantity, rate, amount, billable_to, notes))
    conn.commit()
    return round(amount, 2)


def get_charges(shipment_ref):
    conn = get_db()
    _init_tables(conn)
    rows = conn.execute(
        "SELECT * FROM accessorial_charges WHERE shipment_ref=? ORDER BY created_at DESC",
        (shipment_ref,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_charges_summary(shipment_ref):
    rows = get_charges(shipment_ref)
    total_customer = sum(r['amount'] for r in rows if r['billable_to'] == 'customer')
    total_carrier = sum(r['amount'] for r in rows if r['billable_to'] == 'carrier')
    return {
        "charges": rows,
        "total_customer_billable": round(total_customer, 2),
        "total_carrier_billable": round(total_carrier, 2),
        "total": round(total_customer + total_carrier, 2),
    }


def approve_charge(charge_id, approved_by):
    conn = get_db()
    conn.execute(
        "UPDATE accessorial_charges SET status='approved', approved_by=? WHERE id=?",
        (approved_by, charge_id)
    )
    conn.commit()


def delete_charge(charge_id):
    conn = get_db()
    conn.execute("DELETE FROM accessorial_charges WHERE id=?", (charge_id,))
    conn.commit()


def get_all_pending_charges():
    conn = get_db()
    _init_tables(conn)
    rows = conn.execute("""
        SELECT ac.*, s.customer_name, s.carrier_name
        FROM accessorial_charges ac
        JOIN shipments s ON s.shipment_ref = ac.shipment_ref
        WHERE ac.status = 'pending'
        ORDER BY ac.created_at DESC LIMIT 100
    """).fetchall()
    return [dict(r) for r in rows]


# ── Detention timer ───────────────────────────────────────────────────────────

def start_detention_timer(shipment_ref, location_type='delivery',
                           free_hours=2.0, rate_per_hour=75.00):
    conn = get_db()
    _init_tables(conn)
    cur = conn.execute("""
        INSERT INTO detention_timers
        (shipment_ref, location_type, arrived_at, free_hours, rate_per_hour)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?)
    """, (shipment_ref, location_type, free_hours, rate_per_hour))
    conn.commit()
    return cur.lastrowid


def stop_detention_timer(timer_id):
    """Stop timer, calculate detention, auto-create charge if billable."""
    conn = get_db()
    conn.execute(
        "UPDATE detention_timers SET departed_at=CURRENT_TIMESTAMP, status='completed' WHERE id=?",
        (timer_id,)
    )
    conn.commit()

    timer = conn.execute("SELECT * FROM detention_timers WHERE id=?", (timer_id,)).fetchone()
    if not timer or not timer['departed_at']:
        return None

    try:
        arrived = datetime.fromisoformat(str(timer['arrived_at']))
        departed = datetime.fromisoformat(str(timer['departed_at']))
        total_hours = (departed - arrived).total_seconds() / 3600
        billable_hours = max(0, total_hours - timer['free_hours'])
        amount = billable_hours * timer['rate_per_hour']
    except Exception:
        return None

    result = {
        "timer_id": timer_id,
        "total_hours": round(total_hours, 2),
        "free_hours": timer['free_hours'],
        "billable_hours": round(billable_hours, 2),
        "rate_per_hour": timer['rate_per_hour'],
        "amount": round(amount, 2),
    }

    if billable_hours > 0:
        add_charge(
            timer['shipment_ref'], 'detention',
            timer['rate_per_hour'], billable_hours,
            description=f"Detention — {result['billable_hours']:.1f} billable hrs ({result['total_hours']:.1f} total - {timer['free_hours']:.1f} free)",
            billable_to='customer'
        )
        result['charge_created'] = True
    else:
        result['charge_created'] = False

    return result


def get_active_timers():
    conn = get_db()
    _init_tables(conn)
    rows = conn.execute("""
        SELECT dt.*, s.customer_name, s.carrier_name
        FROM detention_timers dt
        JOIN shipments s ON s.shipment_ref = dt.shipment_ref
        WHERE dt.status = 'active'
        ORDER BY dt.arrived_at ASC
    """).fetchall()
    now = datetime.utcnow()
    result = []
    for r in rows:
        item = dict(r)
        try:
            arrived = datetime.fromisoformat(str(r['arrived_at']))
            elapsed = (now - arrived).total_seconds() / 3600
            item['elapsed_hours'] = round(elapsed, 2)
            item['billable_hours'] = round(max(0, elapsed - r['free_hours']), 2)
            item['accrued_amount'] = round(item['billable_hours'] * r['rate_per_hour'], 2)
            item['status_color'] = 'danger' if item['billable_hours'] > 0 else 'warning' if elapsed > r['free_hours'] * 0.75 else 'success'
        except Exception:
            item['elapsed_hours'] = 0
            item['billable_hours'] = 0
            item['accrued_amount'] = 0
            item['status_color'] = 'secondary'
        result.append(item)
    return result


# ── Accessorial dashboard ─────────────────────────────────────────────────────

def get_accessorial_dashboard():
    conn = get_db()
    _init_tables(conn)
    pending = get_all_pending_charges()
    active_timers = get_active_timers()
    total_pending_value = sum(c['amount'] for c in pending)
    total_accruing = sum(t['accrued_amount'] for t in active_timers)

    monthly = conn.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               SUM(amount) as total, COUNT(*) as count
        FROM accessorial_charges
        WHERE status='approved'
        GROUP BY month ORDER BY month DESC LIMIT 6
    """).fetchall()

    by_type = conn.execute("""
        SELECT charge_type, SUM(amount) as total, COUNT(*) as count
        FROM accessorial_charges WHERE status='approved'
        GROUP BY charge_type ORDER BY total DESC
    """).fetchall()

    return {
        "pending_charges": pending,
        "active_timers": active_timers,
        "total_pending_value": round(total_pending_value, 2),
        "total_accruing": round(total_accruing, 2),
        "monthly_summary": [dict(r) for r in monthly],
        "by_type": [dict(r) for r in by_type],
        "accessorial_types": ACCESSORIAL_TYPES,
        "rate_feed_providers": RATE_FEED_PROVIDERS,
    }
