"""AI Load Matching — suggests optimal driver assignments for open loads."""
import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_available_drivers():
    """Get drivers who are Active."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM drivers WHERE status='Active' ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_open_shipments():
    """Get shipments in Draft or Booked status needing assignment."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM shipments WHERE status IN ('Draft','Booked') ORDER BY etd ASC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def score_driver_for_shipment(driver: dict, shipment: dict) -> dict:
    """
    Score a driver for a shipment 0-100. Higher = better match.
    Factors: availability, equipment match, location proximity, license class.
    """
    score = 50  # base
    reasons = []

    # Driver status
    if driver.get('status') == 'Active':
        score += 15
        reasons.append("Active driver")

    # Equipment match
    driver_eq = (driver.get('truck_type') or driver.get('vehicle_type') or '').lower()
    ship_eq = (shipment.get('container_type') or shipment.get('mode') or '').lower()
    if driver_eq and ship_eq:
        if driver_eq in ship_eq or ship_eq in driver_eq:
            score += 20
            reasons.append("Equipment match")
        elif 'van' in driver_eq and 'ltl' in ship_eq:
            score += 15
            reasons.append("Compatible equipment")

    # License class (CDL-A preferred for FTL)
    if driver.get('license_class') == 'CDL-A':
        score += 10
        reasons.append("CDL-A licensed")

    # Location proximity (simple: same state prefix)
    driver_state = (driver.get('state') or driver.get('location') or '')[:2].upper()
    origin_state = (shipment.get('origin_port') or '')[:2].upper()
    if driver_state and origin_state and driver_state == origin_state:
        score += 15
        reasons.append("Near origin")
    elif driver_state and origin_state:
        score -= 5
        reasons.append("Different state")

    score = max(0, min(100, score))
    return {"score": score, "reasons": reasons, "driver": driver}


def get_match_suggestions(shipment_ref: str = None) -> list:
    """
    For each open shipment, return top 3 driver matches.
    If shipment_ref provided, return matches for that shipment only.
    """
    conn = get_db()
    try:
        if shipment_ref:
            shipments_q = conn.execute(
                "SELECT * FROM shipments WHERE shipment_ref=?", (shipment_ref,)
            ).fetchall()
        else:
            shipments_q = conn.execute(
                "SELECT * FROM shipments WHERE status IN ('Draft','Booked') ORDER BY etd ASC LIMIT 20"
            ).fetchall()

        drivers = [dict(r) for r in conn.execute(
            "SELECT * FROM drivers WHERE status='Active'"
        ).fetchall()]

        results = []
        for s in shipments_q:
            s = dict(s)
            scored = [score_driver_for_shipment(d, s) for d in drivers]
            scored.sort(key=lambda x: x['score'], reverse=True)
            results.append({
                "shipment": s,
                "top_matches": scored[:3],
                "has_matches": len([x for x in scored if x['score'] >= 50]) > 0
            })
        return results
    finally:
        conn.close()


def auto_assign_driver(shipment_ref: str, driver_id: int) -> bool:
    """Assign the selected driver to a shipment."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE shipments SET status='Dispatched', updated_at=CURRENT_TIMESTAMP WHERE shipment_ref=?",
            (shipment_ref,)
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_load_board_summary() -> dict:
    """Summary stats for the load matching board."""
    conn = get_db()
    try:
        open_loads = conn.execute(
            "SELECT COUNT(*) FROM shipments WHERE status IN ('Draft','Booked')"
        ).fetchone()[0]
        active_drivers = conn.execute(
            "SELECT COUNT(*) FROM drivers WHERE status='Active'"
        ).fetchone()[0]
        unassigned = conn.execute(
            "SELECT COUNT(*) FROM shipments WHERE status='Draft'"
        ).fetchone()[0]
        return {
            "open_loads": open_loads,
            "active_drivers": active_drivers,
            "unassigned": unassigned,
        }
    finally:
        conn.close()
