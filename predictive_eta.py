"""
predictive_eta.py
-----------------
SQLite-backed predictive ETA helpers for vessel schedules.
Run:
  python predictive_eta.py --seed
  python predictive_eta.py --compute
  python predictive_eta.py --test
"""

import argparse
import math
import os
import random
import re
import sqlite3
from datetime import datetime, timedelta
from statistics import mean, median

from config import DB_PATH


_DB_READY = False
_DELAY_PROFILES = {
    "maersk": (12, 18),
    "cma cgm": (12, 18),
    "hapag-lloyd": (12, 18),
    "msc": (18, 24),
    "cosco": (18, 24),
    "evergreen": (18, 24),
    "zim": (24, 30),
    "pil": (24, 30),
    "whl": (24, 30),
    "wan hai": (24, 30),
}


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _parse_datetime(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d") + timedelta(hours=12)
    except ValueError:
        return None


def _format_datetime_like_input(value, dt_value):
    text = str(value or "").strip()
    if len(text) > 10 and ":" in text:
        return dt_value.strftime("%Y-%m-%d %H:%M:%S")
    return dt_value.strftime("%Y-%m-%d")


def _to_hours(delta):
    return round(delta.total_seconds() / 3600.0, 2)


def _percentile(values, percentile_value):
    if not values:
        return 0.0
    if len(values) == 1:
        return round(float(values[0]), 2)

    ordered = sorted(float(v) for v in values)
    rank = (len(ordered) - 1) * percentile_value
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return round(ordered[low], 2)
    fraction = rank - low
    return round(ordered[low] + (ordered[high] - ordered[low]) * fraction, 2)


def _build_metrics(delay_hours):
    if not delay_hours:
        return None

    ordered = sorted(float(v) for v in delay_hours)
    sample_count = len(ordered)
    on_time_count = sum(1 for value in ordered if abs(value) <= 24)
    return {
        "sample_count": sample_count,
        "avg_delay_hours": round(mean(ordered), 2),
        "median_delay_hours": round(median(ordered), 2),
        "p90_delay_hours": _percentile(ordered, 0.90),
        "on_time_pct": round((on_time_count / sample_count) * 100, 2),
        "min_delay_hours": round(ordered[0], 2),
    }


def _confidence_for_sample_count(sample_count):
    if sample_count >= 10:
        return "high"
    if sample_count >= 5:
        return "medium"
    if sample_count >= 3:
        return "low"
    return "none"


def _fetch_delay_hours(conn, carrier=None, origin=None, destination=None):
    cutoff = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    sql = [
        "SELECT delay_hours FROM voyage_actuals",
        "WHERE delay_hours IS NOT NULL",
        "AND actual_eta IS NOT NULL",
        "AND substr(COALESCE(actual_eta, scheduled_eta), 1, 10) >= ?",
    ]
    params = [cutoff]

    if carrier:
        sql.append("AND carrier = ?")
        params.append(carrier)
    if origin:
        sql.append("AND origin = ?")
        params.append(origin)
    if destination:
        sql.append("AND destination = ?")
        params.append(destination)

    rows = conn.execute(" ".join(sql), params).fetchall()
    return [float(row["delay_hours"]) for row in rows if row["delay_hours"] is not None]


def _default_prediction(scheduled_eta):
    return {
        "predicted_eta": scheduled_eta,
        "scheduled_eta": scheduled_eta,
        "delay_hours": 0.0,
        "delay_range_hours": [0.0, 0.0],
        "confidence": "none",
        "on_time_pct": None,
        "sample_count": 0,
        "match_level": "none",
    }


def _build_prediction_from_metrics(scheduled_eta, metrics, match_level):
    prediction = _default_prediction(scheduled_eta)
    if not metrics or metrics["sample_count"] < 3:
        return prediction

    scheduled_dt = _parse_datetime(scheduled_eta)
    if scheduled_dt is None:
        return prediction

    adjusted_dt = scheduled_dt + timedelta(hours=metrics["avg_delay_hours"])
    prediction.update({
        "predicted_eta": _format_datetime_like_input(scheduled_eta, adjusted_dt),
        "delay_hours": round(metrics["avg_delay_hours"], 2),
        "delay_range_hours": [
            round(metrics["min_delay_hours"], 2),
            round(metrics["p90_delay_hours"], 2),
        ],
        "confidence": _confidence_for_sample_count(metrics["sample_count"]),
        "on_time_pct": round(metrics["on_time_pct"], 2),
        "sample_count": int(metrics["sample_count"]),
        "match_level": match_level,
    })
    return prediction


def _carrier_profile(carrier):
    name = (carrier or "").strip().lower()
    return _DELAY_PROFILES.get(name, (24, 30))


def _parse_transit_hours(value):
    text = str(value or "").strip().lower()
    if not text:
        return None

    days_match = re.search(r"(-?\d+(?:\.\d+)?)\s*d", text)
    hours_match = re.search(r"(-?\d+(?:\.\d+)?)\s*h", text)
    if days_match or hours_match:
        days = float(days_match.group(1)) if days_match else 0.0
        hours = float(hours_match.group(1)) if hours_match else 0.0
        return days * 24 + hours

    digits = re.findall(r"-?\d+(?:\.\d+)?", text)
    if not digits:
        return None
    return float(digits[0]) * 24


def _compute_seed_actual_eta(scheduled_eta, etd, transit_time, delay_hours):
    scheduled_dt = _parse_datetime(scheduled_eta)
    if scheduled_dt is None:
        etd_dt = _parse_datetime(etd)
        transit_hours = _parse_transit_hours(transit_time)
        if etd_dt is None or transit_hours is None:
            return None, None
        scheduled_dt = etd_dt + timedelta(hours=transit_hours)
        scheduled_eta = scheduled_dt.strftime("%Y-%m-%d")

    actual_dt = scheduled_dt + timedelta(hours=delay_hours)
    return scheduled_eta, _format_datetime_like_input(scheduled_eta, actual_dt)


def _record_actual_arrival_with_connection(conn, carrier, origin, destination,
                                           vessel_name, service, scheduled_etd,
                                           scheduled_eta, actual_eta, source):
    scheduled_dt = _parse_datetime(scheduled_eta)
    actual_dt = _parse_datetime(actual_eta)
    if scheduled_dt is None or actual_dt is None:
        raise ValueError("scheduled_eta and actual_eta must be ISO-like dates")

    delay_hours = _to_hours(actual_dt - scheduled_dt)
    conn.execute(
        """
        INSERT INTO voyage_actuals
            (carrier, origin, destination, vessel_name, service,
             scheduled_etd, scheduled_eta, actual_eta, delay_hours, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(carrier, origin, destination, vessel_name, scheduled_etd)
        DO UPDATE SET
            service = excluded.service,
            scheduled_eta = excluded.scheduled_eta,
            actual_eta = excluded.actual_eta,
            delay_hours = excluded.delay_hours,
            source = excluded.source,
            recorded_at = datetime('now')
        """,
        (
            (carrier or "").strip(),
            (origin or "").strip(),
            (destination or "").strip(),
            (vessel_name or "").strip(),
            (service or "").strip(),
            (scheduled_etd or "").strip(),
            (scheduled_eta or "").strip(),
            (actual_eta or "").strip(),
            delay_hours,
            (source or "manual").strip() or "manual",
        ),
    )
    return delay_hours


def _exact_metrics(conn, carrier, origin, destination):
    row = conn.execute(
        """
        SELECT sample_count, avg_delay_hours, median_delay_hours,
               p90_delay_hours, on_time_pct
        FROM delay_stats
        WHERE carrier = ? AND origin = ? AND destination = ?
        """,
        ((carrier or "").strip(), (origin or "").strip(), (destination or "").strip()),
    ).fetchone()
    if not row:
        return None

    min_delay_hours = _fetch_delay_hours(
        conn,
        carrier=(carrier or "").strip(),
        origin=(origin or "").strip(),
        destination=(destination or "").strip(),
    )
    return {
        "sample_count": int(row["sample_count"] or 0),
        "avg_delay_hours": float(row["avg_delay_hours"] or 0.0),
        "median_delay_hours": float(row["median_delay_hours"] or 0.0),
        "p90_delay_hours": float(row["p90_delay_hours"] or 0.0),
        "on_time_pct": float(row["on_time_pct"] or 0.0),
        "min_delay_hours": min(min_delay_hours) if min_delay_hours else 0.0,
    }


def _prediction_with_connection(conn, carrier, origin, destination, scheduled_eta):
    exact = _exact_metrics(conn, carrier, origin, destination)
    if exact and exact["sample_count"] >= 3:
        return _build_prediction_from_metrics(scheduled_eta, exact, "exact")

    fallback_carrier_dest = _build_metrics(
        _fetch_delay_hours(
            conn,
            carrier=(carrier or "").strip(),
            destination=(destination or "").strip(),
        )
    )
    if fallback_carrier_dest and fallback_carrier_dest["sample_count"] >= 3:
        return _build_prediction_from_metrics(scheduled_eta, fallback_carrier_dest, "carrier_dest")

    fallback_dest_only = _build_metrics(
        _fetch_delay_hours(conn, destination=(destination or "").strip())
    )
    if fallback_dest_only and fallback_dest_only["sample_count"] >= 3:
        return _build_prediction_from_metrics(scheduled_eta, fallback_dest_only, "dest_only")

    return _default_prediction(scheduled_eta)


def init_predictive_db():
    """Create voyage_actuals and delay_stats tables if they don't exist."""
    global _DB_READY
    if _DB_READY:
        return

    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS voyage_actuals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier         TEXT NOT NULL,
            origin          TEXT NOT NULL,
            destination     TEXT NOT NULL,
            vessel_name     TEXT,
            service         TEXT,
            scheduled_etd   TEXT NOT NULL,
            scheduled_eta   TEXT NOT NULL,
            actual_eta      TEXT,
            delay_hours     REAL,
            recorded_at     TEXT DEFAULT (datetime('now')),
            source          TEXT DEFAULT 'manual',
            UNIQUE(carrier, origin, destination, vessel_name, scheduled_etd)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS delay_stats (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier             TEXT NOT NULL,
            origin              TEXT NOT NULL,
            destination         TEXT NOT NULL,
            sample_count        INTEGER DEFAULT 0,
            avg_delay_hours     REAL DEFAULT 0,
            median_delay_hours  REAL DEFAULT 0,
            p90_delay_hours     REAL DEFAULT 0,
            on_time_pct         REAL DEFAULT 0,
            last_computed       TEXT DEFAULT (datetime('now')),
            UNIQUE(carrier, origin, destination)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_voyage_actuals_lookup "
        "ON voyage_actuals(carrier, origin, destination, scheduled_etd)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_voyage_actuals_destination "
        "ON voyage_actuals(destination, carrier)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_delay_stats_lookup "
        "ON delay_stats(carrier, origin, destination)"
    )
    conn.commit()
    conn.close()
    _DB_READY = True


def record_actual_arrival(carrier, origin, destination, vessel_name,
                          scheduled_etd, scheduled_eta, actual_eta, source='manual'):
    """Record an actual arrival for a completed voyage. Calculates delay_hours automatically."""
    init_predictive_db()
    conn = _connect()
    delay_hours = _record_actual_arrival_with_connection(
        conn,
        carrier,
        origin,
        destination,
        vessel_name,
        "",
        scheduled_etd,
        scheduled_eta,
        actual_eta,
        source,
    )
    conn.commit()
    conn.close()
    return delay_hours


def compute_delay_stats():
    """Recompute delay_stats table from all voyage_actuals data."""
    init_predictive_db()
    conn = _connect()
    rows = conn.execute(
        """
        SELECT carrier, origin, destination, delay_hours, actual_eta, scheduled_eta
        FROM voyage_actuals
        WHERE actual_eta IS NOT NULL AND delay_hours IS NOT NULL
        """
    ).fetchall()

    cutoff = datetime.now() - timedelta(days=180)
    grouped = {}
    for row in rows:
        anchor_dt = _parse_datetime(row["actual_eta"]) or _parse_datetime(row["scheduled_eta"])
        if anchor_dt is None or anchor_dt < cutoff:
            continue
        key = (row["carrier"], row["origin"], row["destination"])
        grouped.setdefault(key, []).append(float(row["delay_hours"]))

    conn.execute("DELETE FROM delay_stats")
    inserted = 0
    for (carrier, origin, destination), delays in grouped.items():
        metrics = _build_metrics(delays)
        if not metrics:
            continue
        conn.execute(
            """
            INSERT INTO delay_stats
                (carrier, origin, destination, sample_count, avg_delay_hours,
                 median_delay_hours, p90_delay_hours, on_time_pct, last_computed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                carrier,
                origin,
                destination,
                metrics["sample_count"],
                metrics["avg_delay_hours"],
                metrics["median_delay_hours"],
                metrics["p90_delay_hours"],
                metrics["on_time_pct"],
            ),
        )
        inserted += 1

    conn.commit()
    conn.close()

    try:
        from reliability import compute_reliability_scores
        compute_reliability_scores()
    except ImportError:
        pass

    return inserted


def get_predicted_eta(carrier, origin, destination, scheduled_eta):
    """Return a predicted ETA dict for a single sailing."""
    init_predictive_db()
    conn = _connect()
    prediction = _prediction_with_connection(conn, carrier, origin, destination, scheduled_eta)
    conn.close()
    return prediction


def enrich_schedules_with_predictions(rows):
    """Take a list of schedule row dicts and add prediction fields to each."""
    init_predictive_db()
    if not rows:
        return rows

    conn = _connect()
    cache = {}
    now = datetime.now()

    for row in rows:
        row["predicted_eta"] = None
        row["delay_hours"] = None
        row["delay_confidence"] = "none"
        row["on_time_pct"] = None
        row["match_level"] = "none"
        row["sample_count"] = 0
        row["delay_range_hours"] = None

        eta_dt = _parse_datetime(row.get("eta"))
        if eta_dt is None or eta_dt <= now:
            continue

        key = (
            (row.get("carrier") or "").strip(),
            (row.get("origin") or "").strip(),
            (row.get("destination") or "").strip(),
            (row.get("eta") or "").strip(),
        )
        if key not in cache:
            cache[key] = _prediction_with_connection(conn, *key)

        prediction = cache[key]
        row.update(prediction)
        row["delay_confidence"] = prediction.get("confidence", "none")

    conn.close()
    return rows


def seed_historical_delays():
    """Seed the voyage_actuals table with synthetic delay data derived from vessel_schedules."""
    init_predictive_db()
    conn = _connect()
    existing = conn.execute("SELECT COUNT(*) FROM voyage_actuals").fetchone()[0]
    if existing > 100:
        conn.close()
        return 0

    random.seed(42)
    today = datetime.now().strftime("%Y-%m-%d")
    schedules = conn.execute(
        """
        SELECT carrier, origin, destination, vessel_name, service, etd, eta, transit_time
        FROM vessel_schedules
        WHERE etd IS NOT NULL AND etd != '' AND substr(etd, 1, 10) < ?
        ORDER BY etd ASC
        """,
        (today,),
    ).fetchall()

    inserted = 0
    for row in schedules:
        mean_hours, stddev_hours = _carrier_profile(row["carrier"])
        delay_hours = max(-24.0, min(120.0, random.gauss(mean_hours, stddev_hours)))
        delay_hours = round(delay_hours, 2)
        scheduled_eta, actual_eta = _compute_seed_actual_eta(
            row["eta"],
            row["etd"],
            row["transit_time"],
            delay_hours,
        )
        if not scheduled_eta or not actual_eta:
            continue

        existing_row = conn.execute(
            """
            SELECT 1
            FROM voyage_actuals
            WHERE carrier = ?
              AND origin = ?
              AND destination = ?
              AND vessel_name = ?
              AND scheduled_etd = ?
            LIMIT 1
            """,
            (
                row["carrier"],
                row["origin"],
                row["destination"],
                row["vessel_name"],
                row["etd"],
            ),
        ).fetchone()
        if existing_row:
            continue

        before = conn.total_changes
        _record_actual_arrival_with_connection(
            conn,
            row["carrier"],
            row["origin"],
            row["destination"],
            row["vessel_name"],
            row["service"],
            row["etd"],
            scheduled_eta,
            actual_eta,
            "synthetic_seed",
        )
        if conn.total_changes > before:
            inserted += 1

    conn.commit()
    conn.close()
    return inserted


def _print_test_predictions():
    init_predictive_db()
    conn = _connect()
    rows = conn.execute(
        """
        SELECT carrier, origin, destination, vessel_name, eta
        FROM vessel_schedules
        WHERE eta IS NOT NULL AND eta != ''
          AND substr(eta, 1, 10) >= ?
        ORDER BY eta ASC
        LIMIT 100
        """
    , (datetime.now().strftime("%Y-%m-%d"),)).fetchall()
    conn.close()

    if not rows:
        print("No vessel schedules found.")
        return

    predictions = []
    for row in rows:
        prediction = get_predicted_eta(
            row["carrier"],
            row["origin"],
            row["destination"],
            row["eta"],
        )
        predictions.append((row, prediction))

    predictions.sort(
        key=lambda item: (
            item[1]["sample_count"],
            item[1]["confidence"] == "high",
            item[1]["confidence"] == "medium",
            item[1]["confidence"] == "low",
        ),
        reverse=True,
    )

    for row, prediction in predictions[:5]:
        print(
            f"{row['carrier']} | {row['origin']} -> {row['destination']} | "
            f"{row['vessel_name'] or 'Unknown vessel'} | "
            f"scheduled {prediction['scheduled_eta']} | "
            f"predicted {prediction['predicted_eta']} | "
            f"confidence={prediction['confidence']} | "
            f"samples={prediction['sample_count']} | "
            f"match={prediction['match_level']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Predictive ETA utilities")
    parser.add_argument("--seed", action="store_true", help="Seed voyage_actuals with synthetic delay history")
    parser.add_argument("--compute", action="store_true", help="Recompute delay_stats from voyage_actuals")
    parser.add_argument("--test", action="store_true", help="Print sample ETA predictions")
    args = parser.parse_args()

    init_predictive_db()

    if args.seed:
        inserted = seed_historical_delays()
        print(f"Seeded {inserted} voyage actuals.")
    if args.compute:
        count = compute_delay_stats()
        print(f"Computed {count} delay stat rows.")
    if args.test:
        _print_test_predictions()
    if not (args.seed or args.compute or args.test):
        parser.print_help()


if __name__ == "__main__":
    main()
