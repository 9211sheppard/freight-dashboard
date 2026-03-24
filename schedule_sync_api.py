"""
schedule_sync_api.py
--------------------
Syncs vessel schedules from carrier APIs into the shared SQLite database.
It keeps the CSV fallback intact while adding API-backed rows, schema
migrations, and a simple background runner for manual or daemon syncs.
"""

import argparse
import logging
import os
import threading
import time
from datetime import datetime, timedelta

from config import DB_PATH, SCHEDULE_SYNC_INTERVAL_HOURS, SCHEDULE_SYNC_DAYS_AHEAD
from database import get_db
from carrier_api import (
    ORIGIN_PORTS,
    DEST_PORTS,
    PORT_LOCODES,
    fetch_schedules,
    has_any_api_keys_configured,
)


log = logging.getLogger(__name__)

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


_sync_lock = threading.Lock()
SYNC_PORT_LIMIT = 3
MAX_PORT_PAIRS_PER_LANE = 5


def ensure_schedule_schema():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vessel_schedules (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                lane          TEXT,
                carrier       TEXT,
                origin        TEXT,
                destination   TEXT,
                vessel_name   TEXT,
                service       TEXT,
                etd           TEXT,
                eta           TEXT,
                transit_time  TEXT,
                imported_at   TEXT DEFAULT (datetime('now')),
                source_file   TEXT,
                data_source   TEXT DEFAULT 'csv',
                last_checked  TEXT,
                UNIQUE(carrier, origin, destination, vessel_name, etd)
            )
            """
        )

        from database import _get_existing_columns
        existing = _get_existing_columns(conn, "vessel_schedules")
        for col, definition in [
            ("source_file", "TEXT"),
            ("imported_at", "TEXT DEFAULT (datetime('now'))"),
            ("data_source", "TEXT DEFAULT 'csv'"),
            ("last_checked", "TEXT"),
        ]:
            if col not in existing:
                conn.execute("ALTER TABLE vessel_schedules ADD COLUMN %s %s" % (col, definition))

        conn.commit()
    finally:
        conn.close()


def _region_lane_name(origin_region, dest_region):
    return "%s to %s" % (origin_region, dest_region)


def _priority_ports(region_ports):
    return [p for p in region_ports[:SYNC_PORT_LIMIT] if p in PORT_LOCODES]


def _iter_ranked_port_pairs(origin_ports, dest_ports):
    pairs = []
    seen = set()
    max_rank = max(len(origin_ports), len(dest_ports))
    for rank in range(max_rank * 2):
        for origin_index, origin_name in enumerate(origin_ports):
            for dest_index, dest_name in enumerate(dest_ports):
                if origin_index + dest_index != rank:
                    continue
                pair = (origin_name, dest_name)
                if pair in seen:
                    continue
                seen.add(pair)
                pairs.append(pair)
                if len(pairs) >= MAX_PORT_PAIRS_PER_LANE:
                    return pairs
    return pairs


def _row_exists(conn, row):
    existing = conn.execute(
        """
        SELECT id FROM vessel_schedules
        WHERE carrier=? AND origin=? AND destination=? AND vessel_name=? AND etd=?
        """,
        (
            row.get("carrier", ""),
            row.get("origin", ""),
            row.get("destination", ""),
            row.get("vessel_name", ""),
            row.get("etd", ""),
        ),
    ).fetchone()
    return bool(existing)


def _upsert_schedule(conn, lane_name, row, checked_at):
    existed = _row_exists(conn, row)
    conn.execute(
        """
        INSERT OR REPLACE INTO vessel_schedules
            (lane, carrier, origin, destination, vessel_name, service,
             etd, eta, transit_time, imported_at, source_file, data_source, last_checked)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, 'api', ?)
        """,
        (
            lane_name,
            row.get("carrier", ""),
            row.get("origin", ""),
            row.get("destination", ""),
            row.get("vessel_name", ""),
            row.get("service", ""),
            row.get("etd", ""),
            row.get("eta", ""),
            row.get("transit_time", ""),
            row.get("source", "api"),
            checked_at,
        ),
    )
    return existed


def sync_lane(origin_region, dest_region):
    ensure_schedule_schema()

    if origin_region not in ORIGIN_PORTS:
        raise ValueError("Unknown origin region: %s" % origin_region)
    if dest_region not in DEST_PORTS:
        raise ValueError("Unknown destination region: %s" % dest_region)

    if not has_any_api_keys_configured():
        log.warning("No carrier API keys configured — running in CSV-only mode")
        return {
            "lane": _region_lane_name(origin_region, dest_region),
            "port_pairs": 0,
            "records_added": 0,
            "records_replaced": 0,
            "carrier_errors": {},
            "records_seen": 0,
        }

    lane_name = _region_lane_name(origin_region, dest_region)
    checked_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    start_date = datetime.utcnow().strftime("%Y-%m-%d")
    end_date = (datetime.utcnow() + timedelta(days=SCHEDULE_SYNC_DAYS_AHEAD)).strftime("%Y-%m-%d")

    origin_ports = _priority_ports(ORIGIN_PORTS[origin_region])
    dest_ports = _priority_ports(DEST_PORTS[dest_region])
    port_pairs = _iter_ranked_port_pairs(origin_ports, dest_ports)

    if not port_pairs:
        return {
            "lane": lane_name,
            "port_pairs": 0,
            "records_added": 0,
            "records_replaced": 0,
            "carrier_errors": {},
            "records_seen": 0,
        }

    conn = get_db()
    records_added = 0
    records_replaced = 0
    records_seen = 0
    carrier_errors = {}
    seen_keys = set()

    try:
        for origin_name, dest_name in port_pairs:
            origin_locode = PORT_LOCODES.get(origin_name)
            dest_locode = PORT_LOCODES.get(dest_name)
            if not origin_locode or not dest_locode:
                continue

            try:
                rows = fetch_schedules(origin_locode, dest_locode, start_date, end_date)
            except Exception as exc:
                carrier_errors["lane_fetch"] = carrier_errors.get("lane_fetch", 0) + 1
                log.warning("[%s] %s", lane_name, exc)
                continue

            for row in rows:
                key = (
                    row.get("carrier", ""),
                    row.get("origin", ""),
                    row.get("destination", ""),
                    row.get("vessel_name", ""),
                    row.get("etd", ""),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                records_seen += 1
                replaced = _upsert_schedule(conn, lane_name, row, checked_at)
                if replaced:
                    records_replaced += 1
                else:
                    records_added += 1

        conn.execute(
            "UPDATE vessel_schedules SET last_checked=? WHERE lane=? AND data_source='api'",
            (checked_at, lane_name),
        )
        conn.commit()
    finally:
        conn.close()

    log.info(
        "[sync] %s | pairs=%s added=%s replaced=%s seen=%s",
        lane_name,
        len(port_pairs),
        records_added,
        records_replaced,
        records_seen,
    )

    return {
        "lane": lane_name,
        "port_pairs": len(port_pairs),
        "records_added": records_added,
        "records_replaced": records_replaced,
        "carrier_errors": carrier_errors,
        "records_seen": records_seen,
    }


def sync_all_lanes():
    """For each origin-destination region pair that has port mappings,
    fetch schedules from carrier APIs and upsert into vessel_schedules table."""
    ensure_schedule_schema()

    summary = {
        "lanes_synced": 0,
        "records_added": 0,
        "records_replaced": 0,
        "carrier_errors": {},
        "records_seen": 0,
        "api_enabled": has_any_api_keys_configured(),
    }

    if not summary["api_enabled"]:
        log.warning("No carrier API keys configured — running in CSV-only mode")
        return summary

    for origin_region in ORIGIN_PORTS:
        for dest_region in DEST_PORTS:
            lane_result = sync_lane(origin_region, dest_region)
            summary["lanes_synced"] += 1
            summary["records_added"] += lane_result["records_added"]
            summary["records_replaced"] += lane_result["records_replaced"]
            summary["records_seen"] += lane_result["records_seen"]
            for carrier_name, count in lane_result["carrier_errors"].items():
                summary["carrier_errors"][carrier_name] = summary["carrier_errors"].get(carrier_name, 0) + count

    log.info(
        "[sync] complete | lanes=%s added=%s replaced=%s seen=%s errors=%s",
        summary["lanes_synced"],
        summary["records_added"],
        summary["records_replaced"],
        summary["records_seen"],
        summary["carrier_errors"],
    )
    return summary


def _run_sync_job(origin_region=None, dest_region=None):
    if not _sync_lock.acquire(False):
        log.info("[sync] schedule sync already in progress")
        return
    try:
        ensure_schedule_schema()
        if origin_region and dest_region:
            sync_lane(origin_region, dest_region)
        else:
            sync_all_lanes()
    finally:
        _sync_lock.release()


def start_background_sync(origin_region=None, dest_region=None):
    thread = threading.Thread(
        target=_run_sync_job,
        kwargs={"origin_region": origin_region, "dest_region": dest_region},
        daemon=True,
    )
    thread.start()
    return thread


def _run_daemon(origin_region=None, dest_region=None):
    interval_seconds = max(1, SCHEDULE_SYNC_INTERVAL_HOURS) * 3600
    while True:
        _run_sync_job(origin_region=origin_region, dest_region=dest_region)
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Sync vessel schedules from carrier APIs")
    parser.add_argument("--daemon", action="store_true", help="Run continuously on the configured interval")
    parser.add_argument("--lane", nargs=2, metavar=("ORIGIN_REGION", "DEST_REGION"), help="Sync one region pair only")
    args = parser.parse_args()

    ensure_schedule_schema()

    if args.lane:
        origin_region, dest_region = args.lane
    else:
        origin_region = None
        dest_region = None

    if args.daemon:
        _run_daemon(origin_region=origin_region, dest_region=dest_region)
        return

    if origin_region and dest_region:
        result = sync_lane(origin_region, dest_region)
    else:
        result = sync_all_lanes()
    print(result)


if __name__ == "__main__":
    main()
