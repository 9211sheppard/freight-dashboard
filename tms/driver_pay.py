"""
Driver Pay & Settlement Module
Client enters their pay structure. Module calculates, generates settlement sheets.
"""
from datetime import datetime, date
from .tms_db import get_db


def _init_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS driver_pay_structures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            pay_type TEXT NOT NULL DEFAULT 'per_mile',
            rate_per_mile REAL DEFAULT 0,
            rate_per_hour REAL DEFAULT 0,
            rate_percentage REAL DEFAULT 0,
            flat_rate_per_load REAL DEFAULT 0,
            per_diem_daily REAL DEFAULT 0,
            fuel_surcharge_passthrough INTEGER DEFAULT 0,
            detention_rate_per_hour REAL DEFAULT 0,
            detention_free_hours REAL DEFAULT 2.0,
            layover_daily REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            effective_from DATE,
            active INTEGER DEFAULT 1,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS driver_settlements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            settlement_ref TEXT UNIQUE NOT NULL,
            period_start DATE NOT NULL,
            period_end DATE NOT NULL,
            status TEXT DEFAULT 'draft',
            gross_pay REAL DEFAULT 0,
            deductions REAL DEFAULT 0,
            net_pay REAL DEFAULT 0,
            miles_driven REAL DEFAULT 0,
            loads_completed INTEGER DEFAULT 0,
            hours_worked REAL DEFAULT 0,
            line_items_json TEXT DEFAULT '[]',
            notes TEXT,
            approved_by TEXT,
            approved_at TIMESTAMP,
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS driver_deductions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            deduction_type TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            settlement_id INTEGER,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    """)
    conn.commit()


# ── Pay Structure ─────────────────────────────────────────────────────────────

def get_pay_structure(driver_id):
    conn = get_db()
    _init_tables(conn)
    row = conn.execute(
        "SELECT * FROM driver_pay_structures WHERE driver_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (driver_id,)
    ).fetchone()
    return dict(row) if row else None


def save_pay_structure(driver_id, data):
    conn = get_db()
    _init_tables(conn)
    # Deactivate old
    conn.execute(
        "UPDATE driver_pay_structures SET active=0 WHERE driver_id=?", (driver_id,)
    )
    conn.execute("""
        INSERT INTO driver_pay_structures
        (driver_id, pay_type, rate_per_mile, rate_per_hour, rate_percentage,
         flat_rate_per_load, per_diem_daily, fuel_surcharge_passthrough,
         detention_rate_per_hour, detention_free_hours, layover_daily, currency, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        driver_id,
        data.get('pay_type', 'per_mile'),
        float(data.get('rate_per_mile') or 0),
        float(data.get('rate_per_hour') or 0),
        float(data.get('rate_percentage') or 0),
        float(data.get('flat_rate_per_load') or 0),
        float(data.get('per_diem_daily') or 0),
        int(data.get('fuel_surcharge_passthrough') or 0),
        float(data.get('detention_rate_per_hour') or 0),
        float(data.get('detention_free_hours') or 2.0),
        float(data.get('layover_daily') or 0),
        data.get('currency', 'USD'),
        data.get('notes', '')
    ))
    conn.commit()


# ── Settlement Calculation ────────────────────────────────────────────────────

def calculate_settlement(driver_id, period_start, period_end):
    """
    Calculate gross pay for a driver over a date range.
    Reads duty_logs for hours, shipments for loads/miles/revenue.
    Returns settlement dict with line_items.
    """
    conn = get_db()
    _init_tables(conn)

    structure = get_pay_structure(driver_id)
    if not structure:
        return {"error": "No pay structure set for this driver"}

    line_items = []
    gross = 0.0

    # ── Loads completed in period ─────────────────────────────────────────────
    loads = conn.execute("""
        SELECT s.shipment_ref, s.freight_rate, s.origin_port, s.destination_port,
               s.weight_kg, s.updated_at
        FROM shipments s
        JOIN duty_logs dl ON dl.shipment_id = s.id
        WHERE dl.driver_id = ? AND s.status = 'Delivered'
          AND date(s.updated_at) BETWEEN ? AND ?
        GROUP BY s.id
    """, (driver_id, period_start, period_end)).fetchall()

    loads_count = len(loads)
    total_revenue = sum(l['freight_rate'] or 0 for l in loads)

    pay_type = structure['pay_type']

    if pay_type == 'per_load':
        amount = loads_count * structure['flat_rate_per_load']
        line_items.append({
            "description": f"Load pay — {loads_count} loads × ${structure['flat_rate_per_load']:.2f}",
            "amount": round(amount, 2)
        })
        gross += amount

    elif pay_type == 'percentage':
        amount = total_revenue * (structure['rate_percentage'] / 100)
        line_items.append({
            "description": f"Revenue share — {structure['rate_percentage']}% of ${total_revenue:,.2f}",
            "amount": round(amount, 2)
        })
        gross += amount

    elif pay_type == 'per_hour':
        hours = conn.execute("""
            SELECT COALESCE(SUM(
                (julianday(end_time) - julianday(start_time)) * 24
            ), 0) as total_hours
            FROM duty_logs
            WHERE driver_id=? AND date(start_time) BETWEEN ? AND ?
        """, (driver_id, period_start, period_end)).fetchone()['total_hours']
        amount = hours * structure['rate_per_hour']
        line_items.append({
            "description": f"Hourly pay — {hours:.1f} hrs × ${structure['rate_per_hour']:.2f}/hr",
            "amount": round(amount, 2)
        })
        gross += amount

    else:  # per_mile (default)
        # Estimate miles from shipment legs or use weight proxy
        miles = conn.execute("""
            SELECT COALESCE(SUM(distance_miles), 0) as total
            FROM route_stops rs
            JOIN loads l ON l.id = rs.load_id
            JOIN load_shipments ls ON ls.load_id = l.id
            JOIN shipments s ON s.shipment_ref = ls.shipment_ref
            JOIN duty_logs dl ON dl.shipment_id = s.id
            WHERE dl.driver_id=? AND date(s.updated_at) BETWEEN ? AND ?
        """, (driver_id, period_start, period_end)).fetchone()['total'] or 0

        if not miles and loads_count:
            miles = loads_count * 450  # fallback estimate

        amount = miles * structure['rate_per_mile']
        line_items.append({
            "description": f"Mileage pay — {miles:.0f} mi × ${structure['rate_per_mile']:.4f}/mi",
            "amount": round(amount, 2)
        })
        gross += amount

    # ── Per diem ──────────────────────────────────────────────────────────────
    if structure['per_diem_daily'] > 0:
        try:
            d1 = datetime.strptime(str(period_start), "%Y-%m-%d")
            d2 = datetime.strptime(str(period_end), "%Y-%m-%d")
            days_away = max(0, (d2 - d1).days)
        except Exception:
            days_away = 0
        if days_away > 0:
            per_diem = days_away * structure['per_diem_daily']
            line_items.append({
                "description": f"Per diem — {days_away} days × ${structure['per_diem_daily']:.2f}",
                "amount": round(per_diem, 2)
            })
            gross += per_diem

    # ── Deductions ────────────────────────────────────────────────────────────
    deductions_rows = conn.execute("""
        SELECT deduction_type, amount, description
        FROM driver_deductions
        WHERE driver_id=? AND settlement_id IS NULL
          AND date(applied_at) BETWEEN ? AND ?
    """, (driver_id, period_start, period_end)).fetchall()

    total_deductions = 0.0
    for d in deductions_rows:
        total_deductions += d['amount']
        line_items.append({
            "description": f"Deduction: {d['deduction_type']} — {d['description'] or ''}",
            "amount": round(-d['amount'], 2)
        })

    net_pay = gross - total_deductions

    return {
        "driver_id": driver_id,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "pay_type": pay_type,
        "loads_completed": loads_count,
        "gross_pay": round(gross, 2),
        "deductions": round(total_deductions, 2),
        "net_pay": round(net_pay, 2),
        "line_items": line_items,
        "currency": structure['currency'],
    }


def create_settlement(driver_id, period_start, period_end, notes=''):
    """Save a calculated settlement to DB."""
    conn = get_db()
    _init_tables(conn)
    calc = calculate_settlement(driver_id, period_start, period_end)
    if 'error' in calc:
        return calc

    import secrets
    ref = "SET-" + secrets.token_hex(4).upper()

    conn.execute("""
        INSERT INTO driver_settlements
        (driver_id, settlement_ref, period_start, period_end, status,
         gross_pay, deductions, net_pay, loads_completed, line_items_json, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        driver_id, ref, period_start, period_end, 'draft',
        calc['gross_pay'], calc['deductions'], calc['net_pay'],
        calc['loads_completed'], __import__('json').dumps(calc['line_items']), notes
    ))
    conn.commit()
    calc['settlement_ref'] = ref
    return calc


def approve_settlement(settlement_id, approved_by):
    conn = get_db()
    conn.execute(
        "UPDATE driver_settlements SET status='approved', approved_by=?, approved_at=CURRENT_TIMESTAMP WHERE id=?",
        (approved_by, settlement_id)
    )
    conn.commit()


def mark_paid(settlement_id):
    conn = get_db()
    conn.execute(
        "UPDATE driver_settlements SET status='paid', paid_at=CURRENT_TIMESTAMP WHERE id=?",
        (settlement_id,)
    )
    conn.commit()


def get_settlements(driver_id=None, status=None):
    conn = get_db()
    _init_tables(conn)
    q = "SELECT ds.*, d.name as driver_name FROM driver_settlements ds JOIN drivers d ON d.id=ds.driver_id WHERE 1=1"
    params = []
    if driver_id:
        q += " AND ds.driver_id=?"
        params.append(driver_id)
    if status:
        q += " AND ds.status=?"
        params.append(status)
    q += " ORDER BY ds.created_at DESC LIMIT 100"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def get_settlement(settlement_id):
    conn = get_db()
    row = conn.execute(
        "SELECT ds.*, d.name as driver_name FROM driver_settlements ds JOIN drivers d ON d.id=ds.driver_id WHERE ds.id=?",
        (settlement_id,)
    ).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result['line_items'] = __import__('json').loads(result.get('line_items_json') or '[]')
    except Exception:
        result['line_items'] = []
    return result
