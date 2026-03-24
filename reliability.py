"""
reliability.py
--------------
SQLite-backed vessel schedule reliability scoring helpers.
Run:
  python reliability.py --compute
  python reliability.py --leaderboard
  python reliability.py --carrier Maersk
  python reliability.py --test
"""

import argparse
import math
import os
import sqlite3
from datetime import datetime, timedelta
from statistics import median

from config import DB_PATH
from predictive_eta import init_predictive_db


_DB_READY = False
_PERIODS = {
    "30d": 30,
    "90d": 90,
    "180d": 180,
}
_GRADE_THRESHOLDS = (
    (95, "A+"),
    (90, "A"),
    (85, "B+"),
    (80, "B"),
    (70, "C+"),
    (60, "C"),
    (50, "D"),
)

ORIGIN_PORTS = {
    "China":       ["Shanghai", "Ningbo", "Yantian", "Shenzhen", "Guangzhou", "Qingdao", "Tianjin", "Xiamen", "Dalian", "Lianyungang"],
    "Vietnam":     ["Ho Chi Minh", "Cat Lai", "Cai Mep", "Hai Phong", "Da Nang"],
    "India":       ["Nhava Sheva", "JNPT", "Chennai", "Mundra", "Cochin", "Hazira", "Pipavav", "Kolkata", "Mumbai"],
    "Middle East": ["Jebel Ali", "Dubai", "Dammam", "Sohar", "Salalah", "Jeddah", "Aqaba", "Kuwait", "Muscat"],
    "Europe":      ["Rotterdam", "Hamburg", "Antwerp", "Bremerhaven", "Felixstowe", "Le Havre", "Barcelona", "Genoa", "Valencia", "Piraeus", "Gdansk"],
    "South Korea": ["Busan", "Incheon", "Gwangyang"],
    "Japan":       ["Yokohama", "Tokyo", "Kobe", "Osaka", "Nagoya"],
    "Bangladesh":  ["Chittagong"],
    "Indonesia":   ["Tanjung Priok", "Surabaya", "Belawan"],
    "Malaysia":    ["Port Klang", "Penang", "Tanjung Pelepas"],
    "Thailand":    ["Laem Chabang", "Bangkok"],
    "Brazil":      ["Santos", "Itajai", "Paranagua", "Rio de Janeiro"],
    "Mexico":      ["Manzanillo", "Lazaro Cardenas", "Veracruz", "Altamira"],
}

DEST_PORTS = {
    "USA":             ["Los Angeles", "Long Beach", "Oakland", "Seattle", "Tacoma", "New York", "Newark", "Norfolk", "Savannah", "Charleston", "Houston", "Miami"],
    "Canada":          ["Vancouver", "Prince Rupert", "Montreal", "Halifax"],
    "Europe":          ["Rotterdam", "Hamburg", "Antwerp", "Bremerhaven", "Felixstowe", "Le Havre", "Barcelona", "Genoa", "Valencia", "Piraeus"],
    "Mexico":          ["Manzanillo", "Lazaro Cardenas", "Veracruz", "Altamira"],
    "South America":   ["Santos", "Buenos Aires", "Callao", "Buenaventura", "Cartagena", "Valparaiso", "San Antonio", "Montevideo"],
    "Central America": ["Colon", "Moin", "Puerto Cortes", "Puerto Quetzal", "Acajutla"],
    "Australia/NZ":    ["Sydney", "Melbourne", "Brisbane", "Fremantle", "Adelaide", "Auckland", "Tauranga", "Lyttelton", "Port Botany"],
    "Middle East":     ["Jebel Ali", "Dubai", "Dammam", "Sohar", "Salalah", "Jeddah", "Aqaba"],
    "Africa":          ["Durban", "Mombasa", "Lagos", "Tema", "Dar es Salaam", "Port Elizabeth", "Apapa"],
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


def _build_port_like_clause(ports, column):
    if not ports:
        return None, []

    parts = []
    params = []
    for port in ports:
        parts.append("LOWER({0}) LIKE LOWER(?)".format(column))
        params.append("%{0}%".format(port))
    return "(" + " OR ".join(parts) + ")", params


def _stddev(values):
    if not values:
        return 0.0
    if len(values) == 1:
        return 0.0

    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _grade_for_score(on_time_pct, total_voyages):
    if total_voyages < 3:
        return "N/A"

    for threshold, grade in _GRADE_THRESHOLDS:
        if on_time_pct >= threshold:
            return grade
    return "F"


def _calculate_metrics(delay_values):
    if not delay_values:
        return None

    ordered = sorted(float(value) for value in delay_values)
    total_voyages = len(ordered)
    on_time_count = sum(1 for value in ordered if -24 <= value <= 24)
    late_count = sum(1 for value in ordered if value > 24)
    early_count = sum(1 for value in ordered if value < -6)
    on_time_pct = round((on_time_count / total_voyages) * 100, 2)
    avg_delay_hours = round(sum(ordered) / total_voyages, 2)
    median_delay_hours = round(float(median(ordered)), 2)
    worst_delay_hours = round(max(ordered), 2)
    consistency_score = round(max(0.0, 100.0 - min(_stddev(ordered) * 2.0, 100.0)), 2)

    return {
        "total_voyages": total_voyages,
        "on_time_count": on_time_count,
        "late_count": late_count,
        "early_count": early_count,
        "on_time_pct": on_time_pct,
        "avg_delay_hours": avg_delay_hours,
        "median_delay_hours": median_delay_hours,
        "worst_delay_hours": worst_delay_hours,
        "consistency_score": consistency_score,
        "reliability_grade": _grade_for_score(on_time_pct, total_voyages),
    }


def _period_cutoffs(now):
    return {
        period: now - timedelta(days=days)
        for period, days in _PERIODS.items()
    }


def _anchor_datetime(row):
    actual_dt = _parse_datetime(row["actual_eta"])
    if actual_dt is not None:
        return actual_dt
    return _parse_datetime(row["scheduled_eta"])


def _row_to_dict(row):
    if row is None:
        return None
    data = dict(row)
    if "id" in data and data["id"] is not None:
        data["id"] = int(data["id"])
    for key in ("total_voyages", "on_time_count", "late_count", "early_count"):
        if key in data and data[key] is not None:
            data[key] = int(data[key])
    return data


def _insert_score(conn, carrier, origin, destination, lane, period, metrics):
    conn.execute(
        """
        INSERT OR REPLACE INTO reliability_scores (
            carrier, origin, destination, lane, period,
            total_voyages, on_time_count, late_count, early_count,
            on_time_pct, avg_delay_hours, median_delay_hours,
            worst_delay_hours, consistency_score, reliability_grade, last_computed
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            carrier,
            origin,
            destination,
            lane,
            period,
            metrics["total_voyages"],
            metrics["on_time_count"],
            metrics["late_count"],
            metrics["early_count"],
            metrics["on_time_pct"],
            metrics["avg_delay_hours"],
            metrics["median_delay_hours"],
            metrics["worst_delay_hours"],
            metrics["consistency_score"],
            metrics["reliability_grade"],
        ),
    )


def _print_score_row(prefix, row):
    if not row:
        print(prefix + ": no data")
        return

    if not hasattr(row, "get"):
        row = dict(row)

    print(
        "{0}: grade={1} | on-time={2}% | avg delay={3}h | consistency={4} | voyages={5}".format(
            prefix,
            row.get("reliability_grade") or "N/A",
            round(float(row.get("on_time_pct") or 0), 2),
            round(float(row.get("avg_delay_hours") or 0), 2),
            round(float(row.get("consistency_score") or 0), 2),
            int(row.get("total_voyages") or 0),
        )
    )


def init_reliability_db():
    """Create reliability_scores table if it doesn't exist."""
    global _DB_READY
    if _DB_READY:
        return

    init_predictive_db()
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reliability_scores (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            carrier             TEXT NOT NULL,
            origin              TEXT,
            destination         TEXT,
            lane                TEXT,
            period              TEXT NOT NULL,
            total_voyages       INTEGER DEFAULT 0,
            on_time_count       INTEGER DEFAULT 0,
            late_count          INTEGER DEFAULT 0,
            early_count         INTEGER DEFAULT 0,
            on_time_pct         REAL DEFAULT 0,
            avg_delay_hours     REAL DEFAULT 0,
            median_delay_hours  REAL DEFAULT 0,
            worst_delay_hours   REAL DEFAULT 0,
            consistency_score   REAL DEFAULT 0,
            reliability_grade   TEXT DEFAULT 'N/A',
            last_computed       TEXT DEFAULT (datetime('now')),
            UNIQUE(carrier, origin, destination, period)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reliability_scores_carrier_period "
        "ON reliability_scores(carrier, period)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reliability_scores_pair_period "
        "ON reliability_scores(origin, destination, period)"
    )
    conn.commit()
    conn.close()
    _DB_READY = True


def compute_reliability_scores():
    """Compute reliability scores from voyage_actuals data."""
    init_reliability_db()
    conn = _connect()
    rows = conn.execute(
        """
        SELECT
            va.carrier,
            va.origin,
            va.destination,
            va.vessel_name,
            va.scheduled_etd,
            va.scheduled_eta,
            va.actual_eta,
            va.delay_hours,
            vs.lane
        FROM voyage_actuals va
        LEFT JOIN vessel_schedules vs
          ON vs.carrier = va.carrier
         AND vs.origin = va.origin
         AND vs.destination = va.destination
         AND COALESCE(vs.vessel_name, '') = COALESCE(va.vessel_name, '')
         AND vs.etd = va.scheduled_etd
        WHERE va.actual_eta IS NOT NULL
          AND va.delay_hours IS NOT NULL
        """
    ).fetchall()

    now = datetime.now()
    cutoffs = _period_cutoffs(now)
    grouped = {}

    for row in rows:
        anchor_dt = _anchor_datetime(row)
        if anchor_dt is None:
            continue

        carrier = (row["carrier"] or "").strip()
        origin = (row["origin"] or "").strip()
        destination = (row["destination"] or "").strip()
        lane = (row["lane"] or "").strip() or None
        delay_hours = float(row["delay_hours"])

        if not carrier:
            continue

        for period, cutoff in cutoffs.items():
            if anchor_dt < cutoff:
                continue

            carrier_key = ("carrier", carrier, period)
            carrier_group = grouped.setdefault(
                carrier_key,
                {"carrier": carrier, "origin": None, "destination": None, "lane": None, "period": period, "delays": []},
            )
            carrier_group["delays"].append(delay_hours)

            if lane:
                lane_key = ("lane", carrier, lane, period)
                lane_group = grouped.setdefault(
                    lane_key,
                    {"carrier": carrier, "origin": None, "destination": None, "lane": lane, "period": period, "delays": []},
                )
                lane_group["delays"].append(delay_hours)

            if origin and destination:
                pair_key = ("pair", carrier, origin, destination, period)
                pair_group = grouped.setdefault(
                    pair_key,
                    {"carrier": carrier, "origin": origin, "destination": destination, "lane": lane, "period": period, "delays": []},
                )
                pair_group["delays"].append(delay_hours)
                if not pair_group["lane"] and lane:
                    pair_group["lane"] = lane

    conn.execute("DELETE FROM reliability_scores")

    inserted = 0
    for group in grouped.values():
        metrics = _calculate_metrics(group["delays"])
        if not metrics:
            continue
        _insert_score(
            conn,
            group["carrier"],
            group["origin"],
            group["destination"],
            group["lane"],
            group["period"],
            metrics,
        )
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def get_carrier_reliability(carrier, period='90d'):
    """Get carrier-wide reliability score for a given period."""
    init_reliability_db()
    conn = _connect()
    row = conn.execute(
        """
        SELECT *
        FROM reliability_scores
        WHERE carrier = ?
          AND period = ?
          AND origin IS NULL
          AND destination IS NULL
          AND lane IS NULL
        ORDER BY last_computed DESC
        LIMIT 1
        """,
        ((carrier or "").strip(), (period or "90d").strip()),
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


def get_lane_reliability(carrier, origin, destination, period='90d'):
    """Get port-pair level reliability. Falls back to carrier-wide if no port-pair data."""
    init_reliability_db()
    conn = _connect()
    row = conn.execute(
        """
        SELECT *
        FROM reliability_scores
        WHERE carrier = ?
          AND origin = ?
          AND destination = ?
          AND period = ?
        ORDER BY total_voyages DESC, last_computed DESC
        LIMIT 1
        """,
        (
            (carrier or "").strip(),
            (origin or "").strip(),
            (destination or "").strip(),
            (period or "90d").strip(),
        ),
    ).fetchone()
    conn.close()
    if row:
        return _row_to_dict(row)
    return get_carrier_reliability(carrier, period)


def get_carrier_leaderboard(period='90d', limit=20):
    """Return carrier-wide reliability scores ranked by on_time_pct descending."""
    init_reliability_db()
    conn = _connect()
    rows = conn.execute(
        """
        SELECT carrier, on_time_pct, avg_delay_hours, consistency_score,
               reliability_grade, total_voyages
        FROM reliability_scores
        WHERE period = ?
          AND total_voyages >= 5
          AND origin IS NULL
          AND destination IS NULL
          AND lane IS NULL
        ORDER BY on_time_pct DESC, consistency_score DESC, avg_delay_hours ASC, carrier ASC
        LIMIT ?
        """,
        ((period or "90d").strip(), max(1, int(limit or 20))),
    ).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]


def get_lane_leaderboard(origin_region=None, dest_region=None, period='90d', limit=20):
    """Return per-port-pair reliability scores for a given lane."""
    init_reliability_db()
    sql = [
        "SELECT carrier, origin, destination, lane, on_time_pct, avg_delay_hours,",
        "       consistency_score, reliability_grade, total_voyages",
        "FROM reliability_scores",
        "WHERE period = ?",
        "  AND origin IS NOT NULL",
        "  AND destination IS NOT NULL",
    ]
    params = [(period or "90d").strip()]

    origin_region = (origin_region or "").strip()
    dest_region = (dest_region or "").strip()

    if origin_region:
        if origin_region in ORIGIN_PORTS:
            clause, clause_params = _build_port_like_clause(ORIGIN_PORTS[origin_region], "origin")
            if clause:
                sql.append("AND " + clause)
                params.extend(clause_params)
        else:
            sql.append("AND LOWER(origin) LIKE LOWER(?)")
            params.append("%{0}%".format(origin_region))

    if dest_region:
        if dest_region in DEST_PORTS:
            clause, clause_params = _build_port_like_clause(DEST_PORTS[dest_region], "destination")
            if clause:
                sql.append("AND " + clause)
                params.extend(clause_params)
        else:
            sql.append("AND LOWER(destination) LIKE LOWER(?)")
            params.append("%{0}%".format(dest_region))

    sql.append("ORDER BY on_time_pct DESC, consistency_score DESC, total_voyages DESC, carrier ASC")
    sql.append("LIMIT ?")
    params.append(max(1, int(limit or 20)))

    conn = _connect()
    rows = conn.execute(" ".join(sql), params).fetchall()
    conn.close()
    return [_row_to_dict(row) for row in rows]


def enrich_schedules_with_reliability(rows):
    """Take a list of schedule row dicts and add reliability fields to each row dict."""
    init_reliability_db()
    if not rows:
        return rows

    conn = _connect()
    cache = {}

    for row in rows:
        row["reliability_grade"] = "N/A"
        row["reliability_on_time_pct"] = None
        row["reliability_consistency"] = None
        row["reliability_sample_count"] = None

        key = (
            (row.get("carrier") or "").strip(),
            (row.get("origin") or "").strip(),
            (row.get("destination") or "").strip(),
            "90d",
        )
        if not key[0]:
            continue

        if key not in cache:
            exact_row = conn.execute(
                """
                SELECT reliability_grade, on_time_pct, consistency_score, total_voyages
                FROM reliability_scores
                WHERE carrier = ?
                  AND origin = ?
                  AND destination = ?
                  AND period = ?
                ORDER BY total_voyages DESC, last_computed DESC
                LIMIT 1
                """,
                key,
            ).fetchone()

            if exact_row is None:
                exact_row = conn.execute(
                    """
                    SELECT reliability_grade, on_time_pct, consistency_score, total_voyages
                    FROM reliability_scores
                    WHERE carrier = ?
                      AND period = ?
                      AND origin IS NULL
                      AND destination IS NULL
                      AND lane IS NULL
                    ORDER BY last_computed DESC
                    LIMIT 1
                    """,
                    (key[0], key[3]),
                ).fetchone()

            cache[key] = dict(exact_row) if exact_row else None

        score = cache[key]
        if not score:
            continue

        row["reliability_grade"] = score.get("reliability_grade") or "N/A"
        row["reliability_on_time_pct"] = float(score["on_time_pct"]) if score.get("on_time_pct") is not None else None
        row["reliability_consistency"] = float(score["consistency_score"]) if score.get("consistency_score") is not None else None
        row["reliability_sample_count"] = int(score["total_voyages"]) if score.get("total_voyages") is not None else None

    conn.close()
    return rows


def _print_leaderboard(period):
    rows = get_carrier_leaderboard(period, 20)
    if not rows:
        print("No carrier reliability data found.")
        return

    print("Carrier leaderboard ({0})".format(period))
    for index, row in enumerate(rows, start=1):
        print(
            "{0:>2}. {1:<18} {2:<2}  on-time={3:>6}%  avg delay={4:>6}h  consistency={5:>6}  voyages={6}".format(
                index,
                row["carrier"][:18],
                row["reliability_grade"],
                round(float(row["on_time_pct"] or 0), 2),
                round(float(row["avg_delay_hours"] or 0), 2),
                round(float(row["consistency_score"] or 0), 2),
                int(row["total_voyages"] or 0),
            )
        )


def _print_carrier_details(carrier):
    init_reliability_db()
    conn = _connect()

    print("Carrier reliability: {0}".format(carrier))
    for period in ("30d", "90d", "180d"):
        _print_score_row(period, get_carrier_reliability(carrier, period))

    lane_rows = conn.execute(
        """
        SELECT lane, period, reliability_grade, on_time_pct,
               avg_delay_hours, consistency_score, total_voyages
        FROM reliability_scores
        WHERE carrier = ?
          AND lane IS NOT NULL
          AND origin IS NULL
          AND destination IS NULL
        ORDER BY
            CASE period WHEN '30d' THEN 1 WHEN '90d' THEN 2 WHEN '180d' THEN 3 ELSE 4 END,
            on_time_pct DESC,
            total_voyages DESC,
            lane ASC
        """,
        ((carrier or "").strip(),),
    ).fetchall()

    pair_rows = conn.execute(
        """
        SELECT origin, destination, lane, period, reliability_grade, on_time_pct,
               avg_delay_hours, consistency_score, total_voyages
        FROM reliability_scores
        WHERE carrier = ?
          AND origin IS NOT NULL
          AND destination IS NOT NULL
        ORDER BY
            CASE period WHEN '30d' THEN 1 WHEN '90d' THEN 2 WHEN '180d' THEN 3 ELSE 4 END,
            on_time_pct DESC,
            total_voyages DESC,
            origin ASC,
            destination ASC
        LIMIT 30
        """,
        ((carrier or "").strip(),),
    ).fetchall()
    conn.close()

    if lane_rows:
        print("\nPer-lane scores:")
        for row in lane_rows:
            _print_score_row("  {0} {1}".format(row["period"], row["lane"]), row)
    else:
        print("\nPer-lane scores: no data")

    if pair_rows:
        print("\nSample port-pair scores:")
        for row in pair_rows:
            label = "  {0} {1} -> {2}".format(row["period"], row["origin"], row["destination"])
            _print_score_row(label, row)
    else:
        print("\nSample port-pair scores: no data")


def _print_test_output():
    count = compute_reliability_scores()
    print("Computed {0} reliability rows.".format(count))
    print()
    _print_leaderboard("90d")
    print()
    lane_rows = get_lane_leaderboard("China", "USA", "90d", 5)
    if not lane_rows:
        print("No China -> USA lane reliability data found.")
        return

    print("China -> USA lane reliability (top 5)")
    for row in lane_rows:
        print(
            "{0} | {1} -> {2} | grade={3} | on-time={4}% | voyages={5}".format(
                row["carrier"],
                row["origin"],
                row["destination"],
                row["reliability_grade"],
                round(float(row["on_time_pct"] or 0), 2),
                int(row["total_voyages"] or 0),
            )
        )


def main():
    parser = argparse.ArgumentParser(description="Vessel schedule reliability utilities")
    parser.add_argument("--compute", action="store_true", help="Recompute reliability scores")
    parser.add_argument("--leaderboard", action="store_true", help="Print the carrier leaderboard")
    parser.add_argument("--carrier", help="Print reliability details for a carrier")
    parser.add_argument("--test", action="store_true", help="Run a compute + leaderboard + lane sample smoke test")
    args = parser.parse_args()

    init_reliability_db()

    if args.compute:
        count = compute_reliability_scores()
        print("Computed {0} reliability rows.".format(count))
    if args.leaderboard:
        _print_leaderboard("90d")
    if args.carrier:
        _print_carrier_details(args.carrier)
    if args.test:
        _print_test_output()
    if not (args.compute or args.leaderboard or args.carrier or args.test):
        parser.print_help()


if __name__ == "__main__":
    main()
