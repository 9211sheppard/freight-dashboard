"""
DVIR — Driver Vehicle Inspection Reports + Fleet Maintenance
FMCSA 49 CFR Part 396 compliant pre/post-trip inspections.
"""
import secrets
from datetime import datetime, timedelta
from .tms_db import get_db

INSPECTION_ITEMS = [
    ("Air Brakes", "brakes"), ("Service Brakes", "brakes"), ("Parking Brake", "brakes"),
    ("Steering", "steering"), ("Lights — Head", "lights"), ("Lights — Tail", "lights"),
    ("Lights — Stop", "lights"), ("Lights — Turn Signal", "lights"),
    ("Windshield Wipers", "cab"), ("Horn", "cab"), ("Heater/Defroster", "cab"),
    ("Mirrors", "cab"), ("Coupling Devices", "coupling"),
    ("Tires — Steering Axle", "tires"), ("Tires — Drive Axle", "tires"),
    ("Wheels and Rims", "tires"), ("Emergency Equipment", "safety"),
    ("Fire Extinguisher", "safety"), ("Reflective Triangles", "safety"),
    ("Spare Fuses", "safety"), ("Fuel System", "engine"),
    ("Engine Compartment", "engine"), ("Exhaust System", "engine"),
    ("Frame and Body", "body"), ("Suspension System", "body"),
    ("5th Wheel", "coupling"), ("Cargo Securement", "cargo"),
]

MAINTENANCE_TYPES = [
    "Oil Change", "Tire Rotation", "Brake Inspection", "Brake Replacement",
    "Annual DOT Inspection", "PM Service A", "PM Service B",
    "Transmission Service", "Coolant Flush", "Belt Replacement",
    "Filter Replacement", "Tire Replacement", "Wheel Alignment",
    "Electrical Repair", "Body Repair", "Engine Repair", "Custom"
]


def _init_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dvir_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_ref TEXT UNIQUE NOT NULL,
            vehicle_id INTEGER,
            driver_id INTEGER,
            inspection_type TEXT DEFAULT 'pre_trip',
            odometer REAL,
            location TEXT,
            overall_status TEXT DEFAULT 'satisfactory',
            defects_json TEXT DEFAULT '[]',
            driver_signature TEXT,
            mechanic_signature TEXT,
            mechanic_notes TEXT,
            certified_safe INTEGER DEFAULT 0,
            certified_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            maintenance_type TEXT NOT NULL,
            interval_miles REAL,
            interval_days INTEGER,
            last_done_at DATE,
            last_odometer REAL,
            next_due_date DATE,
            next_due_miles REAL,
            vendor TEXT,
            cost REAL,
            notes TEXT,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_work_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wo_ref TEXT UNIQUE NOT NULL,
            vehicle_id INTEGER NOT NULL,
            maintenance_type TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            odometer REAL,
            vendor TEXT,
            scheduled_date DATE,
            completed_date DATE,
            cost REAL DEFAULT 0,
            parts_cost REAL DEFAULT 0,
            labor_cost REAL DEFAULT 0,
            notes TEXT,
            dvir_defect_ref TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
        )
    """)
    conn.commit()


def create_dvir(vehicle_id, driver_id, inspection_type='pre_trip',
                odometer=None, location='', defects=None):
    """
    defects: list of {"item": str, "category": str, "severity": "minor/major/critical", "notes": str}
    """
    conn = get_db()
    _init_tables(conn)
    import json
    ref = "DVIR-" + secrets.token_hex(4).upper()
    defects = defects or []
    overall = "satisfactory"
    if any(d.get('severity') == 'critical' for d in defects):
        overall = "out_of_service"
    elif any(d.get('severity') == 'major' for d in defects):
        overall = "defects_noted"
    elif defects:
        overall = "defects_noted"

    conn.execute("""
        INSERT INTO dvir_reports
        (report_ref, vehicle_id, driver_id, inspection_type, odometer, location,
         overall_status, defects_json)
        VALUES (?,?,?,?,?,?,?,?)
    """, (ref, vehicle_id, driver_id, inspection_type, odometer, location,
          overall, json.dumps(defects)))
    conn.commit()
    # Auto-create work orders for critical/major defects
    for d in defects:
        if d.get('severity') in ('major', 'critical'):
            _auto_work_order(conn, vehicle_id, d, ref)
    return ref


def _auto_work_order(conn, vehicle_id, defect, dvir_ref):
    wo_ref = "WO-" + secrets.token_hex(4).upper()
    conn.execute("""
        INSERT INTO maintenance_work_orders
        (wo_ref, vehicle_id, maintenance_type, status, notes, dvir_defect_ref)
        VALUES (?,?,?,?,?,?)
    """, (wo_ref, vehicle_id, defect.get('item', 'Defect Repair'),
          'open', defect.get('notes', ''), dvir_ref))
    conn.commit()


def certify_dvir(report_id, mechanic_signature, notes='', certified_safe=True):
    conn = get_db()
    conn.execute("""
        UPDATE dvir_reports SET mechanic_signature=?, mechanic_notes=?,
        certified_safe=?, certified_at=CURRENT_TIMESTAMP WHERE id=?
    """, (mechanic_signature, notes, int(certified_safe), report_id))
    conn.commit()


def get_dvir_reports(vehicle_id=None, driver_id=None, limit=50):
    conn = get_db()
    _init_tables(conn)
    import json
    q = """SELECT dr.*, v.truck_number, d.name as driver_name
           FROM dvir_reports dr
           LEFT JOIN vehicles v ON v.id = dr.vehicle_id
           LEFT JOIN drivers d ON d.id = dr.driver_id
           WHERE 1=1"""
    params = []
    if vehicle_id:
        q += " AND dr.vehicle_id=?"; params.append(vehicle_id)
    if driver_id:
        q += " AND dr.driver_id=?"; params.append(driver_id)
    q += " ORDER BY dr.created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        try:
            item['defects'] = json.loads(item.get('defects_json') or '[]')
        except Exception:
            item['defects'] = []
        result.append(item)
    return result


def get_maintenance_due(days_ahead=30):
    """Vehicles with maintenance due within N days or overdue."""
    conn = get_db()
    _init_tables(conn)
    cutoff = (datetime.utcnow() + timedelta(days=days_ahead)).date().isoformat()
    rows = conn.execute("""
        SELECT ms.*, v.truck_number, v.vehicle_type
        FROM maintenance_schedules ms
        JOIN vehicles v ON v.id = ms.vehicle_id
        WHERE ms.active=1 AND (
            (ms.next_due_date IS NOT NULL AND ms.next_due_date <= ?)
        )
        ORDER BY ms.next_due_date ASC
    """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def create_maintenance_schedule(vehicle_id, maint_type, interval_miles=None,
                                 interval_days=None, last_done=None, last_odo=None, vendor=''):
    conn = get_db()
    _init_tables(conn)
    # Calculate next due
    next_date = None
    if last_done and interval_days:
        try:
            ld = datetime.strptime(str(last_done), "%Y-%m-%d")
            next_date = (ld + timedelta(days=interval_days)).strftime("%Y-%m-%d")
        except Exception:
            pass
    next_miles = (last_odo + interval_miles) if (last_odo and interval_miles) else None
    conn.execute("""
        INSERT INTO maintenance_schedules
        (vehicle_id, maintenance_type, interval_miles, interval_days,
         last_done_at, last_odometer, next_due_date, next_due_miles, vendor)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (vehicle_id, maint_type, interval_miles, interval_days,
          last_done, last_odo, next_date, next_miles, vendor))
    conn.commit()


def get_work_orders(status=None):
    conn = get_db()
    _init_tables(conn)
    q = """SELECT wo.*, v.truck_number FROM maintenance_work_orders wo
           JOIN vehicles v ON v.id = wo.vehicle_id WHERE 1=1"""
    params = []
    if status:
        q += " AND wo.status=?"; params.append(status)
    q += " ORDER BY wo.created_at DESC LIMIT 100"
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def close_work_order(wo_id, cost, parts_cost, labor_cost, notes=''):
    conn = get_db()
    conn.execute("""
        UPDATE maintenance_work_orders SET status='completed',
        completed_date=date('now'), cost=?, parts_cost=?, labor_cost=?, notes=?
        WHERE id=?
    """, (cost, parts_cost, labor_cost, notes, wo_id))
    conn.commit()


def get_fleet_health_dashboard():
    conn = get_db()
    _init_tables(conn)
    total_vehicles = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    oos = conn.execute(
        "SELECT COUNT(DISTINCT vehicle_id) FROM dvir_reports WHERE overall_status='out_of_service' AND certified_safe=0 AND created_at >= datetime('now','-1 day')"
    ).fetchone()[0]
    open_wo = conn.execute("SELECT COUNT(*) FROM maintenance_work_orders WHERE status='open'").fetchone()[0]
    due_soon = get_maintenance_due(30)
    overdue = get_maintenance_due(0)
    recent_dvir = get_dvir_reports(limit=10)
    open_orders = get_work_orders('open')
    return {
        "total_vehicles": total_vehicles,
        "out_of_service": oos,
        "open_work_orders": open_wo,
        "maintenance_due_count": len(due_soon),
        "overdue_count": len(overdue),
        "recent_dvir": recent_dvir,
        "work_orders": open_orders,
        "maintenance_due": due_soon[:10],
        "inspection_items": INSPECTION_ITEMS,
        "maintenance_types": MAINTENANCE_TYPES,
    }
