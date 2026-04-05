"""Carrier Performance Scorecard — auto-ranks carriers per lane."""
import sqlite3, os
from datetime import datetime

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_scorecard_tables():
    conn = get_db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS carrier_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier_name TEXT NOT NULL,
            scac TEXT DEFAULT '',
            shipment_ref TEXT DEFAULT '',
            origin_state TEXT DEFAULT '',
            destination_state TEXT DEFAULT '',
            lane TEXT DEFAULT '',
            scheduled_pickup TEXT DEFAULT '',
            actual_pickup TEXT DEFAULT '',
            scheduled_delivery TEXT DEFAULT '',
            actual_delivery TEXT DEFAULT '',
            on_time_pickup INTEGER DEFAULT NULL,
            on_time_delivery INTEGER DEFAULT NULL,
            damage_reported INTEGER DEFAULT 0,
            damage_notes TEXT DEFAULT '',
            rate_charged REAL DEFAULT 0,
            rate_market REAL DEFAULT 0,
            communication_score INTEGER DEFAULT NULL,
            overall_score REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS carrier_scorecards (
            carrier_name TEXT PRIMARY KEY,
            scac TEXT DEFAULT '',
            total_shipments INTEGER DEFAULT 0,
            on_time_delivery_pct REAL DEFAULT 0,
            on_time_pickup_pct REAL DEFAULT 0,
            damage_rate_pct REAL DEFAULT 0,
            avg_rate_vs_market REAL DEFAULT 0,
            avg_communication_score REAL DEFAULT 0,
            overall_score REAL DEFAULT 0,
            preferred_lanes TEXT DEFAULT '',
            last_shipment TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
    finally:
        conn.close()

init_scorecard_tables()

def log_carrier_performance(data: dict):
    """Log a shipment performance record and recalculate the carrier scorecard."""
    conn = get_db()
    try:
        def is_on_time(scheduled, actual):
            if not scheduled or not actual:
                return None
            try:
                s = datetime.fromisoformat(scheduled.replace('Z',''))
                a = datetime.fromisoformat(actual.replace('Z',''))
                return 1 if a <= s else 0
            except:
                return None

        lane = f"{data.get('origin_state','')}-{data.get('destination_state','')}"
        otp = is_on_time(data.get('scheduled_pickup'), data.get('actual_pickup'))
        otd = is_on_time(data.get('scheduled_delivery'), data.get('actual_delivery'))

        conn.execute(
            """INSERT INTO carrier_performance
               (carrier_name, scac, shipment_ref, origin_state, destination_state, lane,
                scheduled_pickup, actual_pickup, scheduled_delivery, actual_delivery,
                on_time_pickup, on_time_delivery, damage_reported, damage_notes,
                rate_charged, rate_market, communication_score, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (data.get('carrier_name',''), data.get('scac',''), data.get('shipment_ref',''),
             data.get('origin_state',''), data.get('destination_state',''), lane,
             data.get('scheduled_pickup',''), data.get('actual_pickup',''),
             data.get('scheduled_delivery',''), data.get('actual_delivery',''),
             otp, otd, 1 if data.get('damage_reported') else 0,
             data.get('damage_notes',''), float(data.get('rate_charged') or 0),
             float(data.get('rate_market') or 0), data.get('communication_score') or None,
             data.get('notes',''))
        )
        conn.commit()
        _recalculate_scorecard(data['carrier_name'], conn)
    finally:
        conn.close()

def _recalculate_scorecard(carrier_name: str, conn):
    rows = conn.execute(
        "SELECT * FROM carrier_performance WHERE carrier_name=?", (carrier_name,)
    ).fetchall()
    if not rows:
        return
    total = len(rows)
    otd = [r for r in rows if r['on_time_delivery'] is not None]
    otp = [r for r in rows if r['on_time_pickup'] is not None]
    comm = [r['communication_score'] for r in rows if r['communication_score']]
    rates = [r for r in rows if r['rate_charged'] > 0 and r['rate_market'] > 0]
    lanes = list(set(r['lane'] for r in rows if r['lane']))

    otd_pct = (sum(r['on_time_delivery'] for r in otd) / len(otd) * 100) if otd else 0
    otp_pct = (sum(r['on_time_pickup'] for r in otp) / len(otp) * 100) if otp else 0
    dmg_pct = (sum(r['damage_reported'] for r in rows) / total * 100)
    avg_comm = (sum(comm) / len(comm)) if comm else 3.0
    rate_diff = 0
    if rates:
        diffs = [(r['rate_charged'] - r['rate_market']) / r['rate_market'] * 100 for r in rates]
        rate_diff = sum(diffs) / len(diffs)

    score = (
        otd_pct * 0.40 +
        otp_pct * 0.15 +
        max(0, 100 - dmg_pct * 10) * 0.25 +
        (avg_comm / 5 * 100) * 0.10 +
        max(0, 100 - max(0, rate_diff)) * 0.10
    )

    last = max(rows, key=lambda r: r['created_at'])['created_at']

    conn.execute(
        """INSERT OR REPLACE INTO carrier_scorecards
           (carrier_name, total_shipments, on_time_delivery_pct, on_time_pickup_pct,
            damage_rate_pct, avg_rate_vs_market, avg_communication_score, overall_score,
            preferred_lanes, last_shipment, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
        (carrier_name, total, round(otd_pct, 1), round(otp_pct, 1),
         round(dmg_pct, 1), round(rate_diff, 1), round(avg_comm, 1),
         round(score, 1), ",".join(lanes[:5]), last)
    )
    conn.commit()

def get_all_scorecards():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM carrier_scorecards ORDER BY overall_score DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_best_carrier_for_lane(origin_state, destination_state):
    """Returns ranked list of carriers for a lane, best first."""
    lane = f"{origin_state}-{destination_state}"
    conn = get_db()
    try:
        lane_carriers = conn.execute(
            """SELECT carrier_name, COUNT(*) as trips,
               AVG(CASE WHEN on_time_delivery=1 THEN 100.0 ELSE 0 END) as otd,
               AVG(rate_charged) as avg_rate
               FROM carrier_performance WHERE lane=?
               GROUP BY carrier_name ORDER BY otd DESC, avg_rate ASC""",
            (lane,)
        ).fetchall()
        if lane_carriers:
            return [dict(r) for r in lane_carriers]
        rows = conn.execute(
            "SELECT * FROM carrier_scorecards ORDER BY overall_score DESC LIMIT 5"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_carrier_history(carrier_name):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM carrier_performance WHERE carrier_name=? ORDER BY created_at DESC LIMIT 50",
            (carrier_name,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_scorecard_stats():
    conn = get_db()
    try:
        total_carriers = conn.execute("SELECT COUNT(*) FROM carrier_scorecards").fetchone()[0]
        avg_otd = conn.execute("SELECT AVG(on_time_delivery_pct) FROM carrier_scorecards").fetchone()[0] or 0
        top = conn.execute(
            "SELECT carrier_name, overall_score FROM carrier_scorecards ORDER BY overall_score DESC LIMIT 1"
        ).fetchone()
        bottom = conn.execute(
            "SELECT carrier_name, overall_score FROM carrier_scorecards WHERE total_shipments > 2 ORDER BY overall_score ASC LIMIT 1"
        ).fetchone()
        return {
            "total_carriers": total_carriers,
            "avg_otd": round(avg_otd, 1),
            "top_carrier": dict(top) if top else None,
            "bottom_carrier": dict(bottom) if bottom else None,
        }
    finally:
        conn.close()
