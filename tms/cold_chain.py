from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .tms_db import get_db


PROVIDERS: dict[str, dict[str, Any]] = {
    "sensitech": {
        "name": "Sensitech",
        "region": "Global",
        "auth_type": "contact_vendor",
        "settings_keys": [],
        "description": "End-to-end cold chain visibility for food, life sciences, and industrial shipments.",
        "capabilities": [
            "temperature monitoring",
            "shipment visibility",
            "alert workflows",
            "compliance reporting",
        ],
        "website": "https://www.sensitech.com/en/",
        "docs": "https://www.sensitech.com/en/support/downloads/",
    },
    "orbcomm": {
        "name": "ORBCOMM",
        "region": "Global",
        "auth_type": "contact_vendor",
        "settings_keys": [],
        "description": "Reefer and trailer telematics platform for remote temperature, location, and cargo security monitoring.",
        "capabilities": [
            "temperature monitoring",
            "remote reefer visibility",
            "location tracking",
            "sensor integrations",
        ],
        "website": "https://www.orbcomm.com/en/solutions/transportation/reefer-monitoring",
        "docs": "https://www.orbcomm.com/PDF/datasheet/ColdChainView.pdf",
    },
    "tive": {
        "name": "Tive",
        "region": "Global",
        "auth_type": "oauth2_client_credentials",
        "settings_keys": ["tive_client_id", "tive_client_secret", "tive_account_id"],
        "description": "Real-time shipment tracker platform with temperature, humidity, location, and alert webhooks.",
        "capabilities": [
            "temperature monitoring",
            "humidity monitoring",
            "location tracking",
            "webhooks",
        ],
        "website": "https://www.tive.com/",
        "docs": "https://developers.tive.com/",
    },
    "controlant": {
        "name": "Controlant",
        "region": "Global",
        "auth_type": "contact_vendor",
        "settings_keys": [],
        "description": "Cold-chain-as-a-service platform with real-time Saga device monitoring and integrations.",
        "capabilities": [
            "temperature monitoring",
            "quality reports",
            "excursion alerts",
            "integration api",
        ],
        "website": "https://www.controlant.com/",
        "docs": "https://www.controlant.com/integrations",
    },
    "emerson_cargo_watch": {
        "name": "Emerson Cargo Watch",
        "region": "Global",
        "auth_type": "portal_login",
        "settings_keys": [],
        "description": "Copeland cargo monitoring stack with GO trackers and the Oversight cold chain portal.",
        "capabilities": [
            "temperature monitoring",
            "humidity monitoring",
            "location tracking",
            "oversight portal",
        ],
        "website": "https://www.copeland.com/en-us/products/controls-monitoring-systems/cargo-tracking-monitoring/trackers",
        "docs": "https://www.copeland.com/en-in/products/controls-monitoring-systems/cargo-tracking-monitoring/oversight-online-portal",
    },
    "berlinger": {
        "name": "Berlinger",
        "region": "Global",
        "auth_type": "contact_vendor",
        "settings_keys": [],
        "description": "Swiss cold chain monitoring brand for USB loggers, fridge tags, and SmartSystem visibility.",
        "capabilities": [
            "temperature monitoring",
            "pdf logger reports",
            "smart system visibility",
            "vaccine cold chain",
        ],
        "website": "https://www.berlinger.com/smartsystem",
        "docs": "https://www.berlinger.com/shipment-monitoring-solutions/cold-chain-data-logger",
    },
    "elpro": {
        "name": "ELPRO",
        "region": "Global",
        "auth_type": "contact_vendor",
        "settings_keys": [],
        "description": "GxP-focused temperature monitoring and digital logger platform for pharma and life sciences.",
        "capabilities": [
            "temperature monitoring",
            "humidity monitoring",
            "gxp compliance",
            "cloud monitoring",
        ],
        "website": "https://www.elpro.com/en/",
        "docs": "https://www.elpro.com/en/support/operation-manual-elpromonitor",
    },
    "onset_hobo": {
        "name": "Onset HOBO",
        "region": "North America",
        "auth_type": "manual_export",
        "settings_keys": [],
        "description": "Temperature and humidity data logger family commonly used for environmental and cold storage monitoring.",
        "capabilities": [
            "temperature monitoring",
            "humidity monitoring",
            "threshold alerts",
            "bluetooth download",
        ],
        "website": "https://www.onsetcomp.com/products/temperature-relative-humidity",
        "docs": "https://www.onsetcomp.com/products/data-loggers/mx1101",
    },
    "tagmaster": {
        "name": "TagMaster",
        "region": "Europe",
        "auth_type": "manual_export",
        "settings_keys": [],
        "description": "RFID and tag-based sensor hardware suited to asset identification workflows in harsh logistics environments.",
        "capabilities": [
            "tag identity",
            "asset visibility",
            "rfid integration",
            "sensor hardware",
        ],
        "website": "https://tagmaster.com/",
        "docs": "https://tagmaster.com/traffic-solutions/resources/datasheets/",
    },
    "cold_chain_technologies": {
        "name": "Cold Chain Technologies",
        "region": "North America",
        "auth_type": "contact_vendor",
        "settings_keys": [],
        "description": "Packaging and real-time tracking programs for temperature-sensitive life sciences shipments.",
        "capabilities": [
            "temperature monitoring",
            "humidity monitoring",
            "real-time tracking",
            "shipment programs",
        ],
        "website": "https://www.coldchaintech.com/",
        "docs": "https://www.coldchaintech.com/real-time-tracking",
    },
}

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS cold_chain_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_ref TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    temperature_c REAL NOT NULL,
    humidity_pct REAL,
    location_label TEXT,
    lat REAL,
    lon REAL,
    recorded_at TIMESTAMP NOT NULL,
    alert_triggered INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS cold_chain_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_ref TEXT NOT NULL,
    min_temp_c REAL,
    max_temp_c REAL,
    min_humidity REAL,
    max_humidity REAL,
    alert_email TEXT,
    provider TEXT,
    sensor_id TEXT,
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cold_chain_readings_shipment_ref
    ON cold_chain_readings (shipment_ref, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cold_chain_readings_sensor_id
    ON cold_chain_readings (sensor_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cold_chain_readings_alert_triggered
    ON cold_chain_readings (alert_triggered, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_cold_chain_configs_shipment_ref
    ON cold_chain_configs (shipment_ref, active, created_at DESC);
"""


def get_providers() -> dict[str, dict[str, Any]]:
    return PROVIDERS


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _format_timestamp(value: str | None) -> str:
    parsed = _parse_timestamp(value)
    if not parsed:
        return "No reading yet"
    return parsed.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _coerce_float(value: Any, field_name: str, *, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field_name} is required.")
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number.") from exc


def _ensure_tables(conn) -> None:
    conn.executescript(_CREATE_TABLES)
    conn.commit()


def _conn():
    conn = get_db()
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _provider_name(provider_key: str | None) -> str:
    key = _normalize_text(provider_key)
    if key in PROVIDERS:
        return PROVIDERS[key]["name"]
    if not key:
        return "Unassigned"
    return key.replace("_", " ").title()


def _range_label(config: dict[str, Any] | None) -> str:
    if not config:
        return "No thresholds configured"

    parts: list[str] = []
    temp_min = config.get("min_temp_c")
    temp_max = config.get("max_temp_c")
    humidity_min = config.get("min_humidity")
    humidity_max = config.get("max_humidity")

    if temp_min is not None or temp_max is not None:
        temp_low = "min open" if temp_min is None else f"{temp_min:.1f}C"
        temp_high = "max open" if temp_max is None else f"{temp_max:.1f}C"
        parts.append(f"Temp {temp_low} to {temp_high}")
    if humidity_min is not None or humidity_max is not None:
        humidity_low = "min open" if humidity_min is None else f"{humidity_min:.0f}%"
        humidity_high = "max open" if humidity_max is None else f"{humidity_max:.0f}%"
        parts.append(f"Humidity {humidity_low} to {humidity_high}")

    return " / ".join(parts) if parts else "No thresholds configured"


def _location_label(location: str | None, lat: float | None, lon: float | None) -> str:
    label = _normalize_text(location)
    if label:
        return label
    if lat is None or lon is None:
        return "Unspecified"
    return f"{lat:.4f}, {lon:.4f}"


def _is_out_of_range(config: dict[str, Any] | None, temp_c: float | None, humidity_pct: float | None) -> bool:
    if not config:
        return False

    checks = [
        (config.get("min_temp_c"), temp_c, lambda actual, threshold: actual < threshold),
        (config.get("max_temp_c"), temp_c, lambda actual, threshold: actual > threshold),
        (config.get("min_humidity"), humidity_pct, lambda actual, threshold: actual < threshold),
        (config.get("max_humidity"), humidity_pct, lambda actual, threshold: actual > threshold),
    ]

    for threshold, actual, comparator in checks:
        if threshold is None or actual is None:
            continue
        if comparator(actual, threshold):
            return True
    return False


def _build_reading_dict(
    row: sqlite3.Row | dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    chart_min: float | None = None,
    chart_max: float | None = None,
) -> dict[str, Any]:
    reading = dict(row)
    temp_c = reading.get("temperature_c")
    humidity_pct = reading.get("humidity_pct")
    reading["provider_name"] = _provider_name(reading.get("provider"))
    reading["recorded_at_display"] = _format_timestamp(reading.get("recorded_at"))
    reading["temperature_display"] = "-" if temp_c is None else f"{temp_c:.1f}C"
    reading["humidity_display"] = "-" if humidity_pct is None else f"{humidity_pct:.0f}%"
    reading["location_display"] = _location_label(reading.get("location_label"), reading.get("lat"), reading.get("lon"))
    reading["status_label"] = "Excursion" if reading.get("alert_triggered") else "In Range"
    reading["status_class"] = "danger" if reading.get("alert_triggered") else "success"
    reading["range_label"] = _range_label(config)

    if chart_min is not None and chart_max is not None and temp_c is not None and chart_max > chart_min:
        pct = ((temp_c - chart_min) / (chart_max - chart_min)) * 100
        reading["chart_pct"] = max(6, min(100, round(pct, 1)))
    else:
        reading["chart_pct"] = 0

    return reading


def _chart_bounds(readings: list[sqlite3.Row], config: dict[str, Any] | None) -> tuple[float, float]:
    values: list[float] = []

    for row in readings:
        temp_c = row["temperature_c"]
        if temp_c is not None:
            values.append(float(temp_c))

    if config:
        for key in ("min_temp_c", "max_temp_c"):
            if config.get(key) is not None:
                values.append(float(config[key]))

    if not values:
        return -10.0, 10.0

    low = min(values)
    high = max(values)
    spread = max(high - low, 1.0)
    padding = max(1.0, spread * 0.15)
    return low - padding, high + padding


def _get_config_row(conn, shipment_ref: str, *, active_only: bool = False):
    query = """
        SELECT *
        FROM cold_chain_configs
        WHERE shipment_ref = ?
    """
    params: list[Any] = [shipment_ref]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY active DESC, created_at DESC, id DESC LIMIT 1"
    return conn.execute(query, params).fetchone()


def get_shipment_config(shipment_ref: str) -> dict[str, Any] | None:
    shipment_ref = _normalize_text(shipment_ref)
    if not shipment_ref:
        return None

    conn = _conn()
    try:
        row = _get_config_row(conn, shipment_ref, active_only=True) or _get_config_row(conn, shipment_ref)
        if not row:
            return None
        config = dict(row)
        config["provider_name"] = _provider_name(config.get("provider"))
        config["range_label"] = _range_label(config)
        return config
    finally:
        conn.close()


def configure_shipment(
    shipment_ref,
    min_temp,
    max_temp,
    min_humidity,
    max_humidity,
    alert_email,
    provider,
    sensor_id,
):
    shipment_ref = _normalize_text(shipment_ref)
    provider = _normalize_text(provider)
    sensor_id = _normalize_text(sensor_id)
    alert_email = _normalize_text(alert_email)

    if not shipment_ref:
        raise ValueError("Shipment reference is required.")
    if provider and provider not in PROVIDERS:
        raise ValueError("Unknown cold chain provider.")

    min_temp_c = _coerce_float(min_temp, "Minimum temperature")
    max_temp_c = _coerce_float(max_temp, "Maximum temperature")
    min_humidity_pct = _coerce_float(min_humidity, "Minimum humidity")
    max_humidity_pct = _coerce_float(max_humidity, "Maximum humidity")

    if min_temp_c is not None and max_temp_c is not None and min_temp_c > max_temp_c:
        raise ValueError("Minimum temperature cannot be greater than maximum temperature.")
    if min_humidity_pct is not None and max_humidity_pct is not None and min_humidity_pct > max_humidity_pct:
        raise ValueError("Minimum humidity cannot be greater than maximum humidity.")

    created_at = _utcnow()
    conn = _conn()
    try:
        conn.execute(
            "UPDATE cold_chain_configs SET active = 0 WHERE shipment_ref = ? AND active = 1",
            (shipment_ref,),
        )
        conn.execute(
            """
            INSERT INTO cold_chain_configs
                (shipment_ref, min_temp_c, max_temp_c, min_humidity, max_humidity,
                 alert_email, provider, sensor_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                shipment_ref,
                min_temp_c,
                max_temp_c,
                min_humidity_pct,
                max_humidity_pct,
                alert_email,
                provider,
                sensor_id,
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_shipment_config(shipment_ref)


def ingest_reading(
    shipment_ref,
    sensor_id,
    provider,
    temp_c,
    humidity=None,
    lat=None,
    lon=None,
    location=None,
):
    shipment_ref = _normalize_text(shipment_ref)
    sensor_id = _normalize_text(sensor_id)
    provider = _normalize_text(provider)
    location = _normalize_text(location)

    if not shipment_ref:
        raise ValueError("Shipment reference is required.")
    if not sensor_id:
        raise ValueError("Sensor ID is required.")
    if provider not in PROVIDERS:
        raise ValueError("Unknown cold chain provider.")

    temperature_c = _coerce_float(temp_c, "Temperature", required=True)
    humidity_pct = _coerce_float(humidity, "Humidity")
    latitude = _coerce_float(lat, "Latitude")
    longitude = _coerce_float(lon, "Longitude")
    recorded_at = _utcnow()

    conn = _conn()
    try:
        config_row = _get_config_row(conn, shipment_ref, active_only=True)
        config = dict(config_row) if config_row else None
        alert_triggered = 1 if _is_out_of_range(config, temperature_c, humidity_pct) else 0

        cursor = conn.execute(
            """
            INSERT INTO cold_chain_readings
                (shipment_ref, sensor_id, provider, temperature_c, humidity_pct,
                 location_label, lat, lon, recorded_at, alert_triggered)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_ref,
                sensor_id,
                provider,
                temperature_c,
                humidity_pct,
                location,
                latitude,
                longitude,
                recorded_at,
                alert_triggered,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM cold_chain_readings WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        reading = _build_reading_dict(row, config=config)
        reading["alert_email"] = config.get("alert_email", "") if config else ""
        return reading
    finally:
        conn.close()


def get_readings(shipment_ref: str, hours: int = 24) -> list[dict[str, Any]]:
    shipment_ref = _normalize_text(shipment_ref)
    hours = max(1, min(int(hours or 24), 24 * 14))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = _conn()
    try:
        config_row = _get_config_row(conn, shipment_ref, active_only=True) or _get_config_row(conn, shipment_ref)
        config = dict(config_row) if config_row else None
        rows = conn.execute(
            """
            SELECT *
            FROM cold_chain_readings
            WHERE shipment_ref = ? AND recorded_at >= ?
            ORDER BY recorded_at ASC, id ASC
            """,
            (shipment_ref, cutoff),
        ).fetchall()
        chart_min, chart_max = _chart_bounds(rows, config)
        return [
            _build_reading_dict(row, config=config, chart_min=chart_min, chart_max=chart_max)
            for row in rows
        ]
    finally:
        conn.close()


def get_excursions(shipment_ref: str | None = None) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        if shipment_ref:
            config_row = _get_config_row(conn, _normalize_text(shipment_ref), active_only=True) or _get_config_row(conn, _normalize_text(shipment_ref))
            config = dict(config_row) if config_row else None
            rows = conn.execute(
                """
                SELECT *
                FROM cold_chain_readings
                WHERE shipment_ref = ? AND alert_triggered = 1
                ORDER BY recorded_at DESC, id DESC
                """,
                (_normalize_text(shipment_ref),),
            ).fetchall()
            return [_build_reading_dict(row, config=config) for row in rows]

        rows = conn.execute(
            """
            SELECT *
            FROM cold_chain_readings
            WHERE alert_triggered = 1
            ORDER BY recorded_at DESC, id DESC
            """
        ).fetchall()

        excursions: list[dict[str, Any]] = []
        config_cache: dict[str, dict[str, Any] | None] = {}
        for row in rows:
            ref = row["shipment_ref"]
            if ref not in config_cache:
                config_row = _get_config_row(conn, ref, active_only=True) or _get_config_row(conn, ref)
                config_cache[ref] = dict(config_row) if config_row else None
            excursions.append(_build_reading_dict(row, config=config_cache[ref]))
        return excursions
    finally:
        conn.close()


def get_active_configs() -> list[dict[str, Any]]:
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT
                c.*,
                r.id AS last_reading_id,
                r.temperature_c AS last_temperature_c,
                r.humidity_pct AS last_humidity_pct,
                r.location_label AS last_location_label,
                r.lat AS last_lat,
                r.lon AS last_lon,
                r.recorded_at AS last_recorded_at,
                r.alert_triggered AS last_alert_triggered,
                r.provider AS last_provider,
                r.sensor_id AS last_sensor_id
            FROM cold_chain_configs c
            LEFT JOIN cold_chain_readings r
                ON r.id = (
                    SELECT r2.id
                    FROM cold_chain_readings r2
                    WHERE r2.shipment_ref = c.shipment_ref
                    ORDER BY r2.recorded_at DESC, r2.id DESC
                    LIMIT 1
                )
            WHERE c.active = 1
            ORDER BY c.created_at DESC, c.id DESC
            """
        ).fetchall()

        configs: list[dict[str, Any]] = []
        for row in rows:
            config = dict(row)
            provider_key = _normalize_text(config.get("provider") or config.get("last_provider"))
            sensor_id = _normalize_text(config.get("sensor_id") or config.get("last_sensor_id"))
            last_temp = config.get("last_temperature_c")
            last_humidity = config.get("last_humidity_pct")
            last_alert = int(config.get("last_alert_triggered") or 0)

            config["provider"] = provider_key
            config["provider_name"] = _provider_name(provider_key)
            config["sensor_id"] = sensor_id
            config["range_label"] = _range_label(config)
            config["last_temperature_display"] = "-" if last_temp is None else f"{last_temp:.1f}C"
            config["last_humidity_display"] = "-" if last_humidity is None else f"{last_humidity:.0f}%"
            config["last_location_display"] = _location_label(
                config.get("last_location_label"),
                config.get("last_lat"),
                config.get("last_lon"),
            )
            config["last_reading_display"] = _format_timestamp(config.get("last_recorded_at"))

            if not config.get("last_recorded_at"):
                config["status_label"] = "No Data"
                config["status_class"] = "secondary"
            elif last_alert:
                config["status_label"] = "Excursion"
                config["status_class"] = "danger"
            else:
                config["status_label"] = "In Range"
                config["status_class"] = "success"

            configs.append(config)

        return configs
    finally:
        conn.close()


def get_cold_chain_dashboard() -> dict[str, Any]:
    conn = _conn()
    try:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        online_cutoff = (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")

        active_monitored_shipments = conn.execute(
            "SELECT COUNT(DISTINCT shipment_ref) FROM cold_chain_configs WHERE active = 1"
        ).fetchone()[0]
        excursions_today = conn.execute(
            """
            SELECT COUNT(*)
            FROM cold_chain_readings
            WHERE alert_triggered = 1 AND recorded_at >= ?
            """,
            (start_of_day,),
        ).fetchone()[0]
        sensors_online = conn.execute(
            """
            SELECT COUNT(DISTINCT sensor_id)
            FROM cold_chain_readings
            WHERE recorded_at >= ? AND COALESCE(TRIM(sensor_id), '') != ''
            """,
            (online_cutoff,),
        ).fetchone()[0]
        providers_connected = conn.execute(
            """
            SELECT COUNT(DISTINCT provider)
            FROM cold_chain_configs
            WHERE active = 1 AND COALESCE(TRIM(provider), '') != ''
            """
        ).fetchone()[0]
    finally:
        conn.close()

    active_configs = get_active_configs()
    recent_excursions = get_excursions()[:10]
    providers = [
        {
            "key": key,
            **provider,
        }
        for key, provider in PROVIDERS.items()
    ]

    return {
        "active_monitored_shipments": active_monitored_shipments,
        "excursions_today": excursions_today,
        "sensors_online": sensors_online,
        "providers_connected": providers_connected,
        "active_configs": active_configs,
        "recent_excursions": recent_excursions,
        "providers": providers,
        "dashboard_updated_at": _format_timestamp(_utcnow()),
    }
