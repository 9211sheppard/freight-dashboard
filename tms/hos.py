from datetime import date, datetime, time, timedelta

from .tms_db import get_db

MAX_DRIVING_HOURS = 11
MAX_ON_DUTY_HOURS = 14
REQUIRED_OFF_HOURS = 10
MAX_CYCLE_HOURS_8DAY = 70

DUTY_STATUS_CHOICES = (
    ("off", "Off Duty"),
    ("sleeper", "Sleeper Berth"),
    ("driving", "Driving"),
    ("on_not_driving", "On Duty (Not Driving)"),
)
DUTY_STATUS_LABELS = dict(DUTY_STATUS_CHOICES)
ON_DUTY_STATUSES = {"driving", "on_not_driving"}
OFF_DUTY_STATUSES = {"off", "sleeper"}
ACTIVE_DRIVER_STATUSES = ("Active", "On Trip")


def _normalize_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _normalize_duty_status(value):
    clean_value = _normalize_text(value).lower()
    if clean_value not in DUTY_STATUS_LABELS:
        raise ValueError("Duty status must be off, sleeper, driving, or on_not_driving.")
    return clean_value


def _parse_datetime_value(value, label):
    if isinstance(value, datetime):
        return value

    clean_value = _normalize_text(value)
    if not clean_value:
        raise ValueError(f"{label} is required.")

    candidate = clean_value[:-1] + "+00:00" if clean_value.endswith("Z") else clean_value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date/time.") from exc


def _serialize_datetime(value):
    return value.replace(second=0, microsecond=0).isoformat(timespec="minutes")


def _minutes_between(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 60)


def _hours_from_minutes(minutes_value):
    return round((minutes_value or 0) / 60.0, 2)


def _pct(value, limit):
    if not limit:
        return 0.0
    return round((float(value or 0) / float(limit)) * 100.0, 1)


def _gauge_value(value, limit):
    return min(_pct(value, limit), 100.0)


def _ensure_hos_schema(conn=None):
    should_close = conn is None
    conn = conn or get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hos_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                driver_id INTEGER NOT NULL,
                log_date DATE NOT NULL,
                duty_status TEXT NOT NULL
                    CHECK (duty_status IN ('off', 'sleeper', 'driving', 'on_not_driving')),
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                location TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
                FOREIGN KEY (driver_id) REFERENCES drivers(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hos_logs_driver_date ON hos_logs(driver_id, log_date)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hos_logs_driver_start ON hos_logs(driver_id, start_time)"
        )
        if should_close:
            conn.commit()
    finally:
        if should_close:
            conn.close()


def _fetch_driver(conn, driver_id):
    return conn.execute(
        """
        SELECT
            d.*,
            (
                SELECT s.shipment_ref
                FROM shipments s
                WHERE s.driver_id = d.id
                  AND s.status NOT IN ('Delivered', 'Cancelled')
                ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
                LIMIT 1
            ) AS active_shipment_ref,
            (
                SELECT v.truck_number
                FROM shipments s
                JOIN vehicles v ON v.id = s.vehicle_id
                WHERE s.driver_id = d.id
                  AND s.status NOT IN ('Delivered', 'Cancelled')
                ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
                LIMIT 1
            ) AS active_truck_number
        FROM drivers d
        WHERE d.id = ?
        LIMIT 1
        """,
        (int(driver_id),),
    ).fetchone()


def _fetch_active_drivers(conn):
    placeholders = ",".join("?" for _ in ACTIVE_DRIVER_STATUSES)
    return conn.execute(
        f"""
        SELECT
            d.*,
            (
                SELECT s.shipment_ref
                FROM shipments s
                WHERE s.driver_id = d.id
                  AND s.status NOT IN ('Delivered', 'Cancelled')
                ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
                LIMIT 1
            ) AS active_shipment_ref,
            (
                SELECT v.truck_number
                FROM shipments s
                JOIN vehicles v ON v.id = s.vehicle_id
                WHERE s.driver_id = d.id
                  AND s.status NOT IN ('Delivered', 'Cancelled')
                ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
                LIMIT 1
            ) AS active_truck_number
        FROM drivers d
        WHERE d.status IN ({placeholders})
        ORDER BY
            CASE d.status
                WHEN 'On Trip' THEN 0
                WHEN 'Active' THEN 1
                ELSE 2
            END,
            d.name COLLATE NOCASE ASC,
            d.id ASC
        """,
        ACTIVE_DRIVER_STATUSES,
    ).fetchall()


def _hydrate_log_row(row):
    record = dict(row)
    start_dt = _parse_datetime_value(record.get("start_time"), "Log start")
    end_dt = _parse_datetime_value(record.get("end_time"), "Log end")
    duration_minutes = int(record.get("duration_minutes") or _minutes_between(start_dt, end_dt))
    record["start_dt"] = start_dt
    record["end_dt"] = end_dt
    record["log_date"] = record.get("log_date") or start_dt.date().isoformat()
    record["duration_minutes"] = duration_minutes
    record["duration_hours"] = _hours_from_minutes(duration_minutes)
    record["duty_status_label"] = DUTY_STATUS_LABELS.get(record.get("duty_status"), "Unknown")
    record["start_time_display"] = start_dt.strftime("%Y-%m-%d %H:%M")
    record["end_time_display"] = end_dt.strftime("%Y-%m-%d %H:%M")
    return record


def _fetch_driver_log_rows(conn, driver_id, start_boundary, end_boundary, *, descending=False):
    order_by = "ORDER BY start_time DESC, id DESC" if descending else "ORDER BY start_time ASC, id ASC"
    rows = conn.execute(
        f"""
        SELECT *
        FROM hos_logs
        WHERE driver_id = ?
          AND start_time < ?
          AND end_time > ?
        {order_by}
        """,
        (
            int(driver_id),
            _serialize_datetime(end_boundary),
            _serialize_datetime(start_boundary),
        ),
    ).fetchall()
    return [_hydrate_log_row(row) for row in rows]


def _overlap_minutes(log_row, window_start, window_end):
    overlap_start = max(log_row["start_dt"], window_start)
    overlap_end = min(log_row["end_dt"], window_end)
    if overlap_end <= overlap_start:
        return 0
    return _minutes_between(overlap_start, overlap_end)


def _resolve_off_duty_reference(log_rows, day_start, day_end):
    work_logs = [
        row
        for row in log_rows
        if row["duty_status"] in ON_DUTY_STATUSES
        and row["end_dt"] > day_start
        and row["start_dt"] < day_end
    ]
    if work_logs:
        return min(row["start_dt"] for row in work_logs), True

    latest_off_end = max(
        (
            min(row["end_dt"], day_end)
            for row in log_rows
            if row["duty_status"] in OFF_DUTY_STATUSES and row["start_dt"] < day_end
        ),
        default=day_start,
    )
    return latest_off_end, False


def _calculate_last_off_duty_period(log_rows, reference_time):
    current_end = reference_time
    total_minutes = 0
    found_period = False

    for row in reversed(log_rows):
        if row["start_dt"] >= current_end:
            continue

        truncated_end = min(row["end_dt"], current_end)
        if truncated_end <= row["start_dt"]:
            continue

        if truncated_end != current_end:
            if found_period:
                break
            continue

        if row["duty_status"] not in OFF_DUTY_STATUSES:
            break

        total_minutes += _minutes_between(row["start_dt"], truncated_end)
        current_end = row["start_dt"]
        found_period = True

    return total_minutes


def _build_summary_payload(driver_row, log_rows, *, today_value=None):
    today_value = today_value or date.today()
    day_start = datetime.combine(today_value, time.min)
    day_end = day_start + timedelta(days=1)
    cycle_start = day_start - timedelta(days=7)

    driving_today_minutes = sum(
        _overlap_minutes(row, day_start, day_end)
        for row in log_rows
        if row["duty_status"] == "driving"
    )
    on_duty_today_minutes = sum(
        _overlap_minutes(row, day_start, day_end)
        for row in log_rows
        if row["duty_status"] in ON_DUTY_STATUSES
    )
    cycle_minutes = sum(
        _overlap_minutes(row, cycle_start, day_end)
        for row in log_rows
        if row["duty_status"] in ON_DUTY_STATUSES
    )
    off_reference, has_work_today = _resolve_off_duty_reference(log_rows, day_start, day_end)
    off_duty_last_period_minutes = _calculate_last_off_duty_period(log_rows, off_reference)

    driving_today = _hours_from_minutes(driving_today_minutes)
    on_duty_today = _hours_from_minutes(on_duty_today_minutes)
    off_duty_last_period = _hours_from_minutes(off_duty_last_period_minutes)
    cycle_hours_8day = _hours_from_minutes(cycle_minutes)

    driving_violation = driving_today > MAX_DRIVING_HOURS
    on_duty_violation = on_duty_today > MAX_ON_DUTY_HOURS
    off_duty_violation = has_work_today and off_duty_last_period < REQUIRED_OFF_HOURS
    cycle_violation = cycle_hours_8day > MAX_CYCLE_HOURS_8DAY

    violation_labels = []
    if driving_violation:
        violation_labels.append("11-hour driving limit")
    if on_duty_violation:
        violation_labels.append("14-hour on-duty window")
    if off_duty_violation:
        violation_labels.append("10-hour off-duty reset")
    if cycle_violation:
        violation_labels.append("70-hour / 8-day cycle")

    return {
        "driver_id": driver_row["id"],
        "driver_name": driver_row["name"],
        "driver_status": driver_row["status"],
        "license_number": driver_row["license_number"],
        "phone": driver_row["phone"],
        "country": driver_row["country"],
        "active_shipment_ref": driver_row["active_shipment_ref"] or "",
        "active_truck_number": driver_row["active_truck_number"] or "",
        "summary_date": today_value.isoformat(),
        "driving_today": driving_today,
        "on_duty_today": on_duty_today,
        "off_duty_last_period": off_duty_last_period,
        "cycle_hours_8day": cycle_hours_8day,
        "driving_violation": driving_violation,
        "on_duty_violation": on_duty_violation,
        "off_duty_violation": off_duty_violation,
        "cycle_violation": cycle_violation,
        "has_violation": any(
            (driving_violation, on_duty_violation, off_duty_violation, cycle_violation)
        ),
        "violation_labels": violation_labels,
        "violation_count": len(violation_labels),
        "driving_pct": _pct(driving_today, MAX_DRIVING_HOURS),
        "on_duty_pct": _pct(on_duty_today, MAX_ON_DUTY_HOURS),
        "off_duty_pct": _pct(off_duty_last_period, REQUIRED_OFF_HOURS),
        "cycle_pct": _pct(cycle_hours_8day, MAX_CYCLE_HOURS_8DAY),
        "driving_progress": _gauge_value(driving_today, MAX_DRIVING_HOURS),
        "on_duty_progress": _gauge_value(on_duty_today, MAX_ON_DUTY_HOURS),
        "off_duty_progress": _gauge_value(off_duty_last_period, REQUIRED_OFF_HOURS),
        "cycle_progress": _gauge_value(cycle_hours_8day, MAX_CYCLE_HOURS_8DAY),
    }


def add_log_entry(driver_id, duty_status, start_time, end_time, location="", notes=""):
    conn = get_db()
    try:
        _ensure_hos_schema(conn)
        driver_row = _fetch_driver(conn, driver_id)
        if not driver_row:
            raise ValueError("Driver not found.")

        clean_status = _normalize_duty_status(duty_status)
        clean_location = _normalize_text(location)
        clean_notes = _normalize_text(notes)
        start_dt = _parse_datetime_value(start_time, "Start time")
        end_dt = _parse_datetime_value(end_time, "End time")
        if end_dt <= start_dt:
            raise ValueError("End time must be after the start time.")

        duration_minutes = _minutes_between(start_dt, end_dt)
        cursor = conn.execute(
            """
            INSERT INTO hos_logs
                (driver_id, log_date, duty_status, start_time, end_time, duration_minutes, location, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(driver_id),
                start_dt.date().isoformat(),
                clean_status,
                _serialize_datetime(start_dt),
                _serialize_datetime(end_dt),
                duration_minutes,
                clean_location,
                clean_notes,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM hos_logs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _hydrate_log_row(row)
    finally:
        conn.close()


def get_driver_logs(driver_id, days=7):
    safe_days = max(int(days or 7), 1)
    conn = get_db()
    try:
        _ensure_hos_schema(conn)
        if not _fetch_driver(conn, driver_id):
            raise ValueError("Driver not found.")
        today_value = date.today()
        start_boundary = datetime.combine(today_value - timedelta(days=safe_days - 1), time.min)
        end_boundary = datetime.combine(today_value + timedelta(days=1), time.min)
        return _fetch_driver_log_rows(
            conn,
            driver_id,
            start_boundary,
            end_boundary,
            descending=True,
        )
    finally:
        conn.close()


def get_driver_summary(driver_id):
    conn = get_db()
    try:
        _ensure_hos_schema(conn)
        driver_row = _fetch_driver(conn, driver_id)
        if not driver_row:
            raise ValueError("Driver not found.")

        today_value = date.today()
        lookback_start = datetime.combine(today_value - timedelta(days=14), time.min)
        lookahead_end = datetime.combine(today_value + timedelta(days=1), time.min)
        log_rows = _fetch_driver_log_rows(conn, driver_id, lookback_start, lookahead_end)
        return _build_summary_payload(driver_row, log_rows, today_value=today_value)
    finally:
        conn.close()


def get_all_violations():
    return [summary for summary in get_hos_dashboard() if summary["has_violation"]]


def get_hos_dashboard():
    conn = get_db()
    try:
        _ensure_hos_schema(conn)
        today_value = date.today()
        lookback_start = datetime.combine(today_value - timedelta(days=14), time.min)
        lookahead_end = datetime.combine(today_value + timedelta(days=1), time.min)

        dashboard = []
        for driver_row in _fetch_active_drivers(conn):
            log_rows = _fetch_driver_log_rows(conn, driver_row["id"], lookback_start, lookahead_end)
            dashboard.append(_build_summary_payload(driver_row, log_rows, today_value=today_value))

        dashboard.sort(
            key=lambda item: (
                0 if item["has_violation"] else 1,
                -item["violation_count"],
                -item["cycle_pct"],
                item["driver_name"].lower(),
            )
        )
        return dashboard
    finally:
        conn.close()
