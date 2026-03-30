"""
Live Map + Geofencing Engine
Reads tracking_pings from DB. Geofence alerts stored and evaluated on each ping.
Client plugs in their GPS provider via tms_integrations (Samsara, Motive, etc.)
"""
import json
import math
from datetime import datetime, timedelta
from .tms_db import get_db


# ── Geofence helpers ──────────────────────────────────────────────────────────

def _haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles."""
    R = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def _init_geofence_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geofences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            radius_miles REAL NOT NULL DEFAULT 0.5,
            fence_type TEXT DEFAULT 'poi',
            shipment_ref TEXT,
            alert_on_entry INTEGER DEFAULT 1,
            alert_on_exit INTEGER DEFAULT 1,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geofence_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            geofence_id INTEGER NOT NULL,
            shipment_ref TEXT,
            driver_id INTEGER,
            event_type TEXT NOT NULL,
            lat REAL, lon REAL,
            triggered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notified INTEGER DEFAULT 0,
            FOREIGN KEY (geofence_id) REFERENCES geofences(id)
        )
    """)
    conn.commit()


# ── Live tracking data ────────────────────────────────────────────────────────

def get_live_shipments():
    """
    All active shipments with their latest GPS ping.
    Returns list ready for map markers.
    """
    conn = get_db()
    _init_geofence_tables(conn)

    rows = conn.execute("""
        SELECT
            s.id, s.shipment_ref, s.status, s.carrier_name,
            s.origin_port, s.destination_port, s.eta,
            s.customer_name,
            d.name as driver_name, d.id as driver_id,
            tp.lat, tp.lon, tp.speed_mph, tp.heading,
            tp.recorded_at as last_ping,
            tp.location_label
        FROM shipments s
        LEFT JOIN drivers d ON d.id = (
            SELECT driver_id FROM duty_logs
            WHERE shipment_id = s.id AND status = 'Driving'
            ORDER BY start_time DESC LIMIT 1
        )
        LEFT JOIN tracking_pings tp ON tp.id = (
            SELECT id FROM tracking_pings
            WHERE shipment_ref = s.shipment_ref
            ORDER BY recorded_at DESC LIMIT 1
        )
        WHERE s.status NOT IN ('Delivered', 'Cancelled', 'Draft')
        ORDER BY tp.recorded_at DESC
    """).fetchall()

    result = []
    for r in rows:
        item = dict(r)
        # Staleness flag
        if r['last_ping']:
            try:
                last = datetime.fromisoformat(str(r['last_ping']))
                age_hours = (datetime.utcnow() - last).total_seconds() / 3600
                item['ping_age_hours'] = round(age_hours, 1)
                item['stale'] = age_hours > 4
            except Exception:
                item['ping_age_hours'] = None
                item['stale'] = True
        else:
            item['ping_age_hours'] = None
            item['stale'] = True
        result.append(item)
    return result


def get_shipment_trail(shipment_ref, hours=24):
    """Breadcrumb trail for one shipment — last N hours of pings."""
    conn = get_db()
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    rows = conn.execute("""
        SELECT lat, lon, speed_mph, heading, recorded_at, location_label
        FROM tracking_pings
        WHERE shipment_ref = ? AND recorded_at >= ?
        ORDER BY recorded_at ASC
    """, (shipment_ref, since)).fetchall()
    return [dict(r) for r in rows]


def get_map_summary():
    """Stats bar above the map."""
    conn = get_db()
    total_active = conn.execute(
        "SELECT COUNT(*) FROM shipments WHERE status NOT IN ('Delivered','Cancelled','Draft')"
    ).fetchone()[0]
    with_gps = conn.execute("""
        SELECT COUNT(DISTINCT shipment_ref) FROM tracking_pings
        WHERE recorded_at >= datetime('now','-4 hours')
    """).fetchone()[0]
    recent_alerts = conn.execute(
        "SELECT COUNT(*) FROM geofence_events WHERE triggered_at >= datetime('now','-24 hours')"
    ).fetchone()[0] if _table_exists(conn, 'geofence_events') else 0
    geofences_active = conn.execute(
        "SELECT COUNT(*) FROM geofences WHERE active=1"
    ).fetchone()[0] if _table_exists(conn, 'geofences') else 0
    return {
        "total_active": total_active,
        "with_gps": with_gps,
        "no_gps": total_active - with_gps,
        "recent_alerts": recent_alerts,
        "geofences_active": geofences_active,
    }


def _table_exists(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# ── Geofence CRUD ─────────────────────────────────────────────────────────────

def get_geofences():
    conn = get_db()
    _init_geofence_tables(conn)
    rows = conn.execute(
        "SELECT * FROM geofences ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def create_geofence(name, lat, lon, radius_miles, fence_type='poi',
                    shipment_ref=None, alert_entry=True, alert_exit=True):
    conn = get_db()
    _init_geofence_tables(conn)
    cur = conn.execute(
        """INSERT INTO geofences (name, lat, lon, radius_miles, fence_type,
           shipment_ref, alert_on_entry, alert_on_exit)
           VALUES (?,?,?,?,?,?,?,?)""",
        (name, lat, lon, radius_miles, fence_type, shipment_ref,
         int(alert_entry), int(alert_exit))
    )
    conn.commit()
    return cur.lastrowid


def delete_geofence(fence_id):
    conn = get_db()
    conn.execute("UPDATE geofences SET active=0 WHERE id=?", (fence_id,))
    conn.commit()


def get_geofence_events(limit=50):
    conn = get_db()
    _init_geofence_tables(conn)
    rows = conn.execute("""
        SELECT ge.*, gf.name as fence_name, gf.radius_miles
        FROM geofence_events ge
        JOIN geofences gf ON gf.id = ge.geofence_id
        ORDER BY ge.triggered_at DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def evaluate_geofences(shipment_ref, lat, lon, driver_id=None):
    """
    Called on every new tracking ping.
    Returns list of triggered geofence events.
    """
    conn = get_db()
    _init_geofence_tables(conn)
    fences = conn.execute(
        "SELECT * FROM geofences WHERE active=1"
    ).fetchall()

    triggered = []
    for fence in fences:
        dist = _haversine_miles(lat, lon, fence['lat'], fence['lon'])
        inside = dist <= fence['radius_miles']

        # Check previous state
        last = conn.execute("""
            SELECT event_type FROM geofence_events
            WHERE geofence_id=? AND shipment_ref=?
            ORDER BY triggered_at DESC LIMIT 1
        """, (fence['id'], shipment_ref)).fetchone()

        prev_inside = (last and last['event_type'] == 'entry')

        if inside and not prev_inside and fence['alert_on_entry']:
            conn.execute(
                """INSERT INTO geofence_events
                   (geofence_id, shipment_ref, driver_id, event_type, lat, lon)
                   VALUES (?,?,?,?,?,?)""",
                (fence['id'], shipment_ref, driver_id, 'entry', lat, lon)
            )
            triggered.append({'fence': dict(fence), 'event': 'entry', 'distance_miles': round(dist, 3)})
        elif not inside and prev_inside and fence['alert_on_exit']:
            conn.execute(
                """INSERT INTO geofence_events
                   (geofence_id, shipment_ref, driver_id, event_type, lat, lon)
                   VALUES (?,?,?,?,?,?)""",
                (fence['id'], shipment_ref, driver_id, 'exit', lat, lon)
            )
            triggered.append({'fence': dict(fence), 'event': 'exit', 'distance_miles': round(dist, 3)})

    if triggered:
        conn.commit()
    return triggered


def ingest_ping(shipment_ref, lat, lon, speed_mph=None,
                heading=None, location_label=None, driver_id=None):
    """
    Write a new tracking ping and evaluate geofences.
    Called by GPS provider webhooks or ELD sync.
    """
    conn = get_db()
    conn.execute("""
        INSERT INTO tracking_pings
        (shipment_ref, lat, lon, speed_mph, heading, location_label, recorded_at)
        VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)
    """, (shipment_ref, lat, lon, speed_mph, heading, location_label))
    conn.commit()
    return evaluate_geofences(shipment_ref, lat, lon, driver_id)
