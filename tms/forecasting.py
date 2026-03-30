from datetime import date, datetime, timedelta

from .tms_db import get_db


HISTORY_WEEKS = 12
FORECAST_WEEKS = 4
MOVING_AVERAGE_WINDOW = 4


def _normalize_text(value):
    return (value or "").strip()


def _parse_sqlite_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _week_start(day_value):
    return day_value - timedelta(days=day_value.weekday())


def _week_key(day_value):
    return day_value.strftime("%Y-%W")


def _week_label(day_value):
    return day_value.strftime("%b %d")


def _lane_label(origin, destination):
    return f"{origin or 'All origins'} -> {destination or 'All destinations'}"


def _build_filters(origin=None, destination=None, start_date=None, end_date=None):
    clauses = []
    params = []

    origin = _normalize_text(origin)
    destination = _normalize_text(destination)

    if origin:
        clauses.append("TRIM(COALESCE(origin_port, '')) = ?")
        params.append(origin)
    if destination:
        clauses.append("TRIM(COALESCE(destination_port, '')) = ?")
        params.append(destination)
    if start_date:
        clauses.append("date(created_at) >= ?")
        params.append(start_date.isoformat())
    if end_date:
        clauses.append("date(created_at) < ?")
        params.append(end_date.isoformat())

    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def _get_anchor_date(conn, origin=None, destination=None):
    where_clause, params = _build_filters(origin=origin, destination=destination)
    row = conn.execute(
        f"SELECT MAX(date(created_at)) AS anchor_date FROM shipments{where_clause}",
        params,
    ).fetchone()
    anchor_date = _parse_sqlite_date(row["anchor_date"] if row else None)
    return anchor_date or date.today()


def _fetch_weekly_series(conn, weeks=HISTORY_WEEKS, origin=None, destination=None):
    weeks = max(1, int(weeks or 1))
    anchor_date = _get_anchor_date(conn, origin=origin, destination=destination)
    anchor_week_start = _week_start(anchor_date)
    start_week = anchor_week_start - timedelta(weeks=weeks - 1)
    end_week = anchor_week_start + timedelta(weeks=1)

    where_clause, params = _build_filters(
        origin=origin,
        destination=destination,
        start_date=start_week,
        end_date=end_week,
    )
    rows = conn.execute(
        f"""
        SELECT
            strftime('%Y-%W', created_at) AS week,
            COUNT(*) AS count,
            COALESCE(SUM(freight_rate), 0) AS revenue
        FROM shipments
        {where_clause}
        GROUP BY strftime('%Y-%W', created_at)
        ORDER BY week
        """,
        params,
    ).fetchall()

    weekly_map = {
        row["week"]: {
            "count": int(row["count"] or 0),
            "revenue": round(float(row["revenue"] or 0.0), 2),
        }
        for row in rows
    }

    series = []
    for offset in range(weeks):
        week_start = start_week + timedelta(weeks=offset)
        week = _week_key(week_start)
        aggregate = weekly_map.get(week, {})
        series.append(
            {
                "week": week,
                "week_start": week_start,
                "count": int(aggregate.get("count", 0)),
                "revenue": round(float(aggregate.get("revenue", 0.0)), 2),
            }
        )
    return series


def _fetch_historical_week_map(conn, origin=None, destination=None, lookback_weeks=104):
    anchor_date = _get_anchor_date(conn, origin=origin, destination=destination)
    anchor_week_start = _week_start(anchor_date)
    start_week = anchor_week_start - timedelta(weeks=max(lookback_weeks, HISTORY_WEEKS))
    end_week = anchor_week_start + timedelta(weeks=1)
    where_clause, params = _build_filters(
        origin=origin,
        destination=destination,
        start_date=start_week,
        end_date=end_week,
    )
    rows = conn.execute(
        f"""
        SELECT
            strftime('%Y-%W', created_at) AS week,
            COUNT(*) AS count,
            COALESCE(SUM(freight_rate), 0) AS revenue
        FROM shipments
        {where_clause}
        GROUP BY strftime('%Y-%W', created_at)
        """,
        params,
    ).fetchall()
    return {
        row["week"]: {
            "count": int(row["count"] or 0),
            "revenue": round(float(row["revenue"] or 0.0), 2),
        }
        for row in rows
    }


def _fetch_distinct_values(conn, column_name):
    rows = conn.execute(
        f"""
        SELECT DISTINCT TRIM({column_name}) AS value
        FROM shipments
        WHERE TRIM(COALESCE({column_name}, '')) != ''
        ORDER BY value
        """
    ).fetchall()
    return [row["value"] for row in rows if row["value"]]


def _fetch_top_lanes(conn, limit=5, weeks=HISTORY_WEEKS):
    anchor_date = _get_anchor_date(conn)
    anchor_week_start = _week_start(anchor_date)
    start_week = anchor_week_start - timedelta(weeks=max(weeks, 1) - 1)
    end_week = anchor_week_start + timedelta(weeks=1)
    rows = conn.execute(
        """
        SELECT
            TRIM(COALESCE(origin_port, '')) AS origin,
            TRIM(COALESCE(destination_port, '')) AS destination,
            COUNT(*) AS count,
            COALESCE(SUM(freight_rate), 0) AS revenue
        FROM shipments
        WHERE TRIM(COALESCE(origin_port, '')) != ''
          AND TRIM(COALESCE(destination_port, '')) != ''
          AND date(created_at) >= ?
          AND date(created_at) < ?
        GROUP BY origin, destination
        ORDER BY count DESC, revenue DESC, origin, destination
        LIMIT ?
        """,
        (start_week.isoformat(), end_week.isoformat(), int(limit)),
    ).fetchall()

    top_lanes = []
    for row in rows:
        top_lanes.append(
            {
                "origin": row["origin"],
                "destination": row["destination"],
                "lane_label": _lane_label(row["origin"], row["destination"]),
                "count": int(row["count"] or 0),
                "revenue": round(float(row["revenue"] or 0.0), 2),
            }
        )
    return top_lanes


def _coefficient_of_variation(values):
    cleaned = [float(value) for value in values if float(value) > 0]
    if len(cleaned) < 2:
        return None
    mean_value = sum(cleaned) / len(cleaned)
    if mean_value <= 0:
        return None
    variance = sum((value - mean_value) ** 2 for value in cleaned) / len(cleaned)
    return (variance ** 0.5) / mean_value


def _trend_details(slope):
    if slope > 0.2:
        return {
            "label": "Up",
            "icon": "bi-arrow-up-right",
            "class": "success",
        }
    if slope < -0.2:
        return {
            "label": "Down",
            "icon": "bi-arrow-down-right",
            "class": "danger",
        }
    return {
        "label": "Flat",
        "icon": "bi-arrow-right",
        "class": "secondary",
    }


def _confidence_score(history_rows):
    observed_weeks = sum(1 for row in history_rows if row["count"] > 0)
    if observed_weeks >= 10:
        score = 2
    elif observed_weeks >= 5:
        score = 1
    else:
        score = 0

    variation = _coefficient_of_variation([row["count"] for row in history_rows])
    if variation is not None:
        if variation < 0.35 and observed_weeks >= 8:
            score = min(2, score + 1)
        elif variation > 0.85:
            score = max(0, score - 1)
    return score


def _confidence_label(base_score, step_index, seasonal_available):
    score = base_score
    if seasonal_available and score > 0:
        score = min(2, score + 1)
    if step_index >= 3:
        score = max(0, score - 1)
    return {0: "low", 1: "med", 2: "high"}[score]


def _seasonal_factor(weekly_map, week_start, metric_key, baseline_average):
    prior_year_key = f"{week_start.year - 1:04d}-{int(week_start.strftime('%W')):02d}"
    prior_year_row = weekly_map.get(prior_year_key)
    if not prior_year_row or baseline_average <= 0:
        return 1.0, False
    prior_value = float(prior_year_row.get(metric_key, 0) or 0)
    if prior_value <= 0:
        return 1.0, False
    factor = prior_value / baseline_average
    return max(0.7, min(1.35, factor)), True


def get_weekly_volumes(weeks=HISTORY_WEEKS):
    conn = get_db()
    try:
        rows = _fetch_weekly_series(conn, weeks=weeks)
    finally:
        conn.close()
    return [{"week": row["week"], "count": row["count"], "revenue": row["revenue"]} for row in rows]


def moving_average(data, window=MOVING_AVERAGE_WINDOW):
    window = max(1, int(window or 1))
    if not data:
        return []

    if isinstance(data[0], dict):
        averages = []
        for index, row in enumerate(data):
            chunk = data[max(0, index - window + 1) : index + 1]
            averages.append(
                {
                    "week": row.get("week"),
                    "count": round(
                        sum(float(item.get("count", 0) or 0) for item in chunk) / len(chunk),
                        2,
                    ),
                    "revenue": round(
                        sum(float(item.get("revenue", 0) or 0) for item in chunk) / len(chunk),
                        2,
                    ),
                }
            )
        return averages

    values = [float(value or 0) for value in data]
    averages = []
    for index, _ in enumerate(values):
        chunk = values[max(0, index - window + 1) : index + 1]
        averages.append(round(sum(chunk) / len(chunk), 2))
    return averages


def linear_trend(data):
    if not data:
        return 0.0, 0.0

    values = []
    for item in data:
        if isinstance(item, dict):
            if "count" in item:
                values.append(float(item.get("count", 0) or 0))
            elif "revenue" in item:
                values.append(float(item.get("revenue", 0) or 0))
            else:
                values.append(0.0)
        else:
            values.append(float(item or 0))

    if len(values) == 1:
        return 0.0, values[0]

    count = len(values)
    x_values = list(range(count))
    sum_x = sum(x_values)
    sum_y = sum(values)
    sum_xy = sum(x * y for x, y in zip(x_values, values))
    sum_xx = sum(x * x for x in x_values)
    denominator = (count * sum_xx) - (sum_x ** 2)
    if denominator == 0:
        return 0.0, values[-1]
    slope = ((count * sum_xy) - (sum_x * sum_y)) / denominator
    intercept = (sum_y - (slope * sum_x)) / count
    return slope, intercept


def _forecast_rows(conn, weeks=FORECAST_WEEKS, origin=None, destination=None):
    weeks = max(1, int(weeks or 1))
    history_rows = _fetch_weekly_series(conn, weeks=HISTORY_WEEKS, origin=origin, destination=destination)
    history_lookup = _fetch_historical_week_map(conn, origin=origin, destination=destination)
    anchor_week_start = history_rows[-1]["week_start"] if history_rows else _week_start(date.today())

    count_values = [row["count"] for row in history_rows]
    revenue_values = [row["revenue"] for row in history_rows]
    count_slope, count_intercept = linear_trend(count_values)
    revenue_slope, revenue_intercept = linear_trend(revenue_values)

    recent_average = moving_average(history_rows, window=min(MOVING_AVERAGE_WINDOW, len(history_rows) or 1))
    recent_count_average = recent_average[-1]["count"] if recent_average else 0.0
    recent_revenue_average = recent_average[-1]["revenue"] if recent_average else 0.0
    count_baseline = recent_count_average or (sum(count_values) / len(count_values) if count_values else 0.0)
    revenue_baseline = recent_revenue_average or (sum(revenue_values) / len(revenue_values) if revenue_values else 0.0)
    base_score = _confidence_score(history_rows)

    forecast = []
    for step in range(1, weeks + 1):
        future_week_start = anchor_week_start + timedelta(weeks=step)
        x_value = len(history_rows) - 1 + step
        projected_count = count_intercept + (count_slope * x_value)
        projected_revenue = revenue_intercept + (revenue_slope * x_value)

        if count_baseline:
            projected_count = (projected_count * 0.7) + (count_baseline * 0.3)
        if revenue_baseline:
            projected_revenue = (projected_revenue * 0.7) + (revenue_baseline * 0.3)

        count_factor, count_seasonal = _seasonal_factor(
            history_lookup, future_week_start, "count", count_baseline
        )
        revenue_factor, revenue_seasonal = _seasonal_factor(
            history_lookup, future_week_start, "revenue", revenue_baseline
        )

        forecast.append(
            {
                "week_label": f"Week of {_week_label(future_week_start)}",
                "forecast_count": max(0, int(round(max(0.0, projected_count) * count_factor))),
                "forecast_revenue": round(max(0.0, projected_revenue) * revenue_factor, 2),
                "confidence": _confidence_label(
                    base_score,
                    step,
                    count_seasonal or revenue_seasonal,
                ),
            }
        )

    return forecast


def forecast_next_periods(weeks=FORECAST_WEEKS):
    conn = get_db()
    try:
        return _forecast_rows(conn, weeks=weeks)
    finally:
        conn.close()


def _build_dashboard(conn, origin=None, destination=None):
    origin = _normalize_text(origin)
    destination = _normalize_text(destination)
    filtered = bool(origin or destination)

    weekly_rows = _fetch_weekly_series(conn, weeks=HISTORY_WEEKS, origin=origin, destination=destination)
    moving_rows = moving_average(weekly_rows, window=min(MOVING_AVERAGE_WINDOW, len(weekly_rows) or 1))
    forecast_rows = _forecast_rows(conn, weeks=FORECAST_WEEKS, origin=origin, destination=destination)
    top_lanes = _fetch_top_lanes(conn, limit=5, weeks=HISTORY_WEEKS)
    origins = _fetch_distinct_values(conn, "origin_port")
    destinations = _fetch_distinct_values(conn, "destination_port")

    count_slope, _ = linear_trend([row["count"] for row in weekly_rows])
    trend = _trend_details(count_slope)

    max_count = max([row["count"] for row in weekly_rows], default=0)
    bar_denominator = max(max_count, 1)
    for row, moving_row in zip(weekly_rows, moving_rows):
        row["week_label"] = _week_label(row["week_start"])
        row["bar_pct"] = round((row["count"] / bar_denominator) * 100, 2)
        row["moving_avg_count"] = moving_row["count"]

    avg_weekly_shipments = round(
        (sum(row["count"] for row in weekly_rows) / len(weekly_rows)) if weekly_rows else 0.0,
        1,
    )
    projected_next_month = sum(row["forecast_count"] for row in forecast_rows)
    projected_next_month_revenue = round(sum(row["forecast_revenue"] for row in forecast_rows), 2)

    if filtered:
        top_lane_label = _lane_label(origin, destination)
        top_lane_shipments = sum(row["count"] for row in weekly_rows)
    elif top_lanes:
        top_lane_label = top_lanes[0]["lane_label"]
        top_lane_shipments = top_lanes[0]["count"]
    else:
        top_lane_label = "No lane data"
        top_lane_shipments = 0

    scope_label = _lane_label(origin, destination) if filtered else "All lanes"

    return {
        "weekly_volumes": [
            {"week": row["week"], "count": row["count"], "revenue": row["revenue"]}
            for row in weekly_rows
        ],
        "forecast_next_periods": forecast_rows,
        "top_lanes": top_lanes,
        "history_rows": weekly_rows,
        "history_max_count": max_count,
        "avg_weekly_shipments": avg_weekly_shipments,
        "projected_next_month": projected_next_month,
        "projected_next_month_revenue": projected_next_month_revenue,
        "top_lane_label": top_lane_label,
        "top_lane_shipments": top_lane_shipments,
        "trend_label": trend["label"],
        "trend_icon": trend["icon"],
        "trend_class": trend["class"],
        "origins": origins,
        "destinations": destinations,
        "selected_origin": origin,
        "selected_destination": destination,
        "lane_filter_active": filtered,
        "scope_label": scope_label,
    }


def get_lane_forecast(origin, destination):
    conn = get_db()
    try:
        return _build_dashboard(conn, origin=origin, destination=destination)
    finally:
        conn.close()


def get_forecast_dashboard():
    conn = get_db()
    try:
        return _build_dashboard(conn)
    finally:
        conn.close()
