"""
record_arrivals.py
------------------
Utility helpers for recording actual vessel arrivals into voyage_actuals.
Run:
  python record_arrivals.py --csv arrivals.csv
  python record_arrivals.py --id 1234 --actual-eta 2026-04-19
"""

import argparse
import csv
import os

from database import get_db
from predictive_eta import (
    compute_delay_stats,
    init_predictive_db,
    record_actual_arrival,
    _record_actual_arrival_with_connection,
)


def record_from_csv(csv_path):
    """Import actual arrival data from a CSV."""
    init_predictive_db()
    if not os.path.exists(csv_path):
        raise FileNotFoundError(csv_path)

    required = {
        "carrier",
        "origin",
        "destination",
        "vessel_name",
        "scheduled_etd",
        "scheduled_eta",
        "actual_eta",
    }

    inserted = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = sorted(required - headers)
        if missing:
            raise ValueError("Missing CSV columns: " + ", ".join(missing))

        for row in reader:
            record_actual_arrival(
                row.get("carrier", ""),
                row.get("origin", ""),
                row.get("destination", ""),
                row.get("vessel_name", ""),
                row.get("scheduled_etd", ""),
                row.get("scheduled_eta", ""),
                row.get("actual_eta", ""),
                source="csv_import",
            )
            inserted += 1

    compute_delay_stats()
    return inserted


def mark_arrived(schedule_id, actual_eta):
    """Mark a specific vessel_schedules row as arrived."""
    init_predictive_db()
    conn = get_db()
    row = conn.execute(
        """
        SELECT id, carrier, origin, destination, vessel_name, service, etd, eta
        FROM vessel_schedules
        WHERE id = ?
        """,
        (schedule_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Schedule id {schedule_id} not found")

    delay_hours = _record_actual_arrival_with_connection(
        conn,
        row["carrier"],
        row["origin"],
        row["destination"],
        row["vessel_name"],
        row["service"],
        row["etd"],
        row["eta"],
        actual_eta,
        "manual",
    )
    conn.commit()
    conn.close()
    compute_delay_stats()
    return {
        "schedule_id": int(row["id"]),
        "carrier": row["carrier"],
        "origin": row["origin"],
        "destination": row["destination"],
        "vessel_name": row["vessel_name"],
        "scheduled_eta": row["eta"],
        "actual_eta": actual_eta,
        "delay_hours": delay_hours,
    }


def main():
    parser = argparse.ArgumentParser(description="Record actual vessel arrivals")
    parser.add_argument("--csv", help="CSV file containing actual arrival records")
    parser.add_argument("--id", type=int, help="vessel_schedules id to mark arrived")
    parser.add_argument("--actual-eta", dest="actual_eta", help="Actual ETA in YYYY-MM-DD or ISO format")
    args = parser.parse_args()

    if args.csv:
        inserted = record_from_csv(args.csv)
        print(f"Imported {inserted} actual arrival rows.")
        return

    if args.id and args.actual_eta:
        result = mark_arrived(args.id, args.actual_eta)
        print(
            f"Recorded arrival for schedule {result['schedule_id']} "
            f"({result['carrier']} {result['origin']} -> {result['destination']}) "
            f"with delay {result['delay_hours']} hours."
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
