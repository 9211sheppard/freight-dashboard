import base64
import hashlib
import json
import os
import random
import re
import secrets
import sqlite3
import string
import weakref
import tempfile
from collections import Counter
from math import asin, ceil, cos, radians, sin, sqrt
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .tenanting import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    PLAN_OPTIONS,
    TENANT_SCOPED_TABLES,
    TENANT_STATUS_OPTIONS,
    TenantAwareConnection,
    disabled_tenant_scope,
    get_current_tenant,
    normalize_tenant_id,
    tenant_context,
)

import requests

TMS_DB = os.getenv("TMS_DB_PATH") or os.path.join(os.path.dirname(__file__), "tms.db")
CONTACTS_DB = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")
DEFAULT_TENANT_REGION = "ca-central"
DEFAULT_TENANT_SESSION_TIMEOUT_MINUTES = 30
POD_UPLOAD_DIR = os.getenv("TMS_POD_UPLOAD_DIR") or os.path.join(os.path.dirname(__file__), "uploads", "pods")
FMCSA_BASE_URL = "https://mobile.fmcsa.dot.gov/qc/services"
FMCSA_CARRIER_URL_TEMPLATE = FMCSA_BASE_URL + "/carriers/{dot}/"
FMCSA_AUTHORITY_URL_TEMPLATE = FMCSA_BASE_URL + "/carriers/{dot}/authority/"
_OPEN_DB_CONNECTIONS = weakref.WeakSet()

DEFAULT_SETTINGS = {
    "company_name": "Summit Freight",
    "company_logo": "",
    "primary_color": "#0f766e",
    "setup_complete": "0",
    "updated_at": "",
    # Trade / tariff integrations
    "trade_api_key": "",
    "trade_api_provider": "",
    # Email / SMTP outbound
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_user": "",
    "smtp_pass": "",
    "smtp_from": "",
    "smtp_from_name": "",
    "smtp_use_tls": "true",
    "smtp_use_ssl": "false",
    # IMAP inbound (for reply fetching)
    "imap_host": "",
    "imap_port": "993",
    "imap_user": "",
    "imap_pass": "",
    "imap_ssl": "true",
}

_API_KEY_HASH_HEX_RE = re.compile(r"^[0-9a-f]{64}$")

EDI_PARTNER_FORMATS = ("X12", "EDIFACT")
EDI_PARTNER_DIRECTIONS = ("inbound", "outbound", "both")

DEMO_CARRIERS = [
    {
        "name": "NorthStar Freight",
        "scac": "NSFT",
        "country": "United States",
        "contact_email": "ops@northstar.demo",
        "contact_phone": "+1 (312) 555-0181",
    },
    {
        "name": "BluePeak Logistics",
        "scac": "BPLG",
        "country": "United States",
        "contact_email": "dispatch@bluepeak.demo",
        "contact_phone": "+1 (469) 555-0138",
    },
    {
        "name": "RedRiver Transport",
        "scac": "RRTR",
        "country": "Canada",
        "contact_email": "team@redriver.demo",
        "contact_phone": "+1 (416) 555-0196",
    },
]

DEMO_LANES = [
    {
        "lane_code": "CHI-DAL-FTL",
        "origin_name": "Chicago, IL",
        "destination_name": "Dallas, TX",
        "mode": "FTL",
        "avg_transit_days": 2,
        "weekly_shipments": 12,
    },
    {
        "lane_code": "TOR-ATL-LTL",
        "origin_name": "Toronto, ON",
        "destination_name": "Atlanta, GA",
        "mode": "LTL",
        "avg_transit_days": 3,
        "weekly_shipments": 8,
    },
]

DEMO_PORTAL_TOKENS = [
    {
        "token": "demo-lakefront-token",
        "customer_name": "Lakefront Foods",
        "email": "shipping@lakefront.demo",
        "shipment_refs": ["TMS-DEMO-001"],
    },
    {
        "token": "demo-steelridge-token",
        "customer_name": "Steel Ridge Parts",
        "email": "logistics@steelridge.demo",
        "shipment_refs": ["TMS-DEMO-002"],
    },
    {
        "token": "demo-ontariohs-token",
        "customer_name": "Ontario Health Supply",
        "email": "ops@ontariohealth.demo",
        "shipment_refs": ["TMS-DEMO-003", "TMS-DEMO-004"],
    },
]

STATUS_VARIANTS = {
    "Draft": "secondary",
    "Active": "success",
    "Booked": "primary",
    "In Transit": "warning",
    "Delivered": "info",
    "Cancelled": "danger",
}

STATUS_PROGRESS = {
    "Draft": 8,
    "Booked": 24,
    "Active": 42,
    "In Transit": 72,
    "Delivered": 100,
    "Cancelled": 100,
}

CONTROL_TOWER_ACTIVE_STATUSES = ("Draft", "Active", "Booked", "In Transit")
CONTROL_TOWER_HEALTH_LABELS = {
    "on_time": "On Time",
    "at_risk": "At Risk",
    "delayed": "Delayed",
    "draft": "Draft",
}
CONTROL_TOWER_HEALTH_PRIORITY = {
    "delayed": 0,
    "at_risk": 1,
    "on_time": 2,
    "draft": 3,
}

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
GEOCODE_USER_AGENT = "contact-dashboard-tms-tracking/1.0"

CONTRACT_RATE_LABELS = {
    "rate_20ft": "20ft",
    "rate_40ft": "40ft",
    "rate_40hc": "40HC",
}

LOAD_STATUSES = ("Planning", "Dispatched", "In Transit", "Delivered")
DEFAULT_LOAD_CAPACITY_KG = 30000.0
DEFAULT_LOAD_CAPACITY_CBM = 90.0
DRIVER_STATUS_OPTIONS = ("Active", "Inactive", "On Trip")
VEHICLE_STATUS_OPTIONS = ("Active", "Inactive", "On Trip", "Maintenance")
DUTY_STATUS_OPTIONS = ("Driving", "On Duty", "Off Duty", "Sleeper")
DOCK_TYPES = ("inbound", "outbound", "both")
DOCK_APPOINTMENT_TYPES = ("inbound", "outbound")
DOCK_APPOINTMENT_STATUSES = ("Scheduled", "Checked-In", "Loading", "Complete", "No-Show")
DOCK_APPOINTMENT_STATUS_STYLES = {
    "Scheduled": "primary",
    "Checked-In": "info",
    "Loading": "warning",
    "Complete": "success",
    "No-Show": "danger",
}
PORTAL_QUOTE_REQUEST_STATUS_STYLES = {
    "pending": "warning",
    "quoted": "info",
    "booked": "success",
    "cancelled": "secondary",
}
DOCK_SLOT_START_HOUR = 6
DOCK_SLOT_END_HOUR = 18
DOCK_DEFAULT_LOOKAHEAD_DAYS = 7
CLAIM_TYPES = ("Loss", "Damage", "Shortage", "Delay")
CLAIM_STATUSES = ("Filed", "Under Review", "Approved", "Paid", "Denied")
CLAIM_STATUS_TRANSITIONS = {
    "Filed": {"Under Review", "Denied"},
    "Under Review": {"Approved", "Denied"},
    "Approved": {"Paid", "Denied"},
    "Paid": set(),
    "Denied": set(),
}

KNOWN_LOCATION_COORDINATES = {
    "atlanta, ga": (33.7490, -84.3880),
    "chicago, il": (41.8781, -87.6298),
    "dallas, tx": (32.7767, -96.7970),
    "houston, tx": (29.7604, -95.3698),
    "long beach, ca": (33.7701, -118.1937),
    "los angeles, ca": (34.0522, -118.2437),
    "memphis, tn": (35.1495, -90.0490),
    "miami, fl": (25.7617, -80.1918),
    "montreal, qc": (45.5017, -73.5673),
    "new york, ny": (40.7128, -74.0060),
    "newark, nj": (40.7357, -74.1724),
    "savannah, ga": (32.0809, -81.0912),
    "seattle, wa": (47.6062, -122.3321),
    "toronto, on": (43.6532, -79.3832),
    "vancouver, bc": (49.2827, -123.1207),
}

_LOCATION_COORD_CACHE = {}

CARBON_FRAMEWORK_LABEL = "ISO 14083 / GLEC estimate"
CARBON_FRAMEWORK_NOTE = (
    "Calculated from haversine distance, shipment weight, and mode-based emission factors."
)
CARBON_EMISSION_FACTOR_LABEL = "kg CO2 per tonne-km"
CARBON_EMISSION_FACTORS = {
    "ocean": 0.010,
    "air": 0.602,
    "road": 0.096,
    "rail": 0.028,
}
CARBON_MODE_LABELS = {
    "ocean": "Ocean",
    "air": "Air",
    "road": "Road",
    "rail": "Rail",
}


def _build_demo_shipments():
    today = datetime.now().date()
    return [
        {
            "shipment_ref": "TMS-DEMO-001",
            "status": "Booked",
            "shipper_name": "Lakefront Foods",
            "shipper_address": "Chicago, IL",
            "consignee_name": "Metro Grocers",
            "consignee_address": "Dallas, TX",
            "carrier_name": "NorthStar Freight",
            "carrier_scac": "NSFT",
            "origin_port": "Chicago, IL",
            "destination_port": "Dallas, TX",
            "mode": "FTL",
            "lane_code": "CHI-DAL-FTL",
            "etd": (today + timedelta(days=1)).isoformat(),
            "eta": (today + timedelta(days=3)).isoformat(),
            "cargo_description": "Frozen grocery replenishment",
            "containers": "53' Reefer",
            "weight_kg": 12400,
            "volume_cbm": 41.2,
            "freight_rate": 3200.00,
            "currency": "USD",
            "incoterm": "DAP",
            "notes": "White-label demo load for sandbox.",
        },
        {
            "shipment_ref": "TMS-DEMO-002",
            "status": "Active",
            "shipper_name": "Steel Ridge Parts",
            "shipper_address": "Chicago, IL",
            "consignee_name": "Lone Star Manufacturing",
            "consignee_address": "Dallas, TX",
            "carrier_name": "BluePeak Logistics",
            "carrier_scac": "BPLG",
            "origin_port": "Chicago, IL",
            "destination_port": "Dallas, TX",
            "mode": "FTL",
            "lane_code": "CHI-DAL-FTL",
            "etd": (today - timedelta(days=1)).isoformat(),
            "eta": (today + timedelta(days=1)).isoformat(),
            "cargo_description": "Industrial spare parts",
            "containers": "48' Dry Van",
            "weight_kg": 18750,
            "volume_cbm": 52.0,
            "freight_rate": 2860.00,
            "currency": "USD",
            "incoterm": "FCA",
            "notes": "Prioritized delivery for plant maintenance window.",
        },
        {
            "shipment_ref": "TMS-DEMO-003",
            "status": "In Transit",
            "shipper_name": "Ontario Health Supply",
            "shipper_address": "Toronto, ON",
            "consignee_name": "Peachtree Med Group",
            "consignee_address": "Atlanta, GA",
            "carrier_name": "RedRiver Transport",
            "carrier_scac": "RRTR",
            "origin_port": "Toronto, ON",
            "destination_port": "Atlanta, GA",
            "mode": "LTL",
            "lane_code": "TOR-ATL-LTL",
            "etd": (today - timedelta(days=2)).isoformat(),
            "eta": (today + timedelta(days=1)).isoformat(),
            "cargo_description": "Medical consumables",
            "containers": "LTL Pallets",
            "weight_kg": 6900,
            "volume_cbm": 19.4,
            "freight_rate": 2140.00,
            "currency": "USD",
            "incoterm": "DDP",
            "notes": "Cross-border paperwork cleared.",
        },
        {
            "shipment_ref": "TMS-DEMO-004",
            "status": "Delivered",
            "shipper_name": "FreshStone Produce",
            "shipper_address": "Toronto, ON",
            "consignee_name": "Southline Retail",
            "consignee_address": "Atlanta, GA",
            "carrier_name": "NorthStar Freight",
            "carrier_scac": "NSFT",
            "origin_port": "Toronto, ON",
            "destination_port": "Atlanta, GA",
            "mode": "LTL",
            "lane_code": "TOR-ATL-LTL",
            "etd": (today - timedelta(days=6)).isoformat(),
            "eta": (today - timedelta(days=3)).isoformat(),
            "cargo_description": "Fresh produce mix",
            "containers": "Reefer Pallets",
            "weight_kg": 8300,
            "volume_cbm": 27.1,
            "freight_rate": 2580.00,
            "currency": "USD",
            "incoterm": "DAP",
            "notes": "Delivered on time with signed POD.",
        },
        {
            "shipment_ref": "TMS-DEMO-005",
            "status": "Draft",
            "shipper_name": "Cobalt Commerce",
            "shipper_address": "Chicago, IL",
            "consignee_name": "Vertex Home Goods",
            "consignee_address": "Dallas, TX",
            "carrier_name": "BluePeak Logistics",
            "carrier_scac": "BPLG",
            "origin_port": "Chicago, IL",
            "destination_port": "Dallas, TX",
            "mode": "FTL",
            "lane_code": "CHI-DAL-FTL",
            "etd": (today + timedelta(days=4)).isoformat(),
            "eta": (today + timedelta(days=6)).isoformat(),
            "cargo_description": "Consumer packaged goods",
            "containers": "53' Dry Van",
            "weight_kg": 14200,
            "volume_cbm": 46.5,
            "freight_rate": 2995.00,
            "currency": "USD",
            "incoterm": "EXW",
            "notes": "Awaiting customer tender approval.",
        },
    ]


def get_db():
    os.makedirs(os.path.dirname(TMS_DB), exist_ok=True)
    conn = sqlite3.connect(TMS_DB, timeout=30, factory=TenantAwareConnection)
    _OPEN_DB_CONNECTIONS.add(conn)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    db_path = os.path.abspath(TMS_DB)
    temp_root = os.path.abspath(tempfile.gettempdir())
    journal_mode = "WAL"
    try:
        if os.path.commonpath([db_path, temp_root]) == temp_root:
            journal_mode = "DELETE"
    except ValueError:
        journal_mode = "WAL"
    conn.execute(f"PRAGMA journal_mode={journal_mode}")
    return conn


def close_open_connections():
    for conn in list(_OPEN_DB_CONNECTIONS):
        try:
            conn.close()
        except Exception:
            pass


def _table_columns(conn, table_name):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return bool(row)


def _all_table_names(conn):
    return {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def _tenant_table_names(conn):
    return sorted(_all_table_names(conn).intersection(TENANT_SCOPED_TABLES))


def _ensure_tenant_seed(conn, tenant_id=DEFAULT_TENANT_ID, company_name=DEFAULT_TENANT_NAME):
    conn.execute(
        """
        INSERT OR IGNORE INTO tenants
            (tenant_id, company_name, plan, max_users, data_region, session_timeout_minutes, allowed_ip_cidrs, status)
        VALUES (?, ?, 'starter', 5, ?, ?, '[]', 'active')
        """,
        (
            normalize_tenant_id(tenant_id),
            company_name,
            DEFAULT_TENANT_REGION,
            DEFAULT_TENANT_SESSION_TIMEOUT_MINUTES,
        ),
    )


def _migrate_tms_settings_table(conn):
    if not _table_exists(conn, "tms_settings"):
        return
    columns = _table_columns(conn, "tms_settings")
    if "tenant_id" in columns:
        return

    conn.execute("ALTER TABLE tms_settings RENAME TO tms_settings_legacy")
    conn.execute(
        """
        CREATE TABLE tms_settings (
            tenant_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (tenant_id, key)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO tms_settings (tenant_id, key, value)
        SELECT ?, key, value
        FROM tms_settings_legacy
        """,
        (DEFAULT_TENANT_ID,),
    )
    conn.execute("DROP TABLE tms_settings_legacy")


def _ensure_tenant_columns(conn):
    for table_name in _tenant_table_names(conn):
        if table_name in {"audit_log", "tenants", "tms_settings"}:
            continue
        columns = _table_columns(conn, table_name)
        if "tenant_id" not in columns:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"
            )
        conn.execute(
            f"UPDATE {table_name} SET tenant_id = ? WHERE COALESCE(TRIM(tenant_id), '') = ''",
            (DEFAULT_TENANT_ID,),
        )


def _tenant_json_expr(columns, row_alias):
    columns = sorted(columns)
    if not columns:
        return "json_object()"
    parts = []
    for column in columns:
        parts.append(f"'{column}'")
        parts.append(f"{row_alias}.{column}")
    return f"json_object({', '.join(parts)})"


def _audit_record_id_expr(columns, row_alias):
    candidates = [
        "id",
        "shipment_ref",
        "token",
        "booking_token",
        "response_token",
        "key",
        "location_name",
        "load_ref",
        "lane_code",
        "invoice_no",
        "license_number",
        "truck_number",
        "tenant_id",
    ]
    expressions = []
    for column in candidates:
        if column in columns:
            expressions.append(f"CAST({row_alias}.{column} AS TEXT)")
    return "COALESCE(" + ", ".join(expressions + ["''"]) + ")"


def _create_audit_triggers(conn):
    for table_name in _tenant_table_names(conn):
        if table_name == "audit_log":
            continue
        columns = _table_columns(conn, table_name)
        if not columns:
            continue
        record_new = _audit_record_id_expr(columns, "NEW")
        record_old = _audit_record_id_expr(columns, "OLD")
        snapshot_new = _tenant_json_expr(columns, "NEW")
        snapshot_old = _tenant_json_expr(columns, "OLD")
        for action in ("insert", "update", "delete"):
            conn.execute(f"DROP TRIGGER IF EXISTS audit_{table_name}_{action}")

        conn.executescript(
            f"""
            CREATE TRIGGER IF NOT EXISTS audit_{table_name}_insert
            AFTER INSERT ON {table_name}
            WHEN tenant_scope_disabled() = 0
            BEGIN
                INSERT INTO audit_log
                    (tenant_id, user_id, action, table_name, record_id, changes_json, ip)
                VALUES
                    (
                        COALESCE(NEW.tenant_id, current_tenant()),
                        current_audit_actor(),
                        'INSERT',
                        '{table_name}',
                        {record_new},
                        json_object('old', NULL, 'new', {snapshot_new}),
                        current_audit_ip()
                    );
            END;

            CREATE TRIGGER IF NOT EXISTS audit_{table_name}_update
            AFTER UPDATE ON {table_name}
            WHEN tenant_scope_disabled() = 0
            BEGIN
                INSERT INTO audit_log
                    (tenant_id, user_id, action, table_name, record_id, changes_json, ip)
                VALUES
                    (
                        COALESCE(NEW.tenant_id, OLD.tenant_id, current_tenant()),
                        current_audit_actor(),
                        'UPDATE',
                        '{table_name}',
                        {record_new},
                        json_object('old', {snapshot_old}, 'new', {snapshot_new}),
                        current_audit_ip()
                    );
            END;

            CREATE TRIGGER IF NOT EXISTS audit_{table_name}_delete
            AFTER DELETE ON {table_name}
            WHEN tenant_scope_disabled() = 0
            BEGIN
                INSERT INTO audit_log
                    (tenant_id, user_id, action, table_name, record_id, changes_json, ip)
                VALUES
                    (
                        COALESCE(OLD.tenant_id, current_tenant()),
                        current_audit_actor(),
                        'DELETE',
                        '{table_name}',
                        {record_old},
                        json_object('old', {snapshot_old}, 'new', NULL),
                        current_audit_ip()
                    );
            END;
            """
        )


def _ensure_multi_tenant_schema(conn):
    with disabled_tenant_scope():
        _migrate_tms_settings_table(conn)
        _ensure_tenant_columns(conn)

        tenant_columns = _table_columns(conn, "tenants")
        for column, definition in [
            ("company_name", "TEXT NOT NULL DEFAULT 'Default Tenant'"),
            ("plan", "TEXT NOT NULL DEFAULT 'starter'"),
            ("max_users", "INTEGER NOT NULL DEFAULT 5"),
            ("data_region", f"TEXT NOT NULL DEFAULT '{DEFAULT_TENANT_REGION}'"),
            ("session_timeout_minutes", f"INTEGER NOT NULL DEFAULT {DEFAULT_TENANT_SESSION_TIMEOUT_MINUTES}"),
            ("allowed_ip_cidrs", "TEXT NOT NULL DEFAULT '[]'"),
            ("saml_entity_id", "TEXT DEFAULT ''"),
            ("saml_sso_url", "TEXT DEFAULT ''"),
            ("saml_x509_cert", "TEXT DEFAULT ''"),
            ("saml_metadata_url", "TEXT DEFAULT ''"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            if column not in tenant_columns:
                conn.execute(f"ALTER TABLE tenants ADD COLUMN {column} {definition}")

        audit_columns = _table_columns(conn, "audit_log")
        for column, definition in [
            ("tenant_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_TENANT_ID}'"),
            ("user_id", "TEXT DEFAULT ''"),
            ("action", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
            ("table_name", "TEXT NOT NULL DEFAULT ''"),
            ("record_id", "TEXT"),
            ("changes_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("ip", "TEXT DEFAULT ''"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]:
            if column not in audit_columns:
                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {column} {definition}")

        _ensure_tenant_seed(conn)
        conn.execute(
            """
            UPDATE tenants
            SET plan = CASE
                    WHEN lower(COALESCE(plan, '')) IN ('starter', 'pro', 'enterprise') THEN lower(plan)
                    ELSE 'starter'
                END,
                max_users = CASE
                    WHEN COALESCE(max_users, 0) > 0 THEN max_users
                    ELSE 5
                END,
                data_region = COALESCE(NULLIF(TRIM(data_region), ''), ?),
                session_timeout_minutes = CASE
                    WHEN COALESCE(session_timeout_minutes, 0) >= 5 THEN session_timeout_minutes
                    ELSE ?
                END,
                allowed_ip_cidrs = COALESCE(NULLIF(TRIM(allowed_ip_cidrs), ''), '[]'),
                status = CASE
                    WHEN lower(COALESCE(status, '')) IN ('active', 'suspended', 'deleted') THEN lower(status)
                    ELSE 'active'
                END,
                updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
            """,
            (DEFAULT_TENANT_REGION, DEFAULT_TENANT_SESSION_TIMEOUT_MINUTES),
        )

        for table_name in _tenant_table_names(conn):
            if table_name in {"tms_settings"}:
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_tms_settings_tenant_key ON tms_settings(tenant_id, key)"
                )
                continue
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name}_tenant_id ON {table_name}(tenant_id)"
            )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_lookup ON audit_log(tenant_id, created_at DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log(user_id, action)")
        _create_audit_triggers(conn)


def _normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_portal_token(value):
    return _normalize_text(value).upper()


def _normalize_scac(value):
    scac = _normalize_text(value).upper()
    return scac or None


def _normalize_edi_format(value):
    edi_format = _normalize_text(value).upper() or "X12"
    if edi_format not in EDI_PARTNER_FORMATS:
        raise ValueError("EDI format must be X12 or EDIFACT.")
    return edi_format


def _normalize_edi_direction(value):
    direction = _normalize_text(value).lower() or "inbound"
    if direction not in EDI_PARTNER_DIRECTIONS:
        raise ValueError("EDI direction must be inbound, outbound, or both.")
    return direction


def _normalize_dot_number(value):
    digits = "".join(character for character in _normalize_text(value) if character.isdigit())
    return digits or None


def _dedupe_shipment_refs(shipment_refs):
    deduped = []
    seen = set()
    for ref in shipment_refs or []:
        clean_ref = _normalize_text(ref)
        if not clean_ref or clean_ref in seen:
            continue
        deduped.append(clean_ref)
        seen.add(clean_ref)
    return deduped


def _deserialize_shipment_refs(raw_value):
    if isinstance(raw_value, list):
        return _dedupe_shipment_refs(raw_value)

    value = _normalize_text(raw_value)
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = [part.strip() for part in value.split(",")]

    if not isinstance(parsed, list):
        return []
    return _dedupe_shipment_refs(parsed)


def _serialize_shipment_refs(shipment_refs):
    return json.dumps(_dedupe_shipment_refs(shipment_refs))


def _dedupe_permissions(permissions):
    deduped = []
    seen = set()
    for permission in permissions or []:
        clean_permission = _normalize_text(permission).lower()
        if not clean_permission or clean_permission in seen:
            continue
        deduped.append(clean_permission)
        seen.add(clean_permission)
    return deduped


def _deserialize_permissions(raw_value):
    if isinstance(raw_value, list):
        return _dedupe_permissions(raw_value)

    value = _normalize_text(raw_value)
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = [part.strip() for part in value.split(",")]

    if isinstance(parsed, str):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []
    return _dedupe_permissions(parsed)


def _serialize_permissions(permissions):
    return json.dumps(_dedupe_permissions(permissions))


def _portal_pin_for_token(token):
    digits = "".join(character for character in token if character.isdigit())
    if len(digits) >= 6:
        return digits[-6:]

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{int(digest[:12], 16) % 1_000_000:06d}"


def _parse_portal_datetime(value):
    raw_value = _normalize_text(value)
    if not raw_value:
        return None
    if raw_value.endswith("Z"):
        raw_value = f"{raw_value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        try:
            parsed = datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _default_portal_token_expiry(created_at=None):
    base_time = _parse_portal_datetime(created_at) or datetime.utcnow()
    return (base_time + timedelta(days=30)).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _portal_token_is_active(portal_token):
    if not portal_token:
        return False
    expires_at = _parse_portal_datetime(portal_token.get("expires_at"))
    if not expires_at:
        return True
    return expires_at >= datetime.utcnow()


def _portal_row_to_dict(row):
    if not row:
        return None

    portal_token = dict(row)
    portal_token["token"] = _normalize_portal_token(portal_token.get("token"))
    portal_token["shipment_refs"] = _deserialize_shipment_refs(portal_token.get("shipment_refs"))
    portal_token["expires_at"] = _normalize_text(portal_token.get("expires_at"))
    portal_token["pin"] = _portal_pin_for_token(portal_token["token"])
    portal_token["is_active"] = _portal_token_is_active(portal_token)
    return portal_token


def _portal_quote_request_reference(request_id):
    try:
        request_number = int(request_id)
    except (TypeError, ValueError):
        request_number = 0
    return f"PQR-{request_number:06d}"


def _normalize_portal_quote_request_status(value):
    status = _normalize_text(value).lower() or "pending"
    if status not in PORTAL_QUOTE_REQUEST_STATUS_STYLES:
        raise ValueError("Portal quote request status is invalid.")
    return status


def _equipment_label(value):
    equipment_type = _normalize_text(value)
    if not equipment_type:
        return ""
    equipment = EQUIPMENT_TYPES.get(equipment_type)
    if equipment:
        return equipment.get("label") or equipment_type.replace("_", " ").title()
    return equipment_type.replace("_", " ").title()


def _portal_quote_request_row_to_dict(row):
    if not row:
        return None

    portal_request = dict(row)
    portal_request["portal_token"] = _normalize_portal_token(portal_request.get("portal_token"))
    portal_request["customer_name"] = _normalize_text(portal_request.get("customer_name"))
    portal_request["customer_email"] = _normalize_text(portal_request.get("customer_email"))
    portal_request["origin"] = _normalize_text(portal_request.get("origin"))
    portal_request["destination"] = _normalize_text(portal_request.get("destination"))
    portal_request["cargo_description"] = _normalize_text(portal_request.get("cargo_description"))
    portal_request["equipment_type"] = _normalize_text(portal_request.get("equipment_type"))
    portal_request["equipment_label"] = _equipment_label(portal_request["equipment_type"])
    portal_request["notes"] = _normalize_text(portal_request.get("notes"))
    portal_request["status"] = _normalize_portal_quote_request_status(portal_request.get("status"))
    portal_request["status_label"] = portal_request["status"].title()
    portal_request["status_variant"] = PORTAL_QUOTE_REQUEST_STATUS_STYLES.get(portal_request["status"], "secondary")
    portal_request["reference"] = _portal_quote_request_reference(portal_request.get("id"))
    portal_request["route_label"] = " -> ".join(
        part for part in (portal_request["origin"], portal_request["destination"]) if part
    ) or "Route pending"
    portal_request["quoted_rate_display"] = (
        f"${portal_request['quoted_rate']:,.2f}"
        if portal_request.get("quoted_rate") is not None
        else ""
    )
    return portal_request


def _normalize_lane_value(value):
    return re.sub(r"\s+", " ", _normalize_text(value))


def _normalize_mode(value):
    return re.sub(r"\s+", " ", _normalize_text(value))


def normalize_carbon_mode(value):
    clean_mode = _normalize_mode(value).lower()
    if not clean_mode:
        return None

    condensed = clean_mode.replace(" ", "")
    tokens = set(re.findall(r"[a-z0-9]+", clean_mode))
    if {"ocean", "sea", "vessel"} & tokens or condensed in {"fcl", "lcl"}:
        return "ocean"
    if {"air", "airfreight"} & tokens or condensed in {"aircargo", "airfreight"}:
        return "air"
    if {"rail", "train"} & tokens:
        return "rail"
    if condensed in {"ftl", "ltl", "road", "truck", "trucking", "dray", "drayage"}:
        return "road"
    if {"road", "truck", "trucking", "dray", "drayage"} & tokens:
        return "road"
    return None


def _normalize_currency(value):
    currency = _normalize_text(value).upper()
    return currency or "USD"


def _fmcsa_web_key():
    return _normalize_text(os.environ.get("FMCSA_WEB_KEY") or os.environ.get("FMCSA_KEY"))


def _normalize_safety_rating(value):
    rating = _normalize_text(value).lower()
    if rating == "satisfactory":
        return "Satisfactory"
    if rating == "conditional":
        return "Conditional"
    if rating == "unsatisfactory":
        return "Unsatisfactory"
    return ""


def _safety_badge_class(rating):
    normalized = _normalize_safety_rating(rating)
    return {
        "Satisfactory": "success",
        "Conditional": "warning",
        "Unsatisfactory": "danger",
    }.get(normalized, "secondary")


def _parse_mmddyyyy_date(value):
    raw = _normalize_text(value)
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    parsed = _parse_tracking_datetime(raw)
    return parsed.date() if parsed else None


def _extract_fmcsa_values(payload):
    values = []

    def _walk(item, parent_key=""):
        if isinstance(item, dict):
            for key, value in item.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                _walk(value, normalized_key or parent_key)
        elif isinstance(item, list):
            for entry in item:
                _walk(entry, parent_key)
        else:
            values.append((parent_key, item))

    _walk(payload)
    return values


def _first_fmcsa_value(payload, *key_patterns):
    normalized_patterns = [re.sub(r"[^a-z0-9]", "", pattern.lower()) for pattern in key_patterns if pattern]
    if not normalized_patterns:
        return ""

    for key, value in _extract_fmcsa_values(payload):
        if any(pattern in key for pattern in normalized_patterns):
            clean_value = _normalize_text(value)
            if clean_value:
                return clean_value
    return ""


def _extract_fmcsa_safety_rating(payload):
    rating = _normalize_safety_rating(
        _first_fmcsa_value(
            payload,
            "safetyrating",
            "ratingvalue",
            "safetyratingcode",
            "reviewrating",
        )
    )
    if rating:
        return rating

    for _, value in _extract_fmcsa_values(payload):
        clean_value = _normalize_safety_rating(value)
        if clean_value:
            return clean_value
    return ""


def _extract_fmcsa_auth_status(payload):
    status = _first_fmcsa_value(
        payload,
        "commonauthoritystatus",
        "contractauthoritystatus",
        "brokerauthoritystatus",
        "authstatus",
        "authoritystatus",
    )
    if status:
        return status

    allow_to_operate = _first_fmcsa_value(payload, "allowtooperate")
    if allow_to_operate.upper() == "Y":
        return "Authorized"
    if allow_to_operate.upper() == "N":
        return "Not Authorized"
    return ""


def _extract_fmcsa_insurance_status(payload):
    status = _first_fmcsa_value(
        payload,
        "insurancestatus",
        "insuranceonfile",
        "bipdinsuranceonfile",
        "cargoonfile",
        "insproperty",
    )
    if status:
        return status

    insurance_required = _first_fmcsa_value(payload, "insurancerequired", "bipdinsurancerequired")
    if insurance_required.upper() == "Y":
        return "On File"
    return ""


def _extract_fmcsa_insurance_expiry(payload):
    for candidate in [
        _first_fmcsa_value(payload, "insuranceexpirationdate"),
        _first_fmcsa_value(payload, "insuranceexpirydate"),
        _first_fmcsa_value(payload, "insuranceto"),
        _first_fmcsa_value(payload, "insuranceeffectiveto"),
        _first_fmcsa_value(payload, "bipdinsuranceto"),
    ]:
        parsed = _parse_mmddyyyy_date(candidate)
        if parsed:
            return parsed.isoformat()
    return ""


def _decorate_carrier_row(row):
    if not row:
        return None

    carrier = dict(row)
    carrier["dot_number"] = _normalize_dot_number(carrier.get("dot_number")) or ""
    carrier["safety_rating"] = _normalize_safety_rating(carrier.get("safety_rating"))
    carrier["safety_badge_class"] = _safety_badge_class(carrier.get("safety_rating"))
    carrier["last_checked_display"] = _format_tracking_datetime(carrier.get("last_checked"))
    carrier["insurance_expires_display"] = _format_tracking_datetime(carrier.get("insurance_expires_at"))
    carrier["insurance_expires_soon"] = False
    carrier["insurance_expired"] = False
    carrier["insurance_alert"] = ""
    expires_on = _parse_mmddyyyy_date(carrier.get("insurance_expires_at"))
    if expires_on:
        days_remaining = (expires_on - datetime.utcnow().date()).days
        carrier["insurance_expired"] = days_remaining < 0
        carrier["insurance_expires_soon"] = days_remaining <= 30
        if days_remaining < 0:
            carrier["insurance_alert"] = f"Insurance expired on {expires_on.isoformat()}."
        elif days_remaining == 0:
            carrier["insurance_alert"] = "Insurance expires today."
        elif days_remaining <= 30:
            carrier["insurance_alert"] = f"Insurance expires in {days_remaining} day{'s' if days_remaining != 1 else ''}."
    return carrier


def _parse_iso_date(value, label):
    raw = _normalize_text(value)
    if not raw:
        raise ValueError(f"{label} is required.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date in YYYY-MM-DD format.") from exc


def _parse_optional_amount(value, label):
    raw = _normalize_text(value)
    if raw == "":
        return None
    try:
        amount = round(float(raw), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if amount <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return amount


def _parse_required_amount(value, label):
    amount = _parse_optional_amount(value, label)
    if amount is None:
        raise ValueError(f"{label} is required.")
    return amount


def _normalize_claim_type(value):
    claim_type = _normalize_text(value).title()
    if claim_type not in CLAIM_TYPES:
        allowed = ", ".join(CLAIM_TYPES)
        raise ValueError(f"Claim type must be one of: {allowed}.")
    return claim_type


def _normalize_claim_status(value):
    claim_status = _normalize_text(value)
    if claim_status not in CLAIM_STATUSES:
        allowed = ", ".join(CLAIM_STATUSES)
        raise ValueError(f"Claim status must be one of: {allowed}.")
    return claim_status


def _generate_claim_response_token(conn):
    while True:
        token = secrets.token_urlsafe(24)
        exists = conn.execute(
            "SELECT 1 FROM freight_claims WHERE response_token = ? LIMIT 1",
            (token,),
        ).fetchone()
        if not exists:
            return token


def _parse_non_negative_number(value, label):
    raw = _normalize_text(value)
    if raw == "":
        return 0.0
    try:
        amount = round(float(raw), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if amount < 0:
        raise ValueError(f"{label} cannot be negative.")
    return amount


def _normalize_choice(value, options, label, default):
    clean_value = _normalize_text(value) or default
    if clean_value not in options:
        raise ValueError(f"{label} must be one of: {', '.join(options)}.")
    return clean_value


def _normalize_driver_status(value):
    return _normalize_choice(value, DRIVER_STATUS_OPTIONS, "Driver status", "Active")


def _normalize_vehicle_status(value):
    return _normalize_choice(value, VEHICLE_STATUS_OPTIONS, "Vehicle status", "Active")


def _normalize_duty_status(value):
    return _normalize_choice(value, DUTY_STATUS_OPTIONS, "Duty status", "Driving")


def _normalize_dock_type(value):
    clean_value = _normalize_text(value).lower() or "both"
    if clean_value not in DOCK_TYPES:
        raise ValueError("Dock type must be inbound, outbound, or both.")
    return clean_value


def _normalize_dock_appointment_type(value):
    clean_value = _normalize_text(value).lower() or "inbound"
    if clean_value not in DOCK_APPOINTMENT_TYPES:
        raise ValueError("Appointment type must be inbound or outbound.")
    return clean_value


def _normalize_dock_appointment_status(value):
    clean_value = _normalize_text(value) or "Scheduled"
    if clean_value not in DOCK_APPOINTMENT_STATUSES:
        raise ValueError(
            "Appointment status must be one of: "
            + ", ".join(DOCK_APPOINTMENT_STATUSES)
            + "."
        )
    return clean_value


def _parse_duration_minutes(value, label="Duration"):
    raw = _normalize_text(value)
    if not raw:
        return 60
    if not raw.isdigit():
        raise ValueError(f"{label} must be a whole number of minutes.")
    parsed = int(raw)
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    if parsed > 12 * 60:
        raise ValueError(f"{label} must be 720 minutes or less.")
    return parsed


def _parse_dock_datetime(value, label):
    raw = _normalize_text(value)
    if not raw:
        raise ValueError(f"{label} is required.")

    for candidate in (raw, raw.replace("T", " ")):
        try:
            parsed = datetime.fromisoformat(candidate)
            break
        except ValueError:
            parsed = None

    if parsed is None:
        raise ValueError(f"{label} must be a valid date and time.")

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(second=0, microsecond=0)


def _serialize_dock(row):
    dock = dict(row)
    dock["default_duration_minutes"] = int(dock.get("default_duration_minutes") or 60)
    dock["active"] = 1 if dock.get("active", 1) else 0
    dock["type_label"] = dock.get("dock_type", "both").title()
    dock["duration_label"] = f"{dock['default_duration_minutes']} min"
    return dock


def _format_dock_datetime(value):
    parsed = _parse_tracking_datetime(value)
    if not parsed:
        return "-"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _hydrate_dock_appointment_row(row):
    if not row:
        return None

    appointment = dict(row)
    appointment["duration_minutes"] = int(appointment.get("duration_minutes") or 60)
    appointment["status_class"] = DOCK_APPOINTMENT_STATUS_STYLES.get(
        appointment.get("status"),
        "secondary",
    )
    appointment["appointment_type_label"] = (
        appointment.get("appointment_type") or "inbound"
    ).title()
    appointment["dock_type_label"] = (appointment.get("dock_type") or "both").title()
    appointment["has_schedule"] = bool(appointment.get("scheduled_start") and appointment.get("scheduled_end"))
    appointment["scheduled_start_display"] = _format_dock_datetime(appointment.get("scheduled_start"))
    appointment["scheduled_end_display"] = _format_dock_datetime(appointment.get("scheduled_end"))
    appointment["schedule_label"] = (
        f"{appointment['scheduled_start_display']} to {appointment['scheduled_end_display']}"
        if appointment["has_schedule"]
        else "Carrier link created, slot not booked yet"
    )

    start_dt = _parse_tracking_datetime(appointment.get("scheduled_start"))
    if start_dt and start_dt.tzinfo is not None:
        start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
    appointment["scheduled_start_dt"] = start_dt
    appointment["schedule_date_key"] = start_dt.date().isoformat() if start_dt else ""
    appointment["schedule_time_label"] = start_dt.strftime("%H:%M") if start_dt else ""
    appointment["carrier_display"] = (
        appointment.get("carrier_name")
        or appointment.get("shipment_carrier_name")
        or appointment.get("shipper_name")
        or "-"
    )
    return appointment


def _parse_datetime_value(value, label):
    raw = _normalize_text(value)
    if not raw:
        raise ValueError(f"{label} is required.")
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date/time.") from exc


def _format_datetime_input(value):
    parsed = _parse_tracking_datetime(value)
    if not parsed:
        return ""
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _generate_driver_token(conn):
    for _ in range(20):
        token = f"drv-{secrets.token_urlsafe(12)}"
        exists = conn.execute(
            "SELECT 1 FROM drivers WHERE checkin_token = ?",
            (token,),
        ).fetchone()
        if not exists:
            return token
    raise RuntimeError("Unable to generate a unique driver check-in token.")


def _generate_pod_token(conn):
    for _ in range(20):
        token = secrets.token_urlsafe(18)
        exists = conn.execute(
            "SELECT 1 FROM shipments WHERE pod_token = ?",
            (token,),
        ).fetchone()
        if not exists:
            return token
    raise RuntimeError("Unable to generate a unique POD token.")


def _coerce_lookup_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _normalize_text(value)
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ValueError("Lookup date must be a valid date in YYYY-MM-DD format.") from exc


def _contract_rate_priority(containers):
    container_text = _normalize_text(containers).upper().replace(" ", "")
    if "40HC" in container_text or "40HQ" in container_text or "HC" in container_text:
        return ("rate_40hc", "rate_40ft", "rate_20ft")
    if "40" in container_text:
        return ("rate_40ft", "rate_40hc", "rate_20ft")
    if "20" in container_text:
        return ("rate_20ft", "rate_40ft", "rate_40hc")
    return ("rate_20ft", "rate_40ft", "rate_40hc")


def _resolve_contract_rate_amount(rate_row, containers=""):
    preferred_fields = _contract_rate_priority(containers)
    if _normalize_text(containers):
        for field_name in preferred_fields:
            value = rate_row.get(field_name)
            if value is not None:
                return field_name, round(float(value), 2)

    available = [
        (field_name, round(float(rate_row[field_name]), 2))
        for field_name in CONTRACT_RATE_LABELS
        if rate_row.get(field_name) is not None
    ]
    if not available:
        return None, None
    return min(available, key=lambda item: item[1])


def _build_contract_rate_row(row, containers="", reference_date=None):
    contract_rate = dict(row)
    matched_field, matched_rate = _resolve_contract_rate_amount(contract_rate, containers)
    lookup_date = _coerce_lookup_date(reference_date)
    valid_from = _coerce_lookup_date(contract_rate.get("valid_from"))
    valid_to = _coerce_lookup_date(contract_rate.get("valid_to"))
    contract_rate["matched_rate_field"] = matched_field
    contract_rate["matched_rate_label"] = CONTRACT_RATE_LABELS.get(matched_field, "Best")
    contract_rate["matched_rate"] = matched_rate
    contract_rate["is_active"] = valid_from <= lookup_date <= valid_to
    if lookup_date < valid_from:
        contract_rate["status_label"] = "Future"
        contract_rate["status_class"] = "info"
    elif lookup_date > valid_to:
        contract_rate["status_label"] = "Expired"
        contract_rate["status_class"] = "secondary"
    else:
        contract_rate["status_label"] = "Active"
        contract_rate["status_class"] = "success"
    contract_rate["lane_label"] = f"{contract_rate['origin']} -> {contract_rate['destination']}"
    return contract_rate


def _upsert_setting(conn, key, value):
    existing = conn.execute(
        "SELECT key FROM tms_settings WHERE key = ?",
        (key,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE tms_settings SET value = ? WHERE key = ?",
            (value, key),
        )
    else:
        conn.execute(
            "INSERT INTO tms_settings (key, value) VALUES (?, ?)",
            (key, value),
        )


def _get_settings(conn):
    settings = DEFAULT_SETTINGS.copy()
    for row in conn.execute("SELECT key, value FROM tms_settings").fetchall():
        settings[row["key"]] = _decode_secure_setting(row["key"], row["value"])
    return settings


def _normalize_color(value):
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_SETTINGS["primary_color"]
    if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", raw):
        raise ValueError("Primary color must be a 6-digit hex value.")
    return f"#{raw.lstrip('#').lower()}"


def _encode_logo(logo_file):
    if not logo_file or not getattr(logo_file, "filename", ""):
        return None

    mime_type = (getattr(logo_file, "mimetype", "") or "").strip().lower()
    if not mime_type.startswith("image/"):
        raise ValueError("Logo upload must be an image file.")

    blob = logo_file.read()
    if not blob:
        return None
    if len(blob) > 2 * 1024 * 1024:
        raise ValueError("Logo upload must be 2 MB or smaller.")

    encoded = base64.b64encode(blob).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _rebuild_legacy_docks_table(conn):
    legacy_rows = conn.execute("SELECT * FROM docks").fetchall()
    conn.execute("DROP TABLE IF EXISTS docks_legacy")
    conn.execute("ALTER TABLE docks RENAME TO docks_legacy")
    conn.execute(
        """
        CREATE TABLE docks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            dock_type TEXT NOT NULL DEFAULT 'both',
            location TEXT DEFAULT '',
            default_duration_minutes INTEGER NOT NULL DEFAULT 60,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for row in legacy_rows:
        legacy = dict(row)
        name = _normalize_text(legacy.get("name")) or _normalize_text(legacy.get("dock_name")) or "Dock"
        dock_type = _normalize_text(legacy.get("dock_type")).lower()
        if dock_type not in DOCK_TYPES:
            dock_type = "both"
        active = 0 if _normalize_text(legacy.get("status")).lower() in {"inactive", "disabled"} else 1
        conn.execute(
            """
            INSERT INTO docks
                (id, name, dock_type, location, default_duration_minutes, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 60, ?, ?, ?)
            """,
            (
                legacy.get("id"),
                name,
                dock_type,
                _normalize_text(legacy.get("location")),
                active,
                legacy.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                legacy.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
    conn.execute("DROP TABLE IF EXISTS docks_legacy")


def _rebuild_legacy_dock_appointments_table(conn):
    legacy_rows = conn.execute(
        """
        SELECT *
        FROM dock_appointments
        ORDER BY datetime(COALESCE(created_at, appt_date || ' ' || appt_time)) DESC, id DESC
        """
    ).fetchall()
    conn.execute("DROP TABLE IF EXISTS dock_appointments_legacy")
    conn.execute("ALTER TABLE dock_appointments RENAME TO dock_appointments_legacy")
    conn.execute(
        """
        CREATE TABLE dock_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT UNIQUE,
            dock_id INTEGER,
            booking_token TEXT UNIQUE NOT NULL,
            appointment_type TEXT NOT NULL DEFAULT 'inbound',
            status TEXT NOT NULL DEFAULT 'Scheduled',
            scheduled_start TIMESTAMP,
            scheduled_end TIMESTAMP,
            duration_minutes INTEGER NOT NULL DEFAULT 60,
            carrier_name TEXT DEFAULT '',
            contact_name TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            booked_by TEXT DEFAULT 'dispatch',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE,
            FOREIGN KEY (dock_id) REFERENCES docks(id) ON DELETE SET NULL
        )
        """
    )

    seen_refs = set()
    for row in legacy_rows:
        legacy = dict(row)
        shipment_ref = _normalize_text(legacy.get("shipment_ref"))
        if shipment_ref:
            shipment_key = shipment_ref.upper()
            if shipment_key in seen_refs:
                continue
            seen_refs.add(shipment_key)

        legacy_type = _normalize_text(legacy.get("appointment_type") or legacy.get("appt_type")).lower()
        appointment_type = "outbound" if legacy_type in {"pickup", "outbound"} else "inbound"

        legacy_status = _normalize_text(legacy.get("status")).lower()
        status = {
            "scheduled": "Scheduled",
            "checked-in": "Checked-In",
            "checked_in": "Checked-In",
            "loading": "Loading",
            "complete": "Complete",
            "completed": "Complete",
            "no-show": "No-Show",
            "no_show": "No-Show",
        }.get(legacy_status, "Scheduled")

        start_source = _normalize_text(legacy.get("scheduled_start"))
        if not start_source:
            appt_date = _normalize_text(legacy.get("appt_date"))
            appt_time = _normalize_text(legacy.get("appt_time"))
            if appt_date and appt_time:
                start_source = f"{appt_date} {appt_time}"
        start_dt = _parse_tracking_datetime(start_source)
        if start_dt and start_dt.tzinfo is not None:
            start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)
        duration_minutes = int(legacy.get("duration_minutes") or 60)
        end_dt = start_dt + timedelta(minutes=duration_minutes) if start_dt else None

        conn.execute(
            """
            INSERT INTO dock_appointments
                (id, shipment_ref, dock_id, booking_token, appointment_type, status, scheduled_start, scheduled_end,
                 duration_minutes, carrier_name, notes, booked_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'dispatch', ?, ?)
            """,
            (
                legacy.get("id"),
                shipment_ref or None,
                legacy.get("dock_id"),
                _normalize_text(legacy.get("booking_token")) or secrets.token_urlsafe(18),
                appointment_type,
                status,
                start_dt.strftime("%Y-%m-%d %H:%M:%S") if start_dt else None,
                end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else None,
                duration_minutes if duration_minutes > 0 else 60,
                _normalize_text(legacy.get("carrier_name")),
                _normalize_text(legacy.get("notes")),
                legacy.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                legacy.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    conn.execute("DROP TABLE IF EXISTS dock_appointments_legacy")


def init_tms_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'starter',
            max_users INTEGER NOT NULL DEFAULT 5,
            data_region TEXT NOT NULL DEFAULT 'ca-central',
            session_timeout_minutes INTEGER NOT NULL DEFAULT 30,
            allowed_ip_cidrs TEXT NOT NULL DEFAULT '[]',
            saml_entity_id TEXT DEFAULT '',
            saml_sso_url TEXT DEFAULT '',
            saml_x509_cert TEXT DEFAULT '',
            saml_metadata_url TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            user_id TEXT DEFAULT '',
            action TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id TEXT,
            changes_json TEXT NOT NULL DEFAULT '{}',
            ip TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'Draft',
            customer_name TEXT DEFAULT '',
            shipper_name TEXT,
            shipper_address TEXT,
            consignee_name TEXT,
            consignee_address TEXT,
            carrier_name TEXT,
            carrier_id INTEGER,
            origin_port TEXT,
            destination_port TEXT,
            etd DATE,
            eta DATE,
            cargo_description TEXT,
            containers TEXT,
            weight_kg REAL,
            volume_cbm REAL,
            freight_rate REAL,
            currency TEXT DEFAULT 'USD',
            incoterm TEXT DEFAULT 'FOB',
            pod_token TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shipment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT,
            location TEXT,
            event_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by TEXT DEFAULT 'system',
            FOREIGN KEY (shipment_id) REFERENCES shipments(id)
        );

        CREATE TABLE IF NOT EXISTS tms_carriers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            scac TEXT UNIQUE,
            dot_number TEXT,
            country TEXT DEFAULT '',
            contact_email TEXT,
            contact_phone TEXT,
            safety_rating TEXT DEFAULT '',
            insurance_status TEXT DEFAULT '',
            auth_status TEXT DEFAULT '',
            insurance_expires_at DATE,
            last_checked TIMESTAMP,
            fmcsa_source_url TEXT DEFAULT '',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            license_number TEXT NOT NULL,
            phone TEXT DEFAULT '',
            country TEXT DEFAULT '',
            status TEXT DEFAULT 'Active',
            checkin_token TEXT UNIQUE,
            last_location TEXT DEFAULT '',
            last_issue TEXT DEFAULT '',
            last_checkin_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_number TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            capacity_weight REAL DEFAULT 0,
            capacity_cbm REAL DEFAULT 0,
            country TEXT DEFAULT '',
            status TEXT DEFAULT 'Active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS duty_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            shipment_id INTEGER,
            duty_status TEXT NOT NULL,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP NOT NULL,
            hours_logged REAL NOT NULL DEFAULT 0,
            exceeds_driving_limit INTEGER DEFAULT 0,
            location TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers(id) ON DELETE CASCADE,
            FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS tms_lanes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lane_code TEXT UNIQUE NOT NULL,
            origin_name TEXT NOT NULL,
            destination_name TEXT NOT NULL,
            mode TEXT DEFAULT 'FTL',
            avg_transit_days INTEGER DEFAULT 0,
            weekly_shipments INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER,
            carrier_id INTEGER,
            rate_20ft REAL,
            rate_40ft REAL,
            rate_40hc REAL,
            valid_until DATE,
            status TEXT DEFAULT 'Pending',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_id) REFERENCES shipments(id)
        );

        CREATE TABLE IF NOT EXISTS spot_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            weight_lbs REAL,
            equipment_type TEXT NOT NULL,
            pickup_date DATE,
            delivery_date DATE,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'awarded', 'cancelled')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default'
        );

        CREATE TABLE IF NOT EXISTS spot_quote_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quote_id INTEGER NOT NULL,
            carrier_name TEXT NOT NULL,
            carrier_email TEXT,
            rate_20ft REAL,
            rate_40ft REAL,
            transit_days INTEGER,
            validity_date DATE,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'awarded', 'rejected')),
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            FOREIGN KEY (quote_id) REFERENCES spot_quotes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_spot_quotes_status_created
            ON spot_quotes(tenant_id, status, created_at DESC, id DESC);

        CREATE INDEX IF NOT EXISTS idx_spot_quote_responses_quote
            ON spot_quote_responses(tenant_id, quote_id, status, received_at DESC, id DESC);

        CREATE TABLE IF NOT EXISTS carrier_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            carrier_name TEXT NOT NULL,
            invoice_no TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL DEFAULT 'Pending',
            variance_pct REAL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customer_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            exchange_rate REAL DEFAULT 1,
            status TEXT DEFAULT 'Draft',
            due_date DATE,
            paid_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS freight_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            carrier_id INTEGER,
            claim_type TEXT NOT NULL,
            description TEXT NOT NULL,
            claimed_amount REAL NOT NULL,
            settlement_amount REAL,
            currency TEXT NOT NULL DEFAULT 'USD',
            status TEXT NOT NULL DEFAULT 'Filed',
            evidence_path TEXT DEFAULT '',
            settled_at TIMESTAMP,
            carrier_notes TEXT DEFAULT '',
            counter_offer REAL,
            response_token TEXT UNIQUE,
            responded_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref),
            FOREIGN KEY (carrier_id) REFERENCES tms_carriers(id)
        );

        CREATE TABLE IF NOT EXISTS tenders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id INTEGER NOT NULL,
            deadline_at TIMESTAMP NOT NULL,
            notes TEXT,
            status TEXT DEFAULT 'Open',
            awarded_response_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_id) REFERENCES shipments(id)
        );

        CREATE TABLE IF NOT EXISTS tender_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tender_id INTEGER NOT NULL,
            carrier_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            response_status TEXT DEFAULT 'Pending',
            rate_20ft REAL,
            rate_40ft REAL,
            rate_40hc REAL,
            transit_days INTEGER,
            notes TEXT,
            submitted_at TIMESTAMP,
            awarded_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tender_id) REFERENCES tenders(id),
            FOREIGN KEY (carrier_id) REFERENCES tms_carriers(id)
        );

        CREATE TABLE IF NOT EXISTS contract_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            mode TEXT NOT NULL,
            rate_20ft REAL,
            rate_40ft REAL,
            rate_40hc REAL,
            currency TEXT DEFAULT 'USD',
            valid_from DATE NOT NULL,
            valid_to DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS loads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            load_ref TEXT UNIQUE NOT NULL,
            carrier_id INTEGER,
            status TEXT DEFAULT 'Planning',
            total_weight REAL DEFAULT 0,
            total_cbm REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (carrier_id) REFERENCES tms_carriers(id)
        );

        CREATE TABLE IF NOT EXISTS load_shipments (
            load_id INTEGER NOT NULL,
            shipment_ref TEXT NOT NULL UNIQUE,
            PRIMARY KEY (load_id, shipment_ref),
            FOREIGN KEY (load_id) REFERENCES loads(id) ON DELETE CASCADE,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS loadboard_posts (
            shipment_ref TEXT PRIMARY KEY,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            status TEXT DEFAULT 'Active',
            views INTEGER DEFAULT 0,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tracking_pings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            speed REAL,
            timestamp TIMESTAMP NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tracking_driver_tokens (
            token TEXT PRIMARY KEY,
            shipment_ref TEXT UNIQUE NOT NULL,
            carrier_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS location_geocodes (
            location_name TEXT PRIMARY KEY,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            display_name TEXT,
            source_url TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tms_settings (
            tenant_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (tenant_id, key)
        );
        CREATE TABLE IF NOT EXISTS portal_tokens (
            token TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            email TEXT DEFAULT '',
            shipment_refs TEXT DEFAULT '[]',
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS portal_quote_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            portal_token TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            cargo_description TEXT NOT NULL,
            weight_kg REAL,
            volume_cbm REAL,
            equipment_type TEXT DEFAULT '',
            pickup_date DATE,
            delivery_date DATE,
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'quoted', 'booked', 'cancelled')),
            quoted_rate REAL,
            quoted_by TEXT DEFAULT '',
            quoted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            key TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            permissions TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tms_integrations (
            id TEXT PRIMARY KEY,
            name TEXT,
            category TEXT,
            status TEXT DEFAULT 'disconnected',
            credentials_json TEXT DEFAULT '{}',
            connected_at TEXT,
            last_sync TEXT,
            error_msg TEXT
        );
        CREATE TABLE IF NOT EXISTS tms_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            extracted_json TEXT NOT NULL,
            shipment_ref TEXT,
            status TEXT DEFAULT 'reviewed',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pod_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL UNIQUE,
            recipient_name TEXT NOT NULL,
            signature_data TEXT NOT NULL,
            photo_path TEXT,
            delivered_at TIMESTAMP NOT NULL,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS intake_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text TEXT NOT NULL,
            extracted_json TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            shipment_ref TEXT,
            status TEXT DEFAULT 'processed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS edi_partners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            isa_id TEXT NOT NULL,
            format TEXT NOT NULL DEFAULT 'X12',
            direction TEXT NOT NULL DEFAULT 'inbound',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS edi_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL,
            type TEXT NOT NULL,
            format TEXT NOT NULL DEFAULT 'X12',
            raw TEXT NOT NULL,
            parsed_json TEXT NOT NULL DEFAULT '{}',
            shipment_ref TEXT,
            partner_id INTEGER,
            filename TEXT DEFAULT '',
            source_path TEXT DEFAULT '',
            status TEXT DEFAULT 'received',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (partner_id) REFERENCES edi_partners(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS customs_declarations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL UNIQUE,
            hs_code TEXT DEFAULT '',
            country_of_origin TEXT DEFAULT '',
            declared_value REAL DEFAULT 0,
            currency TEXT DEFAULT 'USD',
            export_license_required INTEGER DEFAULT 0,
            dps_status TEXT DEFAULT 'clear',
            screened_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shipment_customs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL UNIQUE,
            hs_code TEXT DEFAULT '',
            goods_description TEXT DEFAULT '',
            declared_value REAL DEFAULT 0,
            declared_currency TEXT DEFAULT 'USD',
            origin_country TEXT DEFAULT '',
            destination_country TEXT DEFAULT '',
            incoterm TEXT DEFAULT 'DAP',
            export_license_required INTEGER DEFAULT 0,
            import_license_required INTEGER DEFAULT 0,
            restricted_goods INTEGER DEFAULT 0,
            restriction_notes TEXT DEFAULT '',
            estimated_duty_pct REAL DEFAULT 0,
            estimated_duty_amount REAL DEFAULT 0,
            customs_status TEXT DEFAULT 'Pending',
            entry_number TEXT DEFAULT '',
            broker_name TEXT DEFAULT '',
            broker_contact TEXT DEFAULT '',
            filing_notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS intake_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            source_type TEXT DEFAULT 'upload',
            raw_text TEXT DEFAULT '',
            extracted_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            shipment_ref TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS docks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            dock_type TEXT NOT NULL DEFAULT 'both',
            location TEXT DEFAULT '',
            default_duration_minutes INTEGER NOT NULL DEFAULT 60,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS dock_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL UNIQUE,
            dock_id INTEGER,
            booking_token TEXT UNIQUE NOT NULL,
            appointment_type TEXT NOT NULL DEFAULT 'inbound',
            status TEXT NOT NULL DEFAULT 'Scheduled',
            scheduled_start TIMESTAMP,
            scheduled_end TIMESTAMP,
            duration_minutes INTEGER NOT NULL DEFAULT 60,
            carrier_name TEXT DEFAULT '',
            contact_name TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            booked_by TEXT DEFAULT 'dispatch',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (dock_id) REFERENCES docks(id) ON DELETE SET NULL,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS yard_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_type TEXT NOT NULL DEFAULT 'trailer',
            unit_number TEXT NOT NULL,
            carrier_name TEXT DEFAULT '',
            shipment_ref TEXT DEFAULT '',
            location TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'in_yard',
            driver_name TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            arrived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            departed_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS integration_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER DEFAULT 1,
            integration_key TEXT NOT NULL,
            encrypted_fields TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'connected',
            last_tested TIMESTAMP,
            last_error TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, integration_key)
        );

        CREATE TABLE IF NOT EXISTS network_loads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER DEFAULT 1,
            posted_by TEXT DEFAULT '',
            company_name TEXT DEFAULT '',
            origin_city TEXT DEFAULT '',
            origin_country TEXT DEFAULT '',
            dest_city TEXT DEFAULT '',
            dest_country TEXT DEFAULT '',
            cargo_type TEXT DEFAULT '',
            weight_kg REAL DEFAULT 0,
            volume_cbm REAL DEFAULT 0,
            ready_date TEXT DEFAULT '',
            equipment_type TEXT DEFAULT 'any',
            rate_usd REAL DEFAULT 0,
            rate_type TEXT DEFAULT 'negotiable',
            mode TEXT DEFAULT 'any',
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS network_capacity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER DEFAULT 1,
            posted_by TEXT DEFAULT '',
            company_name TEXT DEFAULT '',
            origin_city TEXT DEFAULT '',
            origin_country TEXT DEFAULT '',
            dest_city TEXT DEFAULT '',
            dest_country TEXT DEFAULT '',
            equipment_type TEXT DEFAULT '',
            available_date TEXT DEFAULT '',
            capacity_kg REAL DEFAULT 0,
            capacity_cbm REAL DEFAULT 0,
            mode TEXT DEFAULT 'road',
            rate_usd REAL DEFAULT 0,
            rate_type TEXT DEFAULT 'negotiable',
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS network_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_tenant_id INTEGER,
            to_tenant_id INTEGER,
            post_type TEXT DEFAULT 'load',
            post_id INTEGER,
            message TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS network_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rater_tenant_id INTEGER,
            rated_tenant_id INTEGER,
            shipment_ref TEXT DEFAULT '',
            rating INTEGER DEFAULT 5,
            comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # legacy guard — executescript above closed the statement, re-open
    conn.executescript("")

    if "dock_name" in _table_columns(conn, "docks"):
        _rebuild_legacy_docks_table(conn)
    if {"appt_date", "appt_time"} & _table_columns(conn, "dock_appointments"):
        _rebuild_legacy_dock_appointments_table(conn)

    _ensure_multi_tenant_schema(conn)

    shipment_columns = _table_columns(conn, "shipments")
    for column, definition in [
        ("customer_name", "TEXT DEFAULT ''"),
        ("lane_code", "TEXT DEFAULT ''"),
        ("mode", "TEXT DEFAULT ''"),
        ("contract_rate_id", "INTEGER"),
        ("driver_id", "INTEGER"),
        ("vehicle_id", "INTEGER"),
        ("co2_kg", "REAL"),
        ("pod_token", "TEXT"),
        ("po_number", "TEXT DEFAULT ''"),
        ("pro_number", "TEXT DEFAULT ''"),
        ("bol_number", "TEXT DEFAULT ''"),
        ("pickup_number", "TEXT DEFAULT ''"),
        ("delivery_number", "TEXT DEFAULT ''"),
        ("seal_number", "TEXT DEFAULT ''"),
        ("trailer_number", "TEXT DEFAULT ''"),
        ("pickup_appt", "TEXT DEFAULT ''"),
        ("delivery_appt", "TEXT DEFAULT ''"),
        ("shipper_contact_name", "TEXT DEFAULT ''"),
        ("shipper_contact_phone", "TEXT DEFAULT ''"),
        ("consignee_contact_name", "TEXT DEFAULT ''"),
        ("consignee_contact_phone", "TEXT DEFAULT ''"),
        ("hazmat", "INTEGER DEFAULT 0"),
        ("temp_required", "INTEGER DEFAULT 0"),
        ("temp_min_f", "REAL"),
        ("temp_max_f", "REAL"),
        ("pieces", "INTEGER DEFAULT 0"),
        ("pallets", "INTEGER DEFAULT 0"),
        ("special_instructions", "TEXT DEFAULT ''"),
        ("payment_terms", "TEXT DEFAULT 'NET30'"),
    ]:
        if column not in shipment_columns:
            c.execute(f"ALTER TABLE shipments ADD COLUMN {column} {definition}")

    carrier_columns = _table_columns(conn, "tms_carriers")
    for column, definition in [
        ("country", "TEXT DEFAULT ''"),
        ("updated_at", "TIMESTAMP"),
        ("dot_number", "TEXT"),
        ("safety_rating", "TEXT DEFAULT ''"),
        ("insurance_status", "TEXT DEFAULT ''"),
        ("auth_status", "TEXT DEFAULT ''"),
        ("insurance_expires_at", "DATE"),
        ("last_checked", "TIMESTAMP"),
        ("fmcsa_source_url", "TEXT DEFAULT ''"),
    ]:
        if column not in carrier_columns:
            c.execute(f"ALTER TABLE tms_carriers ADD COLUMN {column} {definition}")

    loadboard_columns = _table_columns(conn, "loadboard_posts")
    for column, definition in [
        ("posted_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("expires_at", "TIMESTAMP"),
        ("status", "TEXT DEFAULT 'Active'"),
        ("views", "INTEGER DEFAULT 0"),
    ]:
        if column not in loadboard_columns:
            c.execute(f"ALTER TABLE loadboard_posts ADD COLUMN {column} {definition}")

    driver_columns = _table_columns(conn, "drivers")
    for column, definition in [
        ("phone", "TEXT DEFAULT ''"),
        ("country", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'Active'"),
        ("checkin_token", "TEXT"),
        ("last_location", "TEXT DEFAULT ''"),
        ("last_issue", "TEXT DEFAULT ''"),
        ("last_checkin_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in driver_columns:
            c.execute(f"ALTER TABLE drivers ADD COLUMN {column} {definition}")

    vehicle_columns = _table_columns(conn, "vehicles")
    for column, definition in [
        ("vehicle_type", "TEXT DEFAULT ''"),
        ("capacity_weight", "REAL DEFAULT 0"),
        ("capacity_cbm", "REAL DEFAULT 0"),
        ("country", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'Active'"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("vin", "TEXT DEFAULT ''"),
        ("license_plate", "TEXT DEFAULT ''"),
        ("year", "INTEGER"),
        ("make", "TEXT DEFAULT ''"),
        ("model", "TEXT DEFAULT ''"),
        ("registration_expiry", "DATE"),
        ("insurance_expiry", "DATE"),
        ("insurance_carrier", "TEXT DEFAULT ''"),
        ("odometer", "REAL DEFAULT 0"),
        ("last_inspection_date", "DATE"),
        ("next_inspection_due", "DATE"),
    ]:
        if column not in vehicle_columns:
            c.execute(f"ALTER TABLE vehicles ADD COLUMN {column} {definition}")

    driver_columns = _table_columns(conn, "drivers")
    for column, definition in [
        ("phone", "TEXT DEFAULT ''"),
        ("country", "TEXT DEFAULT ''"),
        ("status", "TEXT DEFAULT 'Active'"),
        ("checkin_token", "TEXT"),
        ("last_location", "TEXT DEFAULT ''"),
        ("last_issue", "TEXT DEFAULT ''"),
        ("last_checkin_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("email", "TEXT DEFAULT ''"),
        ("license_state", "TEXT DEFAULT ''"),
        ("cdl_class", "TEXT DEFAULT ''"),
        ("cdl_expiry", "DATE"),
        ("medical_card_expiry", "DATE"),
        ("drug_test_date", "DATE"),
        ("hire_date", "DATE"),
        ("emergency_contact_name", "TEXT DEFAULT ''"),
        ("emergency_contact_phone", "TEXT DEFAULT ''"),
        ("hazmat_endorsement", "INTEGER DEFAULT 0"),
        ("twic_card", "INTEGER DEFAULT 0"),
    ]:
        if column not in driver_columns:
            c.execute(f"ALTER TABLE drivers ADD COLUMN {column} {definition}")

    carrier_columns = _table_columns(conn, "tms_carriers")
    for column, definition in [
        ("country", "TEXT DEFAULT ''"),
        ("updated_at", "TIMESTAMP"),
        ("dot_number", "TEXT"),
        ("safety_rating", "TEXT DEFAULT ''"),
        ("insurance_status", "TEXT DEFAULT ''"),
        ("auth_status", "TEXT DEFAULT ''"),
        ("insurance_expires_at", "DATE"),
        ("last_checked", "TIMESTAMP"),
        ("fmcsa_source_url", "TEXT DEFAULT ''"),
        ("mc_number", "TEXT DEFAULT ''"),
        ("contact_name", "TEXT DEFAULT ''"),
        ("address", "TEXT DEFAULT ''"),
        ("city", "TEXT DEFAULT ''"),
        ("state_province", "TEXT DEFAULT ''"),
        ("postal_code", "TEXT DEFAULT ''"),
        ("equipment_types", "TEXT DEFAULT ''"),
        ("service_areas", "TEXT DEFAULT ''"),
        ("insurance_company", "TEXT DEFAULT ''"),
        ("insurance_policy", "TEXT DEFAULT ''"),
        ("cargo_insurance_amount", "REAL DEFAULT 0"),
        ("liability_amount", "REAL DEFAULT 0"),
        ("payment_terms", "TEXT DEFAULT ''"),
    ]:
        if column not in carrier_columns:
            c.execute(f"ALTER TABLE tms_carriers ADD COLUMN {column} {definition}")

    invoice_columns = _table_columns(conn, "customer_invoices")
    for column, definition in [
        ("freight_charge", "REAL DEFAULT 0"),
        ("fuel_surcharge", "REAL DEFAULT 0"),
        ("accessorial_total", "REAL DEFAULT 0"),
        ("tax_amount", "REAL DEFAULT 0"),
        ("discount", "REAL DEFAULT 0"),
        ("payment_terms", "TEXT DEFAULT ''"),
        ("remit_to", "TEXT DEFAULT ''"),
        ("invoice_date", "DATE"),
        ("po_reference", "TEXT DEFAULT ''"),
    ]:
        if column not in invoice_columns:
            c.execute(f"ALTER TABLE customer_invoices ADD COLUMN {column} {definition}")

    dock_columns = _table_columns(conn, "docks")
    if "dock_name" in dock_columns and "name" not in dock_columns:
        c.execute("ALTER TABLE docks ADD COLUMN name TEXT")
        c.execute(
            """
            UPDATE docks
            SET name = COALESCE(NULLIF(TRIM(name), ''), NULLIF(TRIM(dock_name), ''))
            WHERE COALESCE(TRIM(name), '') = ''
            """
        )
        dock_columns = _table_columns(conn, "docks")

    for column, definition in [
        ("name", "TEXT"),
        ("dock_type", "TEXT NOT NULL DEFAULT 'both'"),
        ("location", "TEXT DEFAULT ''"),
        ("default_duration_minutes", "INTEGER NOT NULL DEFAULT 60"),
        ("active", "INTEGER DEFAULT 1"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in dock_columns:
            c.execute(f"ALTER TABLE docks ADD COLUMN {column} {definition}")

    dock_appointment_columns = _table_columns(conn, "dock_appointments")
    if "appt_type" in dock_appointment_columns and "appointment_type" not in dock_appointment_columns:
        c.execute("ALTER TABLE dock_appointments ADD COLUMN appointment_type TEXT")
        c.execute(
            """
            UPDATE dock_appointments
            SET appointment_type = CASE
                WHEN lower(COALESCE(appt_type, '')) IN ('pickup', 'outbound') THEN 'outbound'
                ELSE 'inbound'
            END
            WHERE COALESCE(TRIM(appointment_type), '') = ''
            """
        )
        dock_appointment_columns = _table_columns(conn, "dock_appointments")

    for column, definition in [
        ("shipment_ref", "TEXT"),
        ("booking_token", "TEXT"),
        ("appointment_type", "TEXT NOT NULL DEFAULT 'inbound'"),
        ("status", "TEXT NOT NULL DEFAULT 'Scheduled'"),
        ("scheduled_start", "TIMESTAMP"),
        ("scheduled_end", "TIMESTAMP"),
        ("duration_minutes", "INTEGER NOT NULL DEFAULT 60"),
        ("carrier_name", "TEXT DEFAULT ''"),
        ("contact_name", "TEXT DEFAULT ''"),
        ("contact_email", "TEXT DEFAULT ''"),
        ("notes", "TEXT DEFAULT ''"),
        ("booked_by", "TEXT DEFAULT 'dispatch'"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in dock_appointment_columns:
            c.execute(f"ALTER TABLE dock_appointments ADD COLUMN {column} {definition}")

    portal_columns = _table_columns(conn, "portal_tokens")
    for column, definition in [
        ("customer_name", "TEXT NOT NULL DEFAULT ''"),
        ("email", "TEXT DEFAULT ''"),
        ("shipment_refs", "TEXT DEFAULT '[]'"),
        ("expires_at", "TIMESTAMP"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in portal_columns:
            c.execute(f"ALTER TABLE portal_tokens ADD COLUMN {column} {definition}")
    c.execute(
        """
        UPDATE portal_tokens
        SET expires_at = datetime(COALESCE(created_at, CURRENT_TIMESTAMP), '+30 days')
        WHERE COALESCE(TRIM(expires_at), '') = ''
        """
    )

    portal_quote_request_columns = _table_columns(conn, "portal_quote_requests")
    for column, definition in [
        ("portal_token", "TEXT NOT NULL DEFAULT ''"),
        ("customer_name", "TEXT NOT NULL DEFAULT ''"),
        ("origin", "TEXT NOT NULL DEFAULT ''"),
        ("destination", "TEXT NOT NULL DEFAULT ''"),
        ("cargo_description", "TEXT NOT NULL DEFAULT ''"),
        ("weight_kg", "REAL"),
        ("volume_cbm", "REAL"),
        ("equipment_type", "TEXT DEFAULT ''"),
        ("pickup_date", "DATE"),
        ("delivery_date", "DATE"),
        ("notes", "TEXT DEFAULT ''"),
        ("status", "TEXT NOT NULL DEFAULT 'pending'"),
        ("quoted_rate", "REAL"),
        ("quoted_by", "TEXT DEFAULT ''"),
        ("quoted_at", "TIMESTAMP"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in portal_quote_request_columns:
            c.execute(f"ALTER TABLE portal_quote_requests ADD COLUMN {column} {definition}")

    api_key_columns = _table_columns(conn, "api_keys")
    for column, definition in [
        ("customer_name", "TEXT NOT NULL DEFAULT ''"),
        ("permissions", "TEXT NOT NULL DEFAULT '[]'"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("last_used", "TIMESTAMP"),
        ("key_hint", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if column not in api_key_columns:
            c.execute(f"ALTER TABLE api_keys ADD COLUMN {column} {definition}")
    api_key_rows = conn.execute("SELECT key, key_hint FROM api_keys").fetchall()
    for row in api_key_rows:
        raw_or_hash = _normalize_text(row["key"])
        if not raw_or_hash:
            continue
        if _looks_like_api_key_hash(raw_or_hash):
            if not _normalize_text(row["key_hint"]):
                c.execute(
                    "UPDATE api_keys SET key_hint = ? WHERE key = ?",
                    (f"{raw_or_hash[:8]}...", raw_or_hash),
                )
            continue
        c.execute(
            """
            UPDATE api_keys
            SET key = ?, key_hint = ?
            WHERE key = ?
            """,
            (_hash_api_key_value(raw_or_hash), _api_key_hint(raw_or_hash), raw_or_hash),
        )

    edi_transaction_columns = _table_columns(conn, "edi_transactions")
    for column, definition in [
        ("format", "TEXT NOT NULL DEFAULT 'X12'"),
        ("partner_id", "INTEGER"),
        ("filename", "TEXT DEFAULT ''"),
        ("source_path", "TEXT DEFAULT ''"),
    ]:
        if column not in edi_transaction_columns:
            c.execute(f"ALTER TABLE edi_transactions ADD COLUMN {column} {definition}")

    edi_partner_columns = _table_columns(conn, "edi_partners")
    for column, definition in [
        ("name", "TEXT NOT NULL DEFAULT ''"),
        ("isa_id", "TEXT NOT NULL DEFAULT ''"),
        ("format", "TEXT NOT NULL DEFAULT 'X12'"),
        ("direction", "TEXT NOT NULL DEFAULT 'inbound'"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in edi_partner_columns:
            c.execute(f"ALTER TABLE edi_partners ADD COLUMN {column} {definition}")

    freight_claim_columns = _table_columns(conn, "freight_claims")
    for column, definition in [
        ("settled_at", "TIMESTAMP"),
        ("carrier_notes", "TEXT DEFAULT ''"),
        ("counter_offer", "REAL"),
        ("response_token", "TEXT"),
        ("responded_at", "TIMESTAMP"),
        ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        if column not in freight_claim_columns:
            c.execute(f"ALTER TABLE freight_claims ADD COLUMN {column} {definition}")

    c.execute(
        """
        UPDATE tms_carriers
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL OR updated_at = ''
        """
    )
    c.execute(
        """
        UPDATE drivers
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL OR updated_at = ''
        """
    )
    c.execute(
        """
        UPDATE vehicles
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL OR updated_at = ''
        """
    )
    if "dock_name" in dock_columns:
        c.execute(
            """
            UPDATE docks
            SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
                name = COALESCE(NULLIF(TRIM(name), ''), NULLIF(TRIM(dock_name), ''), 'Dock')
            """
        )
    else:
        c.execute(
            """
            UPDATE docks
            SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
                name = COALESCE(NULLIF(TRIM(name), ''), 'Dock')
            """
        )
    c.execute(
        """
        UPDATE docks
        SET dock_type = CASE
            WHEN lower(COALESCE(dock_type, '')) IN ('inbound', 'outbound', 'both') THEN lower(dock_type)
            ELSE 'both'
        END,
            default_duration_minutes = CASE
                WHEN COALESCE(default_duration_minutes, 0) > 0 THEN default_duration_minutes
                ELSE 60
            END,
            active = CASE
                WHEN COALESCE(active, 1) = 0 THEN 0
                ELSE 1
            END
        """
    )
    c.execute(
        """
        UPDATE shipments
        SET customer_name = COALESCE(NULLIF(TRIM(customer_name), ''), COALESCE(TRIM(shipper_name), ''))
        WHERE COALESCE(TRIM(customer_name), '') = ''
          AND COALESCE(TRIM(shipper_name), '') != ''
        """
    )
    c.execute(
        """
        UPDATE freight_claims
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
            carrier_notes = COALESCE(carrier_notes, ''),
            evidence_path = COALESCE(evidence_path, '')
        """
    )
    c.execute(
        """
        UPDATE dock_appointments
        SET shipment_ref = COALESCE(NULLIF(TRIM(shipment_ref), ''), ''),
            carrier_name = COALESCE(carrier_name, ''),
            contact_name = COALESCE(contact_name, ''),
            contact_email = COALESCE(contact_email, ''),
            notes = COALESCE(notes, ''),
            booked_by = COALESCE(NULLIF(TRIM(booked_by), ''), 'dispatch'),
            updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        """
    )
    c.execute(
        """
        UPDATE dock_appointments
        SET appointment_type = CASE
            WHEN lower(COALESCE(appointment_type, '')) IN ('inbound', 'delivery') THEN 'inbound'
            WHEN lower(COALESCE(appointment_type, '')) IN ('outbound', 'pickup') THEN 'outbound'
            ELSE 'inbound'
        END,
            status = CASE
                WHEN COALESCE(TRIM(status), '') IN ('Scheduled', 'Checked-In', 'Loading', 'Complete', 'No-Show') THEN status
                WHEN lower(COALESCE(status, '')) = 'checked-in' THEN 'Checked-In'
                WHEN lower(COALESCE(status, '')) = 'loading' THEN 'Loading'
                WHEN lower(COALESCE(status, '')) = 'complete' THEN 'Complete'
                WHEN lower(COALESCE(status, '')) = 'no-show' THEN 'No-Show'
                ELSE 'Scheduled'
            END,
            duration_minutes = CASE
                WHEN COALESCE(duration_minutes, 0) > 0 THEN duration_minutes
                ELSE 60
            END
        """
    )
    c.execute(
        """
        UPDATE dock_appointments
        SET shipment_ref = NULL
        WHERE COALESCE(TRIM(shipment_ref), '') = ''
        """
    )
    if {"appt_date", "appt_time"} <= dock_appointment_columns:
        try:
            c.execute(
                """
                UPDATE dock_appointments
                SET scheduled_start = CASE
                    WHEN COALESCE(TRIM(scheduled_start), '') != '' THEN scheduled_start
                    WHEN COALESCE(TRIM(appt_date), '') != '' AND COALESCE(TRIM(appt_time), '') != ''
                        THEN trim(appt_date) || ' ' || trim(appt_time)
                    ELSE NULL
                END
                WHERE COALESCE(TRIM(scheduled_start), '') = ''
                """
            )
        except sqlite3.OperationalError:
            pass
    c.execute(
        """
        UPDATE dock_appointments
        SET scheduled_end = datetime(
            scheduled_start,
            printf('+%s minutes', COALESCE(NULLIF(duration_minutes, 0), 60))
        )
        WHERE COALESCE(TRIM(scheduled_start), '') != ''
          AND COALESCE(TRIM(scheduled_end), '') = ''
        """
    )

    duplicate_appointment_refs = conn.execute(
        """
        SELECT shipment_ref, COUNT(*) AS row_count
        FROM dock_appointments
        WHERE COALESCE(TRIM(shipment_ref), '') != ''
        GROUP BY shipment_ref
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in duplicate_appointment_refs:
        duplicate_rows = conn.execute(
            """
            SELECT id
            FROM dock_appointments
            WHERE shipment_ref = ?
            ORDER BY
                CASE WHEN COALESCE(TRIM(scheduled_start), '') != '' THEN 0 ELSE 1 END,
                datetime(COALESCE(scheduled_start, created_at)) DESC,
                id DESC
            """,
            (row["shipment_ref"],),
        ).fetchall()
        for duplicate in duplicate_rows[1:]:
            conn.execute("DELETE FROM dock_appointments WHERE id = ?", (duplicate["id"],))

    missing_dock_tokens = conn.execute(
        "SELECT id FROM dock_appointments WHERE COALESCE(TRIM(booking_token), '') = ''"
    ).fetchall()
    for row in missing_dock_tokens:
        conn.execute(
            "UPDATE dock_appointments SET booking_token = ? WHERE id = ?",
            (secrets.token_urlsafe(18), row["id"]),
        )

    missing_driver_tokens = conn.execute(
        "SELECT id FROM drivers WHERE COALESCE(checkin_token, '') = ''"
    ).fetchall()
    for row in missing_driver_tokens:
        conn.execute(
            "UPDATE drivers SET checkin_token = ? WHERE id = ?",
            (_generate_driver_token(conn), row["id"]),
        )

    missing_pod_tokens = conn.execute(
        "SELECT shipment_ref FROM shipments WHERE COALESCE(pod_token, '') = ''"
    ).fetchall()
    for row in missing_pod_tokens:
        conn.execute(
            "UPDATE shipments SET pod_token = ? WHERE shipment_ref = ?",
            (_generate_pod_token(conn), row["shipment_ref"]),
        )

    secure_setting_rows = conn.execute(
        "SELECT key, value FROM tms_settings WHERE key IN (?, ?, ?)",
        tuple(_ENCRYPTED_SETTING_KEYS),
    ).fetchall()
    for row in secure_setting_rows:
        raw_value = str(row["value"] or "")
        if raw_value and not raw_value.startswith(_ENCRYPTED_SETTING_PREFIX):
            conn.execute(
                "UPDATE tms_settings SET value = ? WHERE key = ?",
                (_encode_secure_setting(row["key"], raw_value), row["key"]),
            )

    c.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_customer_name ON api_keys(customer_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tms_carriers_name ON tms_carriers(name)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tms_carriers_dot_number ON tms_carriers(dot_number)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_carrier_id ON shipments(carrier_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_carrier_name ON shipments(carrier_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_customer_name ON shipments(customer_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_pod_token ON shipments(pod_token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_driver_id ON shipments(driver_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_vehicle_id ON shipments(vehicle_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_drivers_status ON drivers(status)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_drivers_license_number ON drivers(license_number)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_drivers_checkin_token ON drivers(checkin_token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicles_truck_number ON vehicles(truck_number)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_duty_logs_driver_id ON duty_logs(driver_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_duty_logs_shipment_id ON duty_logs(shipment_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_carrier_invoices_shipment_ref ON carrier_invoices(shipment_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_carrier_invoices_status ON carrier_invoices(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_carrier_invoices_invoice_no ON carrier_invoices(invoice_no)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_freight_claims_shipment_ref ON freight_claims(shipment_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_freight_claims_status ON freight_claims(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_freight_claims_carrier_id ON freight_claims(carrier_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_freight_claims_claim_type ON freight_claims(claim_type)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_freight_claims_response_token ON freight_claims(response_token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tms_documents_shipment_ref ON tms_documents(shipment_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tms_documents_uploaded_at ON tms_documents(uploaded_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pod_records_shipment_ref ON pod_records(shipment_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_customer_invoices_shipment_ref ON customer_invoices(shipment_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_customer_invoices_status ON customer_invoices(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_portal_tokens_email ON portal_tokens(email)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_portal_quote_requests_token_created ON portal_quote_requests(portal_token, created_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_portal_quote_requests_status_created ON portal_quote_requests(status, created_at DESC, id DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_mode ON shipments(mode)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_shipments_contract_rate_id ON shipments(contract_rate_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contract_rates_lookup ON contract_rates(origin, destination, mode, valid_from, valid_to)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_loads_status ON loads(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_load_shipments_load_id ON load_shipments(load_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_loadboard_posts_status ON loadboard_posts(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_loadboard_posts_expires_at ON loadboard_posts(expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_docks_name ON docks(name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_docks_active ON docks(active)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dock_appointments_shipment_ref ON dock_appointments(shipment_ref)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_dock_appointments_booking_token ON dock_appointments(booking_token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_dock_appointments_dock_schedule ON dock_appointments(dock_id, scheduled_start, scheduled_end)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_dock_appointments_status ON dock_appointments(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tenders_shipment_id ON tenders(shipment_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tenders_status_deadline ON tenders(status, deadline_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tender_responses_tender_id ON tender_responses(tender_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tender_responses_token ON tender_responses(token)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tracking_pings_ref_timestamp ON tracking_pings(shipment_ref, timestamp, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tracking_driver_tokens_shipment_ref ON tracking_driver_tokens(shipment_ref)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edi_partners_lookup ON edi_partners(isa_id, format, direction)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edi_transactions_created_at ON edi_transactions(created_at, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edi_transactions_direction_type ON edi_transactions(direction, type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edi_transactions_format ON edi_transactions(format)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edi_transactions_partner_id ON edi_transactions(partner_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_edi_transactions_shipment_ref ON edi_transactions(shipment_ref)")

    # --- LTL/FTL Load Builder tables ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS load_stops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            load_id INTEGER NOT NULL,
            stop_number INTEGER NOT NULL,
            stop_type TEXT NOT NULL DEFAULT 'pickup',
            company_name TEXT DEFAULT '',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip TEXT DEFAULT '',
            shipment_ref TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            scheduled_time TEXT DEFAULT '',
            actual_time TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            deviation_reason TEXT DEFAULT '',
            deviation_approved INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (load_id) REFERENCES loads(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS load_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            load_id INTEGER NOT NULL,
            sender TEXT NOT NULL,
            message TEXT NOT NULL,
            read_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (load_id) REFERENCES loads(id) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS shipment_legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            leg_number INTEGER NOT NULL,
            mode TEXT NOT NULL,
            carrier_name TEXT DEFAULT '',
            origin TEXT NOT NULL,
            destination TEXT NOT NULL,
            etd TEXT DEFAULT '',
            eta TEXT DEFAULT '',
            status TEXT DEFAULT 'Planned',
            container_ref TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (shipment_ref) REFERENCES shipments(shipment_ref) ON DELETE CASCADE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS route_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_ref TEXT NOT NULL UNIQUE,
            shipment_ref TEXT DEFAULT '',
            load_number TEXT DEFAULT '',
            driver_id INTEGER DEFAULT NULL,
            status TEXT DEFAULT 'Draft',
            total_stops INTEGER DEFAULT 0,
            estimated_miles REAL DEFAULT 0,
            estimated_hours REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS route_stops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_ref TEXT NOT NULL,
            stop_number INTEGER NOT NULL,
            stop_type TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip TEXT DEFAULT '',
            contact_name TEXT DEFAULT '',
            contact_phone TEXT DEFAULT '',
            appointment_time TEXT DEFAULT '',
            reference_number TEXT DEFAULT '',
            shipment_ref TEXT DEFAULT '',
            weight_lbs REAL DEFAULT 0,
            pallets INTEGER DEFAULT 0,
            special_instructions TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            completed_at TIMESTAMP DEFAULT NULL,
            UNIQUE(route_ref, stop_number)
        )
    """)
    # ALTER TABLE migrations for loads (wrap in try/except — columns may already exist)
    for _alter in [
        "ALTER TABLE loads ADD COLUMN equipment_type TEXT DEFAULT 'dry_van'",
        "ALTER TABLE loads ADD COLUMN trailer_number TEXT DEFAULT ''",
        "ALTER TABLE loads ADD COLUMN load_type TEXT DEFAULT 'LTL'",
        "ALTER TABLE loads ADD COLUMN max_weight_lbs REAL DEFAULT 44000",
        "ALTER TABLE loads ADD COLUMN driver_id INTEGER",
        "ALTER TABLE loads ADD COLUMN dispatcher_notes TEXT DEFAULT ''",
        "ALTER TABLE loads ADD COLUMN billing_released INTEGER DEFAULT 0",
        "ALTER TABLE loads ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]:
        try:
            c.execute(_alter)
        except Exception:
            pass
    # ALTER TABLE for pod_records billing_status
    try:
        c.execute("ALTER TABLE pod_records ADD COLUMN billing_status TEXT DEFAULT 'pending'")
    except Exception:
        pass

    for key, value in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO tms_settings (key, value) VALUES (?, ?)", (key, value))

    # --- LTL Load Builder (dedicated tables, separate from loads/load_shipments) ---
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ltl_loads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            load_number TEXT NOT NULL UNIQUE,
            trailer_number TEXT DEFAULT '',
            equipment_type TEXT DEFAULT 'Dry Van',
            max_weight_lbs REAL DEFAULT 44000,
            current_weight_lbs REAL DEFAULT 0,
            max_pallets INTEGER DEFAULT 26,
            current_pallets INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Building',
            origin_city TEXT DEFAULT '',
            destination_city TEXT DEFAULT '',
            pickup_date TEXT DEFAULT '',
            driver_id INTEGER DEFAULT NULL,
            carrier TEXT DEFAULT '',
            ftl_shipment_ref TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS ltl_load_shipments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            load_number TEXT NOT NULL,
            shipment_ref TEXT NOT NULL,
            weight_lbs REAL DEFAULT 0,
            pallets INTEGER DEFAULT 0,
            sequence INTEGER DEFAULT 0,
            pickup_address TEXT DEFAULT '',
            delivery_address TEXT DEFAULT '',
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(load_number, shipment_ref)
        );
        CREATE INDEX IF NOT EXISTS idx_ltl_loads_status ON ltl_loads(status);
        CREATE INDEX IF NOT EXISTS idx_ltl_load_shipments_load_number ON ltl_load_shipments(load_number);
    """)

    # ── Driver Direct Messaging ───────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS driver_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            driver_id INTEGER NOT NULL,
            shipment_ref TEXT DEFAULT '',
            direction TEXT NOT NULL,
            message TEXT NOT NULL,
            sent_by TEXT DEFAULT 'Dispatcher',
            read_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (driver_id) REFERENCES drivers(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_driver_messages_driver_id ON driver_messages(driver_id)")

    # ── POD Submissions ───────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS pod_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_ref TEXT NOT NULL,
            driver_id INTEGER DEFAULT NULL,
            bol_numbers TEXT DEFAULT '',
            pod_image_path TEXT DEFAULT '',
            pod_pdf_path TEXT DEFAULT '',
            signature_data TEXT DEFAULT '',
            delivery_notes TEXT DEFAULT '',
            recipient_name TEXT DEFAULT '',
            delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Submitted',
            reviewed_by TEXT DEFAULT '',
            reviewed_at TIMESTAMP DEFAULT NULL,
            billing_notified INTEGER DEFAULT 0,
            billing_notified_at TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_pod_submissions_shipment_ref ON pod_submissions(shipment_ref)")

    # ── Billing Queue ─────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS billing_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
            shipment_ref TEXT NOT NULL UNIQUE,
            pod_submission_id INTEGER DEFAULT NULL,
            customer_name TEXT DEFAULT '',
            invoice_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'Ready to Bill',
            pod_count INTEGER DEFAULT 1,
            notes TEXT DEFAULT '',
            notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            invoiced_at TIMESTAMP DEFAULT NULL,
            FOREIGN KEY (pod_submission_id) REFERENCES pod_submissions(id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_billing_queue_status ON billing_queue(status)")

    # ── Customer Order Intake ──────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS customer_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ref TEXT NOT NULL UNIQUE,
            shipment_ref TEXT DEFAULT '',
            customer_name TEXT NOT NULL,
            customer_email TEXT DEFAULT '',
            customer_phone TEXT DEFAULT '',
            customer_company TEXT DEFAULT '',
            origin_address TEXT DEFAULT '',
            origin_city TEXT DEFAULT '',
            origin_state TEXT DEFAULT '',
            origin_zip TEXT DEFAULT '',
            destination_address TEXT DEFAULT '',
            destination_city TEXT DEFAULT '',
            destination_state TEXT DEFAULT '',
            destination_zip TEXT DEFAULT '',
            pickup_date TEXT DEFAULT '',
            delivery_date TEXT DEFAULT '',
            cargo_description TEXT DEFAULT '',
            weight_lbs REAL DEFAULT 0,
            pallets INTEGER DEFAULT 0,
            pieces INTEGER DEFAULT 0,
            equipment_type TEXT DEFAULT 'Dry Van',
            service_type TEXT DEFAULT 'LTL',
            special_instructions TEXT DEFAULT '',
            hazmat INTEGER DEFAULT 0,
            temperature_controlled INTEGER DEFAULT 0,
            temp_min REAL DEFAULT NULL,
            temp_max REAL DEFAULT NULL,
            declared_value REAL DEFAULT 0,
            pipeline_stage TEXT DEFAULT 'Received',
            quoted_rate REAL DEFAULT 0,
            accepted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_customer_orders_pipeline_stage ON customer_orders(pipeline_stage)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_customer_orders_created_at ON customer_orders(created_at)")

    _ensure_multi_tenant_schema(conn)

    conn.commit()
    conn.close()


# ── Driver Messaging ──────────────────────────────────────────────────────────

def send_message_to_driver(driver_id, message, shipment_ref="", sent_by="Dispatcher"):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO driver_messages (driver_id, shipment_ref, direction, message, sent_by) VALUES (?,?,?,?,?)",
            (driver_id, shipment_ref, "to_driver", message, sent_by)
        )
        conn.commit()
    finally:
        conn.close()


def get_driver_messages(driver_id, shipment_ref=None):
    conn = get_db()
    try:
        if shipment_ref:
            rows = conn.execute(
                "SELECT * FROM driver_messages WHERE driver_id=? AND shipment_ref=? ORDER BY created_at",
                (driver_id, shipment_ref)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM driver_messages WHERE driver_id=? ORDER BY created_at DESC LIMIT 50",
                (driver_id,)
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def driver_reply(driver_id, message, shipment_ref=""):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO driver_messages (driver_id, shipment_ref, direction, message, sent_by) VALUES (?,?,?,?,?)",
            (driver_id, shipment_ref, "from_driver", message, "Driver")
        )
        conn.commit()
    finally:
        conn.close()


def get_unread_message_count(driver_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM driver_messages WHERE driver_id=? AND direction='from_driver' AND read_at IS NULL",
            (driver_id,)
        ).fetchone()[0]
    finally:
        conn.close()


# ── POD Submissions ────────────────────────────────────────────────────────────

def save_pod_submission(shipment_ref, driver_id, bol_numbers, image_path, pdf_path,
                         signature_data="", delivery_notes="", recipient_name=""):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO pod_submissions
               (shipment_ref, driver_id, bol_numbers, pod_image_path, pod_pdf_path,
                signature_data, delivery_notes, recipient_name)
               VALUES (?,?,?,?,?,?,?,?)""",
            (shipment_ref, driver_id, bol_numbers, image_path, pdf_path,
             signature_data, delivery_notes, recipient_name)
        )
        conn.execute(
            "UPDATE shipments SET status='Delivered', updated_at=CURRENT_TIMESTAMP WHERE shipment_ref=?",
            (shipment_ref,)
        )
        conn.commit()
        bol_count = len([b for b in bol_numbers.split(",") if b.strip()])
        return bol_count
    finally:
        conn.close()


def get_pod_submissions(shipment_ref=None):
    conn = get_db()
    try:
        if shipment_ref:
            rows = conn.execute(
                "SELECT * FROM pod_submissions WHERE shipment_ref=? ORDER BY created_at DESC",
                (shipment_ref,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT ps.*, s.cargo_description
                   FROM pod_submissions ps
                   LEFT JOIN shipments s ON s.shipment_ref = ps.shipment_ref
                   ORDER BY ps.created_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def route_pod_to_billing(pod_submission_id, shipment_ref, customer_name="", invoice_amount=0, notes=""):
    """Add shipment to billing queue and mark POD as sent to accounting."""
    conn = get_db()
    try:
        pod = conn.execute("SELECT * FROM pod_submissions WHERE id=?", (pod_submission_id,)).fetchone()
        bol_count = len([b for b in (pod["bol_numbers"] or "").split(",") if b.strip()]) if pod else 1
        conn.execute(
            """INSERT OR REPLACE INTO billing_queue
               (shipment_ref, pod_submission_id, customer_name, invoice_amount, pod_count, notes, notified_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (shipment_ref, pod_submission_id, customer_name, invoice_amount, bol_count, notes)
        )
        conn.execute(
            "UPDATE pod_submissions SET status='Sent to Accounting', billing_notified=1, billing_notified_at=CURRENT_TIMESTAMP WHERE id=?",
            (pod_submission_id,)
        )
        conn.commit()
    finally:
        conn.close()


def get_billing_queue():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT bq.*, ps.pod_image_path, ps.pod_pdf_path, ps.delivered_at
               FROM billing_queue bq
               LEFT JOIN pod_submissions ps ON ps.id = bq.pod_submission_id
               ORDER BY bq.notified_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_billed(shipment_ref):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE billing_queue SET status='Invoiced', invoiced_at=CURRENT_TIMESTAMP WHERE shipment_ref=?",
            (shipment_ref,)
        )
        conn.commit()
    finally:
        conn.close()


def pod_image_to_pdf(image_path: str) -> str:
    """Convert a POD image to PDF. Returns PDF path."""
    try:
        from PIL import Image
        pdf_path = image_path.rsplit(".", 1)[0] + ".pdf"
        img = Image.open(image_path)
        img = img.convert("RGB")
        img.save(pdf_path, "PDF", resolution=150)
        return pdf_path
    except Exception:
        return image_path


# ── Tenant payload ─────────────────────────────────────────────────────────────

def _tenant_payload(row):
    tenant = dict(row)
    try:
        tenant["allowed_ip_cidrs"] = json.loads(tenant.get("allowed_ip_cidrs") or "[]")
    except (TypeError, ValueError):
        tenant["allowed_ip_cidrs"] = []
    return tenant


def _normalize_list_input(value):
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = re.split(r"[\r\n,]+", _normalize_text(value))
    clean_items = []
    seen = set()
    for item in raw_items:
        clean_item = _normalize_text(item)
        if not clean_item or clean_item in seen:
            continue
        clean_items.append(clean_item)
        seen.add(clean_item)
    return clean_items


def _generate_tenant_id(conn, company_name):
    base_value = normalize_tenant_id(company_name)
    candidate = base_value
    suffix = 2
    while conn.execute(
        "SELECT 1 FROM tenants WHERE tenant_id = ? LIMIT 1",
        (candidate,),
    ).fetchone():
        candidate = f"{base_value}-{suffix}"
        suffix += 1
    return candidate


def list_tenants(include_deleted=False):
    init_tms_db()
    with disabled_tenant_scope():
        conn = get_db()
        try:
            params = []
            query = "SELECT * FROM tenants"
            if not include_deleted:
                query += " WHERE status != ?"
                params.append("deleted")
            query += " ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'suspended' THEN 1 ELSE 2 END, company_name COLLATE NOCASE ASC"
            rows = conn.execute(query, params).fetchall()
            return [_tenant_payload(row) for row in rows]
        finally:
            conn.close()


def get_tenant(tenant_id):
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    init_tms_db()
    with disabled_tenant_scope():
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM tenants WHERE tenant_id = ?",
                (normalized_tenant_id,),
            ).fetchone()
            return _tenant_payload(row) if row else None
        finally:
            conn.close()


def create_tenant(*, company_name, plan="starter", max_users=5, data_region=DEFAULT_TENANT_REGION, session_timeout_minutes=DEFAULT_TENANT_SESSION_TIMEOUT_MINUTES, allowed_ip_cidrs=None, saml_entity_id="", saml_sso_url="", saml_x509_cert="", saml_metadata_url=""):
    init_tms_db()
    clean_company_name = _normalize_text(company_name)
    clean_plan = _normalize_text(plan).lower() or "starter"
    clean_region = _normalize_text(data_region) or DEFAULT_TENANT_REGION
    clean_allowed_ips = json.dumps(_normalize_list_input(allowed_ip_cidrs))
    clean_saml_entity_id = _normalize_text(saml_entity_id)
    clean_saml_sso_url = _normalize_text(saml_sso_url)
    clean_saml_x509_cert = _normalize_text(saml_x509_cert)
    clean_saml_metadata_url = _normalize_text(saml_metadata_url)

    if not clean_company_name:
        raise ValueError("Company name is required.")
    if clean_plan not in PLAN_OPTIONS:
        raise ValueError("Plan must be starter, pro, or enterprise.")
    try:
        clean_max_users = max(int(max_users or 0), 1)
    except ValueError as exc:
        raise ValueError("Max users must be a whole number.") from exc
    try:
        clean_timeout = max(int(session_timeout_minutes or 0), 5)
    except ValueError as exc:
        raise ValueError("Session timeout must be a whole number of minutes.") from exc

    conn = get_db()
    try:
        with disabled_tenant_scope():
            tenant_id = _generate_tenant_id(conn, clean_company_name)
        with tenant_context(tenant_id=tenant_id):
            conn.execute(
                """
                INSERT INTO tenants
                    (tenant_id, company_name, plan, max_users, data_region, session_timeout_minutes,
                     allowed_ip_cidrs, saml_entity_id, saml_sso_url, saml_x509_cert, saml_metadata_url, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """,
                (
                    tenant_id,
                    clean_company_name,
                    clean_plan,
                    clean_max_users,
                    clean_region,
                    clean_timeout,
                    clean_allowed_ips,
                    clean_saml_entity_id,
                    clean_saml_sso_url,
                    clean_saml_x509_cert,
                    clean_saml_metadata_url,
                ),
            )
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute("INSERT OR IGNORE INTO tms_settings (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
        return get_tenant(tenant_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_tenant_status(tenant_id, status):
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    clean_status = _normalize_text(status).lower()
    if clean_status not in TENANT_STATUS_OPTIONS:
        raise ValueError("Tenant status is invalid.")
    if normalized_tenant_id == DEFAULT_TENANT_ID and clean_status != "active":
        raise ValueError("The default tenant cannot be suspended or deleted.")

    init_tms_db()
    conn = get_db()
    try:
        with tenant_context(tenant_id=normalized_tenant_id):
            result = conn.execute(
                """
                UPDATE tenants
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = ?
                """,
                (clean_status, normalized_tenant_id),
            )
            if result.rowcount == 0:
                raise ValueError("Tenant not found.")
            conn.commit()
        return get_tenant(normalized_tenant_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_audit_log(*, tenant_id=None, user_id="", action="", start_date="", end_date="", include_all=False, limit=500):
    init_tms_db()
    clean_tenant_id = normalize_tenant_id(tenant_id) if tenant_id else None
    clean_user_id = _normalize_text(user_id)
    clean_action = _normalize_text(action).upper()
    clean_start_date = _normalize_text(start_date)
    clean_end_date = _normalize_text(end_date)
    safe_limit = max(int(limit or 500), 1)

    query = """
        SELECT *
        FROM audit_log
        WHERE 1=1
    """
    params = []
    if clean_tenant_id:
        query += " AND tenant_id = ?"
        params.append(clean_tenant_id)
    if clean_user_id:
        query += " AND lower(user_id) = lower(?)"
        params.append(clean_user_id)
    if clean_action:
        query += " AND action = ?"
        params.append(clean_action)
    if clean_start_date:
        query += " AND date(created_at) >= date(?)"
        params.append(clean_start_date)
    if clean_end_date:
        query += " AND date(created_at) <= date(?)"
        params.append(clean_end_date)
    query += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
    params.append(safe_limit)

    context_manager = disabled_tenant_scope() if include_all else tenant_context(tenant_id=clean_tenant_id or get_current_tenant())
    with context_manager:
        conn = get_db()
        try:
            rows = conn.execute(query, params).fetchall()
            payload = []
            for row in rows:
                event = dict(row)
                try:
                    event["changes"] = json.loads(event.get("changes_json") or "{}")
                except (TypeError, ValueError):
                    event["changes"] = {}
                payload.append(event)
            return payload
        finally:
            conn.close()


def _parse_amount_value(raw_value):
    value = _normalize_text(str(raw_value or ""))
    if not value:
        return None

    matches = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", value)
    if not matches:
        return None

    candidate = max(matches, key=len).replace(",", "")
    try:
        return float(candidate)
    except ValueError:
        return None


def _append_shipment_note(existing_notes, new_note):
    clean_note = _normalize_text(new_note)
    if not clean_note:
        return _normalize_text(existing_notes)

    existing = [part.strip() for part in _normalize_text(existing_notes).split(" | ") if part.strip()]
    if clean_note in existing:
        return " | ".join(existing)
    existing.append(clean_note)
    return " | ".join(existing)


def _build_edi_location_label(source):
    city = _normalize_text((source or {}).get("city"))
    state = _normalize_text((source or {}).get("state"))
    if city and state:
        return f"{city}, {state}"
    return city or _normalize_text((source or {}).get("name"))


def _build_edi_address_label(source):
    source = source or {}
    pieces = [
        _normalize_text(source.get("address_line_1")),
        _normalize_text(source.get("address_line_2")),
        _build_edi_location_label(source),
        _normalize_text(source.get("postal_code")),
        _normalize_text(source.get("country")),
    ]
    return ", ".join(piece for piece in pieces if piece)


def _coalesce_text(*values):
    for value in values:
        clean_value = _normalize_text(value)
        if clean_value:
            return clean_value
    return ""


def _coalesce_number(*values):
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _ensure_edi_carrier(conn, scac="", name=""):
    clean_scac = _normalize_scac(scac)
    clean_name = _normalize_text(name)

    if clean_scac:
        row = conn.execute(
            "SELECT * FROM tms_carriers WHERE scac = ?",
            (clean_scac,),
        ).fetchone()
        if row:
            if clean_name and clean_name != _normalize_text(row["name"]):
                conn.execute(
                    """
                    UPDATE tms_carriers
                    SET name = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (clean_name, row["id"]),
                )
                row = conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (row["id"],)).fetchone()
            return dict(row)

    if clean_name:
        row = conn.execute(
            "SELECT * FROM tms_carriers WHERE lower(name) = lower(?)",
            (clean_name,),
        ).fetchone()
        if row:
            if clean_scac and not _normalize_scac(row["scac"]):
                conn.execute(
                    """
                    UPDATE tms_carriers
                    SET scac = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (clean_scac, row["id"]),
                )
                row = conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (row["id"],)).fetchone()
            return dict(row)

    if not clean_scac and not clean_name:
        return None

    cursor = conn.execute(
        """
        INSERT INTO tms_carriers (name, scac, active, updated_at)
        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        """,
        (_coalesce_text(clean_name, clean_scac), clean_scac),
    )
    row = conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def _insert_edi_shipment_event(conn, shipment_id, event_type, description, *, location="", event_date=""):
    event_timestamp = _normalize_text(event_date) or datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO shipment_events (shipment_id, event_type, description, location, event_date, created_by)
        VALUES (?, ?, ?, ?, ?, 'edi')
        """,
        (
            shipment_id,
            _coalesce_text(event_type, "EDI Update"),
            _normalize_text(description),
            _normalize_text(location),
            event_timestamp,
        ),
    )


def _find_shipment_row(conn, shipment_ref):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        return None
    return conn.execute(
        "SELECT * FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
        (clean_ref,),
    ).fetchone()


def _ensure_edi_shipment(conn, shipment_ref, *, status="Draft", carrier=None):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        raise ValueError("Shipment reference is required.")

    row = _find_shipment_row(conn, clean_ref)
    if row:
        return dict(row), False

    carrier = carrier or {}
    cursor = conn.execute(
        """
        INSERT INTO shipments (shipment_ref, status, carrier_id, carrier_name, customer_name)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            clean_ref,
            _coalesce_text(status, "Draft"),
            carrier.get("id"),
            _normalize_text(carrier.get("name")),
            "",
        ),
    )
    row = conn.execute("SELECT * FROM shipments WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row), True


def _decode_edi_transaction_row(row):
    if not row:
        return None
    record = dict(row)
    try:
        record["parsed_data"] = json.loads(record.get("parsed_json") or "{}")
    except json.JSONDecodeError:
        record["parsed_data"] = {"raw_json": record.get("parsed_json", "")}
    return record


def list_edi_partners():
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM edi_partners
            ORDER BY upper(name) ASC, id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_edi_partner(partner_id):
    init_tms_db()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM edi_partners WHERE id = ?",
            (int(partner_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_edi_partner(name, isa_id, edi_format="X12", direction="inbound", partner_id=None):
    clean_name = _normalize_text(name)
    clean_isa_id = _normalize_text(isa_id).upper()
    clean_format = _normalize_edi_format(edi_format)
    clean_direction = _normalize_edi_direction(direction)
    if not clean_name:
        raise ValueError("Partner name is required.")
    if not clean_isa_id:
        raise ValueError("Partner ISA ID is required.")

    init_tms_db()
    conn = get_db()
    try:
        duplicate = conn.execute(
            """
            SELECT id
            FROM edi_partners
            WHERE upper(isa_id) = upper(?)
              AND format = ?
              AND direction = ?
              AND (? IS NULL OR id != ?)
            LIMIT 1
            """,
            (clean_isa_id, clean_format, clean_direction, partner_id, partner_id),
        ).fetchone()
        if duplicate:
            raise ValueError("An EDI partner with that ISA ID, format, and direction already exists.")

        if partner_id:
            conn.execute(
                """
                UPDATE edi_partners
                SET name = ?, isa_id = ?, format = ?, direction = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (clean_name, clean_isa_id, clean_format, clean_direction, int(partner_id)),
            )
            saved_id = int(partner_id)
        else:
            cursor = conn.execute(
                """
                INSERT INTO edi_partners (name, isa_id, format, direction, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (clean_name, clean_isa_id, clean_format, clean_direction),
            )
            saved_id = cursor.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM edi_partners WHERE id = ?", (saved_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_edi_partner(partner_id):
    init_tms_db()
    conn = get_db()
    try:
        conn.execute("DELETE FROM edi_partners WHERE id = ?", (int(partner_id),))
        conn.commit()
    finally:
        conn.close()


def find_edi_partner(conn, isa_id, edi_format="X12", direction="inbound"):
    clean_isa_id = _normalize_text(isa_id).upper()
    if not clean_isa_id:
        return None
    clean_format = _normalize_edi_format(edi_format)
    clean_direction = _normalize_edi_direction(direction)
    allowed_directions = ("both", clean_direction)
    row = conn.execute(
        """
        SELECT *
        FROM edi_partners
        WHERE upper(isa_id) = upper(?)
          AND format = ?
          AND direction IN (?, ?)
        ORDER BY CASE direction WHEN 'both' THEN 0 ELSE 1 END, id ASC
        LIMIT 1
        """,
        (clean_isa_id, clean_format, allowed_directions[0], allowed_directions[1]),
    ).fetchone()
    return dict(row) if row else None


def find_recent_edi_partner_for_shipment(conn, shipment_ref, edi_format="X12"):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        return None
    clean_format = _normalize_edi_format(edi_format)
    row = conn.execute(
        """
        SELECT ep.*
        FROM edi_transactions et
        JOIN edi_partners ep ON ep.id = et.partner_id
        WHERE upper(et.shipment_ref) = upper(?)
          AND et.direction = 'inbound'
          AND ep.format = ?
        ORDER BY et.id DESC
        LIMIT 1
        """,
        (clean_ref, clean_format),
    ).fetchone()
    return dict(row) if row else None


def create_edi_transaction(
    conn,
    direction,
    transaction_type,
    raw,
    parsed_json,
    shipment_ref="",
    status="received",
    *,
    edi_format="X12",
    partner_id=None,
    filename="",
    source_path="",
):
    if not isinstance(parsed_json, str):
        parsed_json = json.dumps(parsed_json or {}, sort_keys=True)

    cursor = conn.execute(
        """
        INSERT INTO edi_transactions (direction, type, format, raw, parsed_json, shipment_ref, partner_id, filename, source_path, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _normalize_text(direction),
            _normalize_text(transaction_type) or "UNKNOWN",
            _normalize_text(edi_format).upper() or "X12",
            raw or "",
            parsed_json,
            _normalize_text(shipment_ref),
            partner_id,
            _normalize_text(filename),
            _normalize_text(source_path),
            _normalize_text(status) or "received",
        ),
    )
    return cursor.lastrowid


def get_edi_transaction(transaction_id):
    init_tms_db()
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT et.*, ep.name AS partner_name, ep.isa_id AS partner_isa_id
            FROM edi_transactions et
            LEFT JOIN edi_partners ep ON ep.id = et.partner_id
            WHERE et.id = ?
            """,
            (int(transaction_id),),
        ).fetchone()
        return _decode_edi_transaction_row(row)
    finally:
        conn.close()


def list_edi_transactions(limit=100):
    init_tms_db()
    safe_limit = max(int(limit or 100), 1)
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT et.*, ep.name AS partner_name, ep.isa_id AS partner_isa_id
            FROM edi_transactions et
            LEFT JOIN edi_partners ep ON ep.id = et.partner_id
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [_decode_edi_transaction_row(row) for row in rows]
    finally:
        conn.close()


def apply_edi_transaction(conn, parsed_transaction):
    transaction_type = _normalize_text((parsed_transaction or {}).get("type"))
    if transaction_type == "204":
        return _apply_edi_204(conn, parsed_transaction)
    if transaction_type == "210":
        return _apply_edi_210(conn, parsed_transaction)
    if transaction_type == "211":
        return _apply_edi_211(conn, parsed_transaction)
    if transaction_type == "214":
        return _apply_edi_214(conn, parsed_transaction)
    if transaction_type == "215":
        return _apply_edi_215(conn, parsed_transaction)
    if transaction_type == "850":
        return _apply_edi_850(conn, parsed_transaction)
    if transaction_type == "856":
        return _apply_edi_856(conn, parsed_transaction)
    if transaction_type == "990":
        return _apply_edi_990(conn, parsed_transaction)
    if transaction_type == "997":
        return {"shipment_id": None, "shipment_ref": "", "status": "received", "status_changed": False}
    if transaction_type == "IFTMIN":
        return _apply_edi_iftmin(conn, parsed_transaction)
    if transaction_type == "IFTSTA":
        return _apply_edi_iftsta(conn, parsed_transaction)
    if transaction_type == "INVOIC":
        return _apply_edi_invoic(conn, parsed_transaction)
    raise ValueError(f"Unsupported EDI transaction type: {transaction_type or 'UNKNOWN'}")


def _build_apply_result(shipment_id, shipment_ref, action, previous_status, new_status):
    return {
        "shipment_id": shipment_id,
        "shipment_ref": shipment_ref,
        "status": action,
        "previous_status": _normalize_text(previous_status),
        "shipment_status": _normalize_text(new_status),
        "status_changed": _normalize_text(previous_status) != _normalize_text(new_status),
    }


def _invoice_like_description(parsed_transaction):
    invoice = (parsed_transaction or {}).get("invoice") or {}
    parts = []
    if _normalize_text(invoice.get("invoice_number")):
        parts.append(f"invoice {invoice['invoice_number']}")
    if invoice.get("amount") not in (None, ""):
        currency = _normalize_text(invoice.get("currency")) or "USD"
        parts.append(f"{float(invoice['amount']):,.2f} {currency}")
    return " ".join(parts).strip()


def _apply_invoice_payload(conn, parsed_transaction, *, event_type, event_prefix):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    parties = (parsed_transaction or {}).get("parties") or {}
    invoice = (parsed_transaction or {}).get("invoice") or {}
    shipment_ref = _coalesce_text(shipment_data.get("shipment_ref"), references.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError(f"{event_type} is missing a shipment reference.")

    shipment_row, created = _ensure_edi_shipment(conn, shipment_ref, status=_coalesce_text(shipment_data.get("status"), "Active"))
    shipper = parties.get("shipper") or {}
    consignee = parties.get("consignee") or {}
    previous_status = shipment_row.get("status")
    new_status = _coalesce_text(shipment_data.get("status"), shipment_row.get("status"), "Active")

    conn.execute(
        """
        UPDATE shipments
        SET status = ?, shipper_name = COALESCE(NULLIF(?, ''), shipper_name),
            shipper_address = COALESCE(NULLIF(?, ''), shipper_address),
            consignee_name = COALESCE(NULLIF(?, ''), consignee_name),
            consignee_address = COALESCE(NULLIF(?, ''), consignee_address),
            origin_port = COALESCE(NULLIF(?, ''), origin_port),
            destination_port = COALESCE(NULLIF(?, ''), destination_port),
            cargo_description = COALESCE(NULLIF(?, ''), cargo_description),
            freight_rate = COALESCE(?, freight_rate),
            currency = COALESCE(NULLIF(?, ''), currency),
            notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            new_status,
            _coalesce_text(shipment_data.get("shipper_name"), shipper.get("name")),
            _coalesce_text(shipment_data.get("shipper_address"), _build_edi_address_label(shipper)),
            _coalesce_text(shipment_data.get("consignee_name"), consignee.get("name")),
            _coalesce_text(shipment_data.get("consignee_address"), _build_edi_address_label(consignee)),
            _coalesce_text(shipment_data.get("origin_port"), _build_edi_location_label(shipper)),
            _coalesce_text(shipment_data.get("destination_port"), _build_edi_location_label(consignee)),
            _coalesce_text(shipment_data.get("cargo_description")),
            _coalesce_number(invoice.get("amount")),
            _normalize_text(invoice.get("currency")),
            _append_shipment_note(shipment_row.get("notes"), f"{event_type} received"),
            shipment_row["id"],
        ),
    )
    description = _invoice_like_description(parsed_transaction)
    _insert_edi_shipment_event(
        conn,
        shipment_row["id"],
        event_type,
        f"{event_prefix}{(': ' + description) if description else '.'}",
    )
    return _build_apply_result(
        shipment_row["id"],
        shipment_ref,
        "created" if created else "updated",
        previous_status,
        new_status,
    )


def _apply_status_payload(conn, parsed_transaction, *, event_type, default_status="Active"):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    carrier_data = (parsed_transaction or {}).get("carrier") or {}
    shipment_ref = _coalesce_text(shipment_data.get("shipment_ref"), references.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError(f"{event_type} is missing a shipment reference.")

    carrier = _ensure_edi_carrier(
        conn,
        scac=carrier_data.get("scac") or shipment_data.get("carrier_scac"),
        name=carrier_data.get("name") or shipment_data.get("carrier_name"),
    )
    shipment_row, created = _ensure_edi_shipment(
        conn,
        shipment_ref,
        status=_coalesce_text(shipment_data.get("status"), default_status),
        carrier=carrier,
    )

    events = [event for event in (parsed_transaction or {}).get("events") or [] if event]
    latest_event = events[-1] if events else {}
    previous_status = shipment_row.get("status")
    new_status = _coalesce_text(latest_event.get("status"), shipment_data.get("status"), shipment_row.get("status"), default_status)

    conn.execute(
        """
        UPDATE shipments
        SET status = ?, carrier_id = ?, carrier_name = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            new_status,
            (carrier or {}).get("id") or shipment_row.get("carrier_id"),
            _coalesce_text((carrier or {}).get("name"), shipment_row.get("carrier_name")),
            _append_shipment_note(shipment_row.get("notes"), f"{event_type} received"),
            shipment_row["id"],
        ),
    )

    if events:
        for event in events:
            _insert_edi_shipment_event(
                conn,
                shipment_row["id"],
                event_type,
                _coalesce_text(event.get("description"), f"Shipment status updated from {event_type}."),
                location=event.get("location"),
                event_date=event.get("event_date"),
            )
    else:
        _insert_edi_shipment_event(
            conn,
            shipment_row["id"],
            event_type,
            f"Shipment status updated from {event_type}.",
        )

    return _build_apply_result(
        shipment_row["id"],
        shipment_ref,
        "created" if created else "updated",
        previous_status,
        new_status,
    )


def _apply_edi_204(conn, parsed_transaction):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    parties = (parsed_transaction or {}).get("parties") or {}
    shipment_ref = _coalesce_text(
        shipment_data.get("shipment_ref"),
        references.get("shipment_ref"),
    )
    if not shipment_ref:
        raise ValueError("Inbound 204 is missing a shipment reference.")

    carrier = _ensure_edi_carrier(
        conn,
        scac=shipment_data.get("carrier_scac"),
        name=shipment_data.get("carrier_name"),
    )
    current_row = _find_shipment_row(conn, shipment_ref)
    current = dict(current_row) if current_row else {}

    shipper = parties.get("shipper") or {}
    consignee = parties.get("consignee") or {}
    payload = {
        "status": _coalesce_text(shipment_data.get("status"), current.get("status"), "Booked"),
        "shipper_name": _coalesce_text(shipment_data.get("shipper_name"), current.get("shipper_name"), shipper.get("name")),
        "shipper_address": _coalesce_text(shipment_data.get("shipper_address"), current.get("shipper_address"), _build_edi_address_label(shipper)),
        "consignee_name": _coalesce_text(shipment_data.get("consignee_name"), current.get("consignee_name"), consignee.get("name")),
        "consignee_address": _coalesce_text(shipment_data.get("consignee_address"), current.get("consignee_address"), _build_edi_address_label(consignee)),
        "carrier_name": _coalesce_text(shipment_data.get("carrier_name"), current.get("carrier_name"), (carrier or {}).get("name")),
        "carrier_id": (carrier or {}).get("id") or current.get("carrier_id"),
        "origin_port": _coalesce_text(shipment_data.get("origin_port"), current.get("origin_port"), _build_edi_location_label(shipper)),
        "destination_port": _coalesce_text(shipment_data.get("destination_port"), current.get("destination_port"), _build_edi_location_label(consignee)),
        "etd": _coalesce_text(shipment_data.get("etd"), current.get("etd")),
        "eta": _coalesce_text(shipment_data.get("eta"), current.get("eta")),
        "cargo_description": _coalesce_text(shipment_data.get("cargo_description"), current.get("cargo_description")),
        "containers": _coalesce_text(shipment_data.get("containers"), current.get("containers")),
        "weight_kg": _coalesce_number(shipment_data.get("weight_kg"), current.get("weight_kg")),
        "volume_cbm": _coalesce_number(shipment_data.get("volume_cbm"), current.get("volume_cbm")),
        "notes": _append_shipment_note(current.get("notes"), shipment_data.get("notes") or "EDI 204 received"),
        "customer_name": _coalesce_text(current.get("customer_name"), shipment_data.get("shipper_name"), shipper.get("name")),
    }

    if current_row:
        conn.execute(
            """
            UPDATE shipments
            SET status = ?, shipper_name = ?, shipper_address = ?, consignee_name = ?, consignee_address = ?,
                carrier_name = ?, carrier_id = ?, origin_port = ?, destination_port = ?, etd = ?, eta = ?,
                cargo_description = ?, containers = ?, weight_kg = ?, volume_cbm = ?, notes = ?, customer_name = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload["status"],
                payload["shipper_name"],
                payload["shipper_address"],
                payload["consignee_name"],
                payload["consignee_address"],
                payload["carrier_name"],
                payload["carrier_id"],
                payload["origin_port"],
                payload["destination_port"],
                payload["etd"],
                payload["eta"],
                payload["cargo_description"],
                payload["containers"],
                payload["weight_kg"],
                payload["volume_cbm"],
                payload["notes"],
                payload["customer_name"],
                current["id"],
            ),
        )
        shipment_id = current["id"]
        action = "updated"
    else:
        cursor = conn.execute(
            """
            INSERT INTO shipments
            (
                shipment_ref, status, shipper_name, shipper_address, consignee_name, consignee_address,
                carrier_name, carrier_id, origin_port, destination_port, etd, eta, cargo_description,
                containers, weight_kg, volume_cbm, notes, customer_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_ref,
                payload["status"],
                payload["shipper_name"],
                payload["shipper_address"],
                payload["consignee_name"],
                payload["consignee_address"],
                payload["carrier_name"],
                payload["carrier_id"],
                payload["origin_port"],
                payload["destination_port"],
                payload["etd"],
                payload["eta"],
                payload["cargo_description"],
                payload["containers"],
                payload["weight_kg"],
                payload["volume_cbm"],
                payload["notes"],
                payload["customer_name"],
            ),
        )
        shipment_id = cursor.lastrowid
        action = "created"

    refresh_shipment_carbon(conn, shipment_id=shipment_id)
    _insert_edi_shipment_event(
        conn,
        shipment_id,
        "EDI 204",
        f"Load tender {action} from EDI 204.",
        location=_coalesce_text(payload["origin_port"], payload["destination_port"]),
    )
    return _build_apply_result(
        shipment_id,
        shipment_ref,
        action,
        current.get("status"),
        payload["status"],
    )


def _apply_edi_214(conn, parsed_transaction):
    return _apply_status_payload(conn, parsed_transaction, event_type="EDI 214", default_status="In Transit")


def _apply_edi_215(conn, parsed_transaction):
    return _apply_status_payload(conn, parsed_transaction, event_type="EDI 215", default_status="In Transit")


def _apply_edi_210(conn, parsed_transaction):
    return _apply_invoice_payload(
        conn,
        parsed_transaction,
        event_type="EDI 210",
        event_prefix="Freight invoice received",
    )


def _apply_edi_invoic(conn, parsed_transaction):
    return _apply_invoice_payload(
        conn,
        parsed_transaction,
        event_type="EDIFACT INVOIC",
        event_prefix="Invoice received",
    )


def _apply_edi_211(conn, parsed_transaction):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    parties = (parsed_transaction or {}).get("parties") or {}
    document = (parsed_transaction or {}).get("document") or {}
    shipment_ref = _coalesce_text(shipment_data.get("shipment_ref"), references.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("Inbound 211 is missing a shipment reference.")

    current_row = _find_shipment_row(conn, shipment_ref)
    current = dict(current_row) if current_row else {}
    shipper = parties.get("shipper") or {}
    consignee = parties.get("consignee") or {}
    previous_status = current.get("status")
    payload = {
        "status": _coalesce_text(shipment_data.get("status"), current.get("status"), "Booked"),
        "shipper_name": _coalesce_text(shipment_data.get("shipper_name"), current.get("shipper_name"), shipper.get("name")),
        "shipper_address": _coalesce_text(shipment_data.get("shipper_address"), current.get("shipper_address"), _build_edi_address_label(shipper)),
        "consignee_name": _coalesce_text(shipment_data.get("consignee_name"), current.get("consignee_name"), consignee.get("name")),
        "consignee_address": _coalesce_text(shipment_data.get("consignee_address"), current.get("consignee_address"), _build_edi_address_label(consignee)),
        "origin_port": _coalesce_text(shipment_data.get("origin_port"), current.get("origin_port"), _build_edi_location_label(shipper)),
        "destination_port": _coalesce_text(shipment_data.get("destination_port"), current.get("destination_port"), _build_edi_location_label(consignee)),
        "etd": _coalesce_text(shipment_data.get("etd"), current.get("etd")),
        "eta": _coalesce_text(shipment_data.get("eta"), current.get("eta")),
        "cargo_description": _coalesce_text(shipment_data.get("cargo_description"), current.get("cargo_description")),
        "weight_kg": _coalesce_number(shipment_data.get("weight_kg"), current.get("weight_kg")),
        "volume_cbm": _coalesce_number(shipment_data.get("volume_cbm"), current.get("volume_cbm")),
        "notes": _append_shipment_note(current.get("notes"), document.get("bol_number") or "EDI 211 received"),
        "customer_name": _coalesce_text(current.get("customer_name"), shipment_data.get("shipper_name"), shipper.get("name")),
    }

    if current_row:
        conn.execute(
            """
            UPDATE shipments
            SET status = ?, shipper_name = ?, shipper_address = ?, consignee_name = ?, consignee_address = ?,
                origin_port = ?, destination_port = ?, etd = ?, eta = ?, cargo_description = ?, weight_kg = ?,
                volume_cbm = ?, notes = ?, customer_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload["status"],
                payload["shipper_name"],
                payload["shipper_address"],
                payload["consignee_name"],
                payload["consignee_address"],
                payload["origin_port"],
                payload["destination_port"],
                payload["etd"],
                payload["eta"],
                payload["cargo_description"],
                payload["weight_kg"],
                payload["volume_cbm"],
                payload["notes"],
                payload["customer_name"],
                current["id"],
            ),
        )
        shipment_id = current["id"]
        action = "updated"
    else:
        cursor = conn.execute(
            """
            INSERT INTO shipments
            (shipment_ref, status, shipper_name, shipper_address, consignee_name, consignee_address,
             origin_port, destination_port, etd, eta, cargo_description, weight_kg, volume_cbm, notes, customer_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_ref,
                payload["status"],
                payload["shipper_name"],
                payload["shipper_address"],
                payload["consignee_name"],
                payload["consignee_address"],
                payload["origin_port"],
                payload["destination_port"],
                payload["etd"],
                payload["eta"],
                payload["cargo_description"],
                payload["weight_kg"],
                payload["volume_cbm"],
                payload["notes"],
                payload["customer_name"],
            ),
        )
        shipment_id = cursor.lastrowid
        action = "created"

    _insert_edi_shipment_event(
        conn,
        shipment_id,
        "EDI 211",
        f"Bill of lading {action} from EDI 211.",
        location=_coalesce_text(payload["origin_port"], payload["destination_port"]),
    )
    return _build_apply_result(shipment_id, shipment_ref, action, previous_status, payload["status"])


def _apply_edi_850(conn, parsed_transaction):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    parties = (parsed_transaction or {}).get("parties") or {}
    document = (parsed_transaction or {}).get("document") or {}
    shipment_ref = _coalesce_text(shipment_data.get("shipment_ref"), references.get("shipment_ref"), document.get("po_number"))
    if not shipment_ref:
        raise ValueError("Inbound 850 is missing a shipment reference.")

    current_row = _find_shipment_row(conn, shipment_ref)
    current = dict(current_row) if current_row else {}
    shipper = parties.get("shipper") or {}
    consignee = parties.get("consignee") or {}
    previous_status = current.get("status")
    payload = {
        "status": _coalesce_text(shipment_data.get("status"), current.get("status"), "Booked"),
        "shipper_name": _coalesce_text(shipment_data.get("shipper_name"), current.get("shipper_name"), shipper.get("name")),
        "shipper_address": _coalesce_text(shipment_data.get("shipper_address"), current.get("shipper_address"), _build_edi_address_label(shipper)),
        "consignee_name": _coalesce_text(shipment_data.get("consignee_name"), current.get("consignee_name"), consignee.get("name")),
        "consignee_address": _coalesce_text(shipment_data.get("consignee_address"), current.get("consignee_address"), _build_edi_address_label(consignee)),
        "origin_port": _coalesce_text(shipment_data.get("origin_port"), current.get("origin_port"), _build_edi_location_label(shipper)),
        "destination_port": _coalesce_text(shipment_data.get("destination_port"), current.get("destination_port"), _build_edi_location_label(consignee)),
        "etd": _coalesce_text(shipment_data.get("etd"), current.get("etd")),
        "eta": _coalesce_text(shipment_data.get("eta"), current.get("eta")),
        "cargo_description": _coalesce_text(shipment_data.get("cargo_description"), current.get("cargo_description")),
        "notes": _append_shipment_note(current.get("notes"), document.get("po_number") or "EDI 850 received"),
        "customer_name": _coalesce_text(current.get("customer_name"), shipment_data.get("shipper_name"), shipper.get("name")),
    }

    if current_row:
        conn.execute(
            """
            UPDATE shipments
            SET status = ?, shipper_name = ?, shipper_address = ?, consignee_name = ?, consignee_address = ?,
                origin_port = ?, destination_port = ?, etd = ?, eta = ?, cargo_description = ?, notes = ?,
                customer_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                payload["status"],
                payload["shipper_name"],
                payload["shipper_address"],
                payload["consignee_name"],
                payload["consignee_address"],
                payload["origin_port"],
                payload["destination_port"],
                payload["etd"],
                payload["eta"],
                payload["cargo_description"],
                payload["notes"],
                payload["customer_name"],
                current["id"],
            ),
        )
        shipment_id = current["id"]
        action = "updated"
    else:
        cursor = conn.execute(
            """
            INSERT INTO shipments
            (shipment_ref, status, shipper_name, shipper_address, consignee_name, consignee_address,
             origin_port, destination_port, etd, eta, cargo_description, notes, customer_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shipment_ref,
                payload["status"],
                payload["shipper_name"],
                payload["shipper_address"],
                payload["consignee_name"],
                payload["consignee_address"],
                payload["origin_port"],
                payload["destination_port"],
                payload["etd"],
                payload["eta"],
                payload["cargo_description"],
                payload["notes"],
                payload["customer_name"],
            ),
        )
        shipment_id = cursor.lastrowid
        action = "created"

    _insert_edi_shipment_event(conn, shipment_id, "EDI 850", f"Purchase order {action} from EDI 850.")
    return _build_apply_result(shipment_id, shipment_ref, action, previous_status, payload["status"])


def _apply_edi_856(conn, parsed_transaction):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    parties = (parsed_transaction or {}).get("parties") or {}
    shipment_ref = _coalesce_text(shipment_data.get("shipment_ref"), references.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("EDI 856 is missing a shipment reference.")

    shipment_row, created = _ensure_edi_shipment(conn, shipment_ref, status=_coalesce_text(shipment_data.get("status"), "Active"))
    shipper = parties.get("shipper") or {}
    consignee = parties.get("consignee") or {}
    previous_status = shipment_row.get("status")
    new_status = _coalesce_text(shipment_data.get("status"), shipment_row.get("status"), "Active")

    conn.execute(
        """
        UPDATE shipments
        SET status = ?, shipper_name = COALESCE(NULLIF(?, ''), shipper_name),
            shipper_address = COALESCE(NULLIF(?, ''), shipper_address),
            consignee_name = COALESCE(NULLIF(?, ''), consignee_name),
            consignee_address = COALESCE(NULLIF(?, ''), consignee_address),
            origin_port = COALESCE(NULLIF(?, ''), origin_port),
            destination_port = COALESCE(NULLIF(?, ''), destination_port),
            cargo_description = COALESCE(NULLIF(?, ''), cargo_description),
            containers = COALESCE(NULLIF(?, ''), containers),
            weight_kg = COALESCE(?, weight_kg),
            notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            new_status,
            _coalesce_text(shipment_data.get("shipper_name"), shipper.get("name")),
            _coalesce_text(shipment_data.get("shipper_address"), _build_edi_address_label(shipper)),
            _coalesce_text(shipment_data.get("consignee_name"), consignee.get("name")),
            _coalesce_text(shipment_data.get("consignee_address"), _build_edi_address_label(consignee)),
            _coalesce_text(shipment_data.get("origin_port"), _build_edi_location_label(shipper)),
            _coalesce_text(shipment_data.get("destination_port"), _build_edi_location_label(consignee)),
            _coalesce_text(shipment_data.get("cargo_description")),
            _coalesce_text(shipment_data.get("containers")),
            _coalesce_number(shipment_data.get("weight_kg")),
            _append_shipment_note(shipment_row.get("notes"), "EDI 856 received"),
            shipment_row["id"],
        ),
    )
    _insert_edi_shipment_event(conn, shipment_row["id"], "EDI 856", "Ship notice received from EDI 856.")
    return _build_apply_result(shipment_row["id"], shipment_ref, "created" if created else "updated", previous_status, new_status)


def _apply_edi_iftmin(conn, parsed_transaction):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    if shipment_data:
        shipment_data.setdefault("status", "Booked")
    return _apply_edi_204(conn, parsed_transaction)


def _apply_edi_iftsta(conn, parsed_transaction):
    return _apply_status_payload(conn, parsed_transaction, event_type="EDIFACT IFTSTA", default_status="In Transit")


def _apply_edi_990(conn, parsed_transaction):
    shipment_data = (parsed_transaction or {}).get("shipment") or {}
    references = (parsed_transaction or {}).get("references") or {}
    carrier_data = (parsed_transaction or {}).get("carrier") or {}
    response = (parsed_transaction or {}).get("response") or {}

    shipment_ref = _coalesce_text(shipment_data.get("shipment_ref"), references.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("Inbound 990 is missing a shipment reference.")

    carrier = _ensure_edi_carrier(
        conn,
        scac=carrier_data.get("scac") or shipment_data.get("carrier_scac"),
        name=carrier_data.get("name"),
    )
    shipment_row, created = _ensure_edi_shipment(
        conn,
        shipment_ref,
        status=_coalesce_text(response.get("status"), shipment_data.get("status"), "Booked"),
        carrier=carrier,
    )

    new_status = _coalesce_text(response.get("status"), shipment_data.get("status"), shipment_row.get("status"))
    response_label = _coalesce_text(response.get("label"), "Tender response received from EDI 990.")
    notes = _append_shipment_note(shipment_row.get("notes"), response_label)

    conn.execute(
        """
        UPDATE shipments
        SET status = ?, carrier_id = ?, carrier_name = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            new_status,
            (carrier or {}).get("id") or shipment_row.get("carrier_id"),
            _coalesce_text((carrier or {}).get("name"), shipment_row.get("carrier_name")),
            notes,
            shipment_row["id"],
        ),
    )
    _insert_edi_shipment_event(
        conn,
        shipment_row["id"],
        "EDI 990",
        response_label,
    )
    return _build_apply_result(
        shipment_row["id"],
        shipment_ref,
        "created" if created else "updated",
        shipment_row.get("status"),
        new_status,
    )


def find_shipment_by_ref(ref):
    clean_ref = _normalize_text(ref)
    if not clean_ref:
        return None

    init_tms_db()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
            (clean_ref,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_shipment_refs():
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT shipment_ref FROM shipments WHERE shipment_ref IS NOT NULL AND shipment_ref != ''"
        ).fetchall()
        return [row["shipment_ref"] for row in rows]
    finally:
        conn.close()


def _log_freight_claim_event(conn, shipment_ref, event_type, description):
    shipment = conn.execute(
        "SELECT id FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
        (shipment_ref,),
    ).fetchone()
    if not shipment:
        return
    conn.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
        (shipment["id"], event_type, description),
    )


def _resolve_claim_carrier_id(conn, shipment):
    if not shipment:
        return None
    shipment_data = dict(shipment)
    if shipment_data.get("carrier_id"):
        return shipment_data["carrier_id"]

    carrier_name = _normalize_text(shipment_data.get("carrier_name"))
    if not carrier_name:
        return None

    carrier = conn.execute(
        """
        SELECT id
        FROM tms_carriers
        WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
        LIMIT 1
        """,
        (carrier_name,),
    ).fetchone()
    return carrier["id"] if carrier else None


def _claim_base_query():
    return """
        SELECT
            fc.*,
            COALESCE(tc.name, COALESCE(s.carrier_name, '')) AS carrier_name,
            COALESCE(tc.scac, '') AS carrier_scac,
            COALESCE(s.status, '') AS shipment_status,
            COALESCE(s.origin_port, '') AS origin_port,
            COALESCE(s.destination_port, '') AS destination_port,
            COALESCE(s.mode, '') AS mode,
            COALESCE(s.customer_name, COALESCE(s.shipper_name, '')) AS customer_name,
            COALESCE(s.shipper_name, '') AS shipper_name,
            COALESCE(s.consignee_name, '') AS consignee_name
        FROM freight_claims fc
        LEFT JOIN shipments s
          ON UPPER(COALESCE(s.shipment_ref, '')) = UPPER(COALESCE(fc.shipment_ref, ''))
        LEFT JOIN tms_carriers tc
          ON tc.id = fc.carrier_id
    """


def _claim_row_to_dict(row):
    if not row:
        return None

    claim = dict(row)
    claim["claim_type"] = _normalize_text(claim.get("claim_type"))
    claim["status"] = _normalize_text(claim.get("status")) or "Filed"
    claim["shipment_ref"] = _normalize_text(claim.get("shipment_ref"))
    claim["description"] = _normalize_text(claim.get("description"))
    claim["currency"] = _normalize_currency(claim.get("currency"))
    claim["carrier_name"] = _normalize_text(claim.get("carrier_name"))
    claim["evidence_path"] = _normalize_text(claim.get("evidence_path"))
    claim["carrier_notes"] = _normalize_text(claim.get("carrier_notes"))
    claim["counter_offer"] = claim.get("counter_offer")
    claim["claimed_amount"] = round(float(claim.get("claimed_amount") or 0), 2)
    claim["settlement_amount"] = (
        round(float(claim["settlement_amount"]), 2)
        if claim.get("settlement_amount") is not None
        else None
    )
    claim["responded_at_display"] = _format_tracking_datetime(claim.get("responded_at"))
    claim["settled_at_display"] = _format_tracking_datetime(claim.get("settled_at"))
    claim["created_at_display"] = _format_tracking_datetime(claim.get("created_at"))
    return claim


def list_freight_claims(*, status="", carrier_id=None, claim_type="", shipment_ref=""):
    init_tms_db()
    filters = []
    params = []

    clean_status = _normalize_text(status)
    if clean_status:
        filters.append("fc.status = ?")
        params.append(_normalize_claim_status(clean_status))

    clean_claim_type = _normalize_text(claim_type)
    if clean_claim_type:
        filters.append("fc.claim_type = ?")
        params.append(_normalize_claim_type(clean_claim_type))

    clean_shipment_ref = _normalize_text(shipment_ref)
    if clean_shipment_ref:
        filters.append("UPPER(fc.shipment_ref) = UPPER(?)")
        params.append(clean_shipment_ref)

    clean_carrier_id = _normalize_text(carrier_id)
    if clean_carrier_id:
        if not clean_carrier_id.isdigit():
            raise ValueError("Carrier filter is invalid.")
        filters.append("fc.carrier_id = ?")
        params.append(int(clean_carrier_id))

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    conn = get_db()
    try:
        rows = conn.execute(
            f"""
            {_claim_base_query()}
            {where_clause}
            ORDER BY
                CASE fc.status
                    WHEN 'Under Review' THEN 0
                    WHEN 'Filed' THEN 1
                    WHEN 'Approved' THEN 2
                    WHEN 'Paid' THEN 3
                    WHEN 'Denied' THEN 4
                    ELSE 5
                END,
                datetime(fc.created_at) DESC,
                fc.id DESC
            """,
            params,
        ).fetchall()
        return [_claim_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_freight_claim(claim_id, *, response_token=None):
    init_tms_db()
    conn = get_db()
    try:
        clean_token = _normalize_text(response_token)
        if clean_token:
            row = conn.execute(
                f"""
                {_claim_base_query()}
                WHERE fc.id = ? AND fc.response_token = ?
                LIMIT 1
                """,
                (claim_id, clean_token),
            ).fetchone()
        else:
            row = conn.execute(
                f"""
                {_claim_base_query()}
                WHERE fc.id = ?
                LIMIT 1
                """,
                (claim_id,),
            ).fetchone()
        return _claim_row_to_dict(row)
    finally:
        conn.close()


def list_freight_claim_filter_carriers():
    init_tms_db()
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT DISTINCT
                c.id,
                c.name
            FROM freight_claims fc
            JOIN tms_carriers c ON c.id = fc.carrier_id
            ORDER BY c.name COLLATE NOCASE ASC
            """
        ).fetchall()
    finally:
        conn.close()


def create_freight_claim(*, shipment_ref, claim_type, description, claimed_amount, currency="USD", evidence_path=""):
    init_tms_db()
    clean_ref = _normalize_text(shipment_ref)
    clean_description = _normalize_text(description)
    clean_evidence_path = _normalize_text(evidence_path)
    normalized_claim_type = _normalize_claim_type(claim_type)
    normalized_currency = _normalize_currency(currency)
    parsed_amount = _parse_required_amount(claimed_amount, "Claim amount")

    if not clean_ref:
        raise ValueError("Shipment reference is required.")
    if not clean_description:
        raise ValueError("Claim description is required.")

    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT * FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise ValueError("Shipment reference was not found.")

        response_token = _generate_claim_response_token(conn)
        cursor = conn.execute(
            """
            INSERT INTO freight_claims
                (shipment_ref, carrier_id, claim_type, description, claimed_amount, currency,
                 status, evidence_path, response_token, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Filed', ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                shipment["shipment_ref"],
                _resolve_claim_carrier_id(conn, shipment),
                normalized_claim_type,
                clean_description,
                parsed_amount,
                normalized_currency,
                clean_evidence_path,
                response_token,
            ),
        )
        claim_id = cursor.lastrowid
        _log_freight_claim_event(
            conn,
            shipment["shipment_ref"],
            "Claim Filed",
            f"{normalized_claim_type} claim filed for {parsed_amount:,.2f} {normalized_currency}.",
        )
        conn.commit()
        return get_freight_claim(claim_id)
    finally:
        conn.close()


def respond_to_freight_claim(claim_id, *, response_token, carrier_notes="", counter_offer=None):
    init_tms_db()
    clean_token = _normalize_text(response_token)
    clean_notes = _normalize_text(carrier_notes)
    parsed_counter_offer = _parse_optional_amount(counter_offer, "Counter-offer")
    if not clean_token:
        raise ValueError("Claim response token is required.")
    if not clean_notes and parsed_counter_offer is None:
        raise ValueError("Enter carrier notes or a counter-offer.")

    conn = get_db()
    try:
        claim = conn.execute(
            "SELECT * FROM freight_claims WHERE id = ? AND response_token = ?",
            (claim_id, clean_token),
        ).fetchone()
        if not claim:
            raise ValueError("Claim response link is invalid.")

        current_status = _normalize_text(claim["status"]) or "Filed"
        if current_status in {"Paid", "Denied"}:
            raise ValueError("This claim is closed and cannot accept carrier responses.")

        next_status = "Under Review" if current_status == "Filed" else current_status
        conn.execute(
            """
            UPDATE freight_claims
            SET carrier_notes = ?,
                counter_offer = ?,
                responded_at = CURRENT_TIMESTAMP,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                clean_notes,
                parsed_counter_offer,
                next_status,
                claim_id,
            ),
        )

        response_summary = "Carrier responded to the claim"
        if parsed_counter_offer is not None:
            response_summary += f" with a counter-offer of {parsed_counter_offer:,.2f} {claim['currency'] or 'USD'}"
        _log_freight_claim_event(conn, claim["shipment_ref"], "Carrier Claim Response", response_summary)
        conn.commit()
        return get_freight_claim(claim_id)
    finally:
        conn.close()


def update_freight_claim(claim_id, *, status=None, settlement_amount=None):
    init_tms_db()
    conn = get_db()
    try:
        claim = conn.execute("SELECT * FROM freight_claims WHERE id = ?", (claim_id,)).fetchone()
        if not claim:
            raise ValueError("Claim not found.")

        current_status = _normalize_text(claim["status"]) or "Filed"
        target_status = _normalize_claim_status(status or current_status)
        if target_status != current_status:
            allowed_statuses = CLAIM_STATUS_TRANSITIONS.get(current_status, set())
            if target_status not in allowed_statuses:
                raise ValueError(
                    f"Cannot move a {current_status.lower()} claim to {target_status.lower()}."
                )

        current_settlement = claim["settlement_amount"]
        raw_settlement = _normalize_text(settlement_amount)
        if raw_settlement == "":
            effective_settlement = current_settlement
        else:
            effective_settlement = _parse_required_amount(raw_settlement, "Settlement amount")

        settled_at = claim["settled_at"]
        if target_status == "Denied":
            effective_settlement = None
            settled_at = None
        elif target_status == "Paid":
            if effective_settlement is None:
                raise ValueError("Settlement amount is required before marking a claim paid.")
            settled_at = datetime.now().isoformat(timespec="seconds")
        elif target_status != "Paid":
            settled_at = None if target_status != current_status else claim["settled_at"]

        conn.execute(
            """
            UPDATE freight_claims
            SET status = ?,
                settlement_amount = ?,
                settled_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                target_status,
                effective_settlement,
                settled_at,
                claim_id,
            ),
        )

        description = f"Claim marked {target_status.lower()}."
        if target_status in {"Approved", "Paid"} and effective_settlement is not None:
            description = (
                f"Claim marked {target_status.lower()} at {effective_settlement:,.2f} "
                f"{claim['currency'] or 'USD'}."
            )
        elif target_status == "Denied":
            description = "Claim denied."

        _log_freight_claim_event(conn, claim["shipment_ref"], "Claim Updated", description)
        conn.commit()
        return get_freight_claim(claim_id)
    finally:
        conn.close()


def list_documents(limit=20):
    init_tms_db()
    safe_limit = max(int(limit or 20), 1)
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                d.*,
                CASE WHEN s.id IS NULL THEN 0 ELSE 1 END AS has_linked_shipment
            FROM tms_documents d
            LEFT JOIN shipments s
              ON UPPER(COALESCE(s.shipment_ref, '')) = UPPER(COALESCE(d.shipment_ref, ''))
            ORDER BY datetime(d.uploaded_at) DESC, d.id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _apply_document_fields_to_shipment(conn, shipment_ref, extracted_payload):
    shipment = conn.execute(
        "SELECT * FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
        (shipment_ref,),
    ).fetchone()
    if not shipment:
        return None, False

    fields = dict((extracted_payload or {}).get("fields") or {})
    updates = []
    params = []
    for column, key in [
        ("shipper_name", "shipper"),
        ("consignee_name", "consignee"),
        ("origin_port", "origin"),
        ("destination_port", "destination"),
    ]:
        value = _normalize_text(fields.get(key))
        if value:
            updates.append(f"{column} = ?")
            params.append(value)

    amount_value = _parse_amount_value(fields.get("amount"))
    if amount_value is not None:
        updates.append("freight_rate = ?")
        params.append(amount_value)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(shipment["shipment_ref"])
        conn.execute(
            f"UPDATE shipments SET {', '.join(updates)} WHERE shipment_ref = ?",
            params,
        )
        refresh_shipment_carbon(conn, shipment_ref=shipment["shipment_ref"])
        shipment = conn.execute(
            "SELECT * FROM shipments WHERE shipment_ref = ?",
            (shipment["shipment_ref"],),
        ).fetchone()
        return dict(shipment), True

    return dict(shipment), False


def save_document_record(*, filename, doc_type, extracted_payload, shipment_ref="", apply_to_shipment=False):
    init_tms_db()
    clean_filename = _normalize_text(filename)
    clean_doc_type = _normalize_text(doc_type) or "Unknown"
    clean_ref = _normalize_text(shipment_ref)
    if not clean_filename:
        raise ValueError("Document filename is required.")

    serialized_payload = json.dumps(extracted_payload or {}, ensure_ascii=True)

    conn = get_db()
    try:
        linked_shipment = None
        if clean_ref:
            shipment_row = conn.execute(
                "SELECT * FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
                (clean_ref,),
            ).fetchone()
            if shipment_row:
                clean_ref = shipment_row["shipment_ref"]
                linked_shipment = dict(shipment_row)

        status = "linked" if linked_shipment else "reviewed"
        cursor = conn.execute(
            """
            INSERT INTO tms_documents
                (filename, doc_type, extracted_json, shipment_ref, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                clean_filename,
                clean_doc_type,
                serialized_payload,
                clean_ref or None,
                status,
            ),
        )

        applied_updates = False
        if linked_shipment:
            if apply_to_shipment:
                linked_shipment, applied_updates = _apply_document_fields_to_shipment(
                    conn,
                    clean_ref,
                    extracted_payload,
                )

            event_description = f"{clean_doc_type} uploaded from {clean_filename}"
            if applied_updates:
                event_description += " and reviewed fields were applied"
            conn.execute(
                "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                (
                    linked_shipment["id"],
                    "Document Linked",
                    event_description,
                ),
            )

        conn.commit()
        return {
            "id": cursor.lastrowid,
            "status": status,
            "shipment": linked_shipment,
            "applied_updates": applied_updates,
        }
    finally:
        conn.close()


def get_or_create_pod_token(shipment_ref):
    init_tms_db()
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        raise ValueError("Shipment reference is required.")

    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT shipment_ref, pod_token FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise LookupError("Shipment not found.")
        token = _normalize_text(shipment["pod_token"])
        if not token:
            token = _generate_pod_token(conn)
            conn.execute(
                "UPDATE shipments SET pod_token = ?, updated_at = CURRENT_TIMESTAMP WHERE shipment_ref = ?",
                (token, shipment["shipment_ref"]),
            )
            conn.commit()
        return token
    finally:
        conn.close()


def get_pod_record(shipment_ref):
    init_tms_db()
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        return None

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM pod_records WHERE UPPER(shipment_ref) = UPPER(?)",
            (clean_ref,),
        ).fetchone()
        if not row:
            return None
        pod = dict(row)
        pod["delivered_at_display"] = _format_tracking_datetime(pod.get("delivered_at"))
        pod["photo_available"] = bool(_normalize_text(pod.get("photo_path")) and os.path.exists(pod.get("photo_path")))
        return pod
    finally:
        conn.close()


def save_pod_record(*, shipment_ref, recipient_name, signature_data, photo_path, delivered_at, notes=""):
    init_tms_db()
    clean_ref = _normalize_text(shipment_ref)
    clean_recipient = _normalize_text(recipient_name)
    clean_signature = _normalize_text(signature_data)
    clean_photo_path = _normalize_text(photo_path)
    clean_notes = _normalize_text(notes)
    delivered_dt = _parse_tracking_datetime(_normalize_text(delivered_at))

    if not clean_ref:
        raise ValueError("Shipment reference is required.")
    if not clean_recipient:
        raise ValueError("Recipient name is required.")
    if not clean_signature.startswith("data:image/"):
        raise ValueError("A signature is required.")
    if not delivered_dt:
        raise ValueError("Delivery timestamp is required.")

    delivered_value = delivered_dt.isoformat()

    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT * FROM shipments WHERE UPPER(shipment_ref) = UPPER(?)",
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise LookupError("Shipment not found.")

        clean_ref = shipment["shipment_ref"]
        existing = conn.execute(
            "SELECT id FROM pod_records WHERE shipment_ref = ?",
            (clean_ref,),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE pod_records
                SET recipient_name = ?, signature_data = ?, photo_path = ?, delivered_at = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE shipment_ref = ?
                """,
                (
                    clean_recipient,
                    clean_signature,
                    clean_photo_path or None,
                    delivered_value,
                    clean_notes,
                    clean_ref,
                ),
            )
            pod_id = existing["id"]
        else:
            cursor = conn.execute(
                """
                INSERT INTO pod_records
                    (shipment_ref, recipient_name, signature_data, photo_path, delivered_at, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_ref,
                    clean_recipient,
                    clean_signature,
                    clean_photo_path or None,
                    delivered_value,
                    clean_notes,
                ),
            )
            pod_id = cursor.lastrowid

        conn.execute(
            """
            UPDATE shipments
            SET status = 'Delivered', updated_at = CURRENT_TIMESTAMP
            WHERE shipment_ref = ?
            """,
            (clean_ref,),
        )
        conn.execute(
            """
            INSERT INTO shipment_events (shipment_id, event_type, description, event_date, created_by)
            VALUES (?, 'Proof of Delivery', ?, ?, 'pod')
            """,
            (
                shipment["id"],
                f"Proof of delivery captured for {clean_recipient}.",
                delivered_value,
            ),
        )
        conn.commit()
        return {
            "id": pod_id,
            "shipment_ref": clean_ref,
            "recipient_name": clean_recipient,
            "signature_data": clean_signature,
            "photo_path": clean_photo_path,
            "delivered_at": delivered_value,
            "notes": clean_notes,
        }
    finally:
        conn.close()


def _load_fmcsa_json(url, web_key):
    response = requests.get(url, params={"webKey": web_key}, timeout=15)
    if response.status_code == 404:
        raise LookupError("FMCSA returned no carrier data for that DOT number.")
    if response.status_code == 401:
        raise ValueError("FMCSA rejected the configured web key.")
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError("FMCSA returned an unexpected response.")
    return payload


def fetch_fmcsa_safety_snapshot(dot_number, web_key=None):
    clean_dot = _normalize_dot_number(dot_number)
    if not clean_dot:
        raise ValueError("Carrier DOT number is required.")

    resolved_web_key = _normalize_text(web_key) or _fmcsa_web_key()
    if not resolved_web_key:
        raise ValueError("FMCSA web key is not configured.")

    carrier_url = FMCSA_CARRIER_URL_TEMPLATE.format(dot=clean_dot)
    authority_url = FMCSA_AUTHORITY_URL_TEMPLATE.format(dot=clean_dot)

    carrier_payload = _load_fmcsa_json(carrier_url, resolved_web_key)
    authority_payload = _load_fmcsa_json(authority_url, resolved_web_key)

    return {
        "dot_number": clean_dot,
        "safety_rating": _extract_fmcsa_safety_rating(carrier_payload),
        "insurance_status": _extract_fmcsa_insurance_status(authority_payload or carrier_payload),
        "auth_status": _extract_fmcsa_auth_status(authority_payload or carrier_payload),
        "insurance_expires_at": _extract_fmcsa_insurance_expiry(authority_payload or carrier_payload),
        "last_checked": datetime.utcnow().replace(microsecond=0).isoformat(),
        "fmcsa_source_url": authority_url,
    }


def refresh_carrier_safety(carrier_id, web_key=None):
    init_tms_db()
    conn = get_db()
    try:
        carrier = conn.execute(
            "SELECT * FROM tms_carriers WHERE id = ?",
            (carrier_id,),
        ).fetchone()
        if not carrier:
            raise LookupError("Carrier not found.")

        clean_dot = _normalize_dot_number(carrier["dot_number"])
        if not clean_dot:
            raise ValueError("Carrier DOT number is required before refreshing FMCSA safety data.")

        snapshot = fetch_fmcsa_safety_snapshot(clean_dot, web_key=web_key)
        conn.execute(
            """
            UPDATE tms_carriers
            SET dot_number = ?, safety_rating = ?, insurance_status = ?, auth_status = ?,
                insurance_expires_at = ?, last_checked = ?, fmcsa_source_url = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                snapshot["dot_number"],
                snapshot["safety_rating"],
                snapshot["insurance_status"],
                snapshot["auth_status"],
                snapshot["insurance_expires_at"] or None,
                snapshot["last_checked"],
                snapshot["fmcsa_source_url"],
                carrier_id,
            ),
        )
        conn.commit()
        refreshed = conn.execute(
            "SELECT * FROM tms_carriers WHERE id = ?",
            (carrier_id,),
        ).fetchone()
        return _decorate_carrier_row(refreshed)
    finally:
        conn.close()


def _hydrate_intake_row(row):
    if not row:
        return None

    item = dict(row)
    try:
        extracted_payload = json.loads(item.get("extracted_json") or "{}")
    except json.JSONDecodeError:
        extracted_payload = {}
    if not isinstance(extracted_payload, dict):
        extracted_payload = {}

    raw_fields = extracted_payload.get("fields") or {}
    fields = {}
    if isinstance(raw_fields, dict):
        for key, value in raw_fields.items():
            if isinstance(value, dict):
                fields[key] = {
                    "value": _normalize_text(value.get("value")),
                    "confidence": int(value.get("confidence") or 0),
                    "source": _normalize_text(value.get("source")),
                }
            else:
                fields[key] = {"value": _normalize_text(value), "confidence": 0, "source": ""}

    warnings = extracted_payload.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = []

    extracted_payload["fields"] = fields
    extracted_payload["warnings"] = [_normalize_text(warning) for warning in warnings if _normalize_text(warning)]
    extracted_payload["source_kind"] = _normalize_text(extracted_payload.get("source_kind")) or "email_text"
    extracted_payload["source_name"] = _normalize_text(extracted_payload.get("source_name")) or "Email text"
    extracted_payload["text_excerpt"] = _normalize_text(extracted_payload.get("text_excerpt")) or _normalize_text(item.get("raw_text"))[:4000]
    extracted_payload["reviewed_at"] = _normalize_text(extracted_payload.get("reviewed_at"))

    item["extracted_json"] = extracted_payload
    item["fields"] = fields
    item["warnings"] = extracted_payload["warnings"]
    item["source_kind"] = extracted_payload["source_kind"]
    item["source_name"] = extracted_payload["source_name"]
    item["text_excerpt"] = extracted_payload["text_excerpt"]
    item["reviewed_at"] = extracted_payload["reviewed_at"]
    item["overall_confidence"] = int(item.get("confidence") or 0)
    item["field_confidence"] = {
        key: field["confidence"]
        for key, field in fields.items()
        if field.get("value")
    }
    item["has_linked_shipment"] = bool(_normalize_text(item.get("shipment_ref")))
    return item


def get_intake_document(intake_id):
    init_tms_db()
    try:
        safe_id = int(intake_id or 0)
    except (TypeError, ValueError):
        return None
    if safe_id <= 0:
        return None

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM intake_documents WHERE id = ?",
            (safe_id,),
        ).fetchone()
        return _hydrate_intake_row(row)
    finally:
        conn.close()


def list_intake_documents(limit=25):
    init_tms_db()
    safe_limit = max(int(limit or 25), 1)
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM intake_documents
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
        return [_hydrate_intake_row(row) for row in rows]
    finally:
        conn.close()


def create_intake_document(*, raw_text, extracted_payload, confidence=0, shipment_ref="", status="processed"):
    init_tms_db()
    clean_text = (raw_text or "").strip()
    if not clean_text:
        raise ValueError("Raw intake text is required.")

    serialized_payload = json.dumps(extracted_payload or {}, ensure_ascii=True)
    clean_ref = _normalize_text(shipment_ref)
    clean_status = _normalize_text(status) or "processed"

    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO intake_documents (raw_text, extracted_json, confidence, shipment_ref, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                clean_text,
                serialized_payload,
                int(confidence or 0),
                clean_ref or None,
                clean_status,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM intake_documents WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return _hydrate_intake_row(row)
    finally:
        conn.close()


def update_intake_document(intake_id, *, extracted_payload=None, confidence=None, shipment_ref=None, status=None, raw_text=None):
    init_tms_db()
    try:
        safe_id = int(intake_id or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Intake document id is invalid.") from exc
    if safe_id <= 0:
        raise ValueError("Intake document id is invalid.")

    conn = get_db()
    try:
        existing_row = conn.execute(
            "SELECT * FROM intake_documents WHERE id = ?",
            (safe_id,),
        ).fetchone()
        if not existing_row:
            raise LookupError("Intake document was not found.")

        updates = []
        params = []
        if raw_text is not None:
            clean_text = (raw_text or "").strip()
            if not clean_text:
                raise ValueError("Raw intake text cannot be empty.")
            updates.append("raw_text = ?")
            params.append(clean_text)
        if extracted_payload is not None:
            updates.append("extracted_json = ?")
            params.append(json.dumps(extracted_payload or {}, ensure_ascii=True))
        if confidence is not None:
            updates.append("confidence = ?")
            params.append(int(confidence or 0))
        if shipment_ref is not None:
            updates.append("shipment_ref = ?")
            params.append(_normalize_text(shipment_ref) or None)
        if status is not None:
            updates.append("status = ?")
            params.append(_normalize_text(status) or existing_row["status"])

        if updates:
            params.append(safe_id)
            conn.execute(
                f"UPDATE intake_documents SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            conn.commit()

        row = conn.execute(
            "SELECT * FROM intake_documents WHERE id = ?",
            (safe_id,),
        ).fetchone()
        return _hydrate_intake_row(row)
    finally:
        conn.close()


def create_shipment_from_intake(intake_id, payload):
    init_tms_db()
    try:
        safe_id = int(intake_id or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Intake document id is invalid.") from exc
    if safe_id <= 0:
        raise ValueError("Intake document id is invalid.")

    conn = get_db()
    try:
        intake_row = conn.execute(
            "SELECT * FROM intake_documents WHERE id = ?",
            (safe_id,),
        ).fetchone()
        if not intake_row:
            raise LookupError("Intake document was not found.")

        intake = _hydrate_intake_row(intake_row)
        existing_ref = _normalize_text(intake.get("shipment_ref"))
        if existing_ref:
            existing_snapshot = get_shipment_snapshot(existing_ref)
            if existing_snapshot:
                return {"shipment": existing_snapshot, "intake": intake, "created": False}

        customer_name = _normalize_text(payload.get("customer_name")) or _normalize_text(payload.get("shipper_name"))
        consignee_name = _normalize_text(payload.get("consignee_name"))
        origin_port = _normalize_text(payload.get("origin_port"))
        destination_port = _normalize_text(payload.get("destination_port"))
        if not customer_name:
            raise ValueError("Shipper is required before creating a shipment.")
        if not consignee_name:
            raise ValueError("Consignee is required before creating a shipment.")
        if not origin_port or not destination_port:
            raise ValueError("Origin and destination are required before creating a shipment.")

        ref = generate_ref()
        notes = _normalize_text(payload.get("notes"))
        intake_note = f"Created from intake #{safe_id}"
        if notes:
            notes = f"{notes} | {intake_note}"
        else:
            notes = intake_note

        cursor = conn.execute(
            """
            INSERT INTO shipments
                (
                    shipment_ref, status, customer_name, shipper_name, shipper_address, consignee_name, consignee_address,
                    carrier_name, origin_port, destination_port, mode, etd, eta, cargo_description, containers,
                    weight_kg, volume_cbm, freight_rate, currency, incoterm, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref,
                _normalize_text(payload.get("status")) or "Draft",
                customer_name,
                _normalize_text(payload.get("shipper_name")) or customer_name,
                _normalize_text(payload.get("shipper_address")),
                consignee_name,
                _normalize_text(payload.get("consignee_address")),
                _normalize_text(payload.get("carrier_name")),
                origin_port,
                destination_port,
                _normalize_mode(payload.get("mode")),
                _normalize_text(payload.get("etd")),
                _normalize_text(payload.get("eta")),
                _normalize_text(payload.get("cargo_description")),
                _normalize_text(payload.get("containers")),
                _parse_optional_number(payload.get("weight_kg"), "Weight (kg)"),
                _parse_optional_number(payload.get("volume_cbm"), "Volume (cbm)"),
                _parse_optional_number(payload.get("freight_rate"), "Freight rate"),
                _normalize_text(payload.get("currency")).upper(),
                _normalize_text(payload.get("incoterm")).upper(),
                notes,
            ),
        )
        conn.execute(
            """
            INSERT INTO shipment_events (shipment_id, event_type, description, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (
                cursor.lastrowid,
                "Created",
                f"Shipment {ref} created from intake #{safe_id}.",
                "intake",
            ),
        )
        conn.execute(
            """
            UPDATE intake_documents
            SET shipment_ref = ?, status = ?
            WHERE id = ?
            """,
            (ref, "shipment_created", safe_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "shipment": get_shipment_snapshot(ref),
        "intake": get_intake_document(safe_id),
        "created": True,
    }


def _upsert_carrier(conn, carrier):
    scac = _normalize_scac(carrier.get("scac"))
    name = _normalize_text(carrier.get("name"))
    country = _normalize_text(carrier.get("country"))
    contact_email = _normalize_text(carrier.get("contact_email"))
    contact_phone = _normalize_text(carrier.get("contact_phone"))

    row = conn.execute(
        "SELECT id FROM tms_carriers WHERE scac = ?",
        (scac,),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE tms_carriers
            SET name = ?, country = ?, contact_email = ?, contact_phone = ?, active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                name,
                country,
                contact_email,
                contact_phone,
                row["id"],
            ),
        )
        return row["id"]

    cursor = conn.execute(
        """
        INSERT INTO tms_carriers (name, scac, country, contact_email, contact_phone, active, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        """,
        (
            name,
            scac,
            country,
            contact_email,
            contact_phone,
        ),
    )
    return cursor.lastrowid


def _upsert_lane(conn, lane):
    row = conn.execute(
        "SELECT id FROM tms_lanes WHERE lane_code = ?",
        (lane["lane_code"],),
    ).fetchone()
    params = (
        lane["origin_name"],
        lane["destination_name"],
        lane["mode"],
        lane["avg_transit_days"],
        lane["weekly_shipments"],
    )
    if row:
        conn.execute(
            """
            UPDATE tms_lanes
            SET origin_name = ?, destination_name = ?, mode = ?,
                avg_transit_days = ?, weekly_shipments = ?, active = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            params + (row["id"],),
        )
        return row["id"]

    cursor = conn.execute(
        """
        INSERT INTO tms_lanes
        (lane_code, origin_name, destination_name, mode, avg_transit_days, weekly_shipments, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            lane["lane_code"],
            lane["origin_name"],
            lane["destination_name"],
            lane["mode"],
            lane["avg_transit_days"],
            lane["weekly_shipments"],
        ),
    )
    return cursor.lastrowid


def _upsert_portal_token(conn, portal_token):
    token = _normalize_portal_token(portal_token.get("token"))
    customer_name = _normalize_text(portal_token.get("customer_name"))
    if not token or not customer_name:
        raise ValueError("Portal token and customer name are required.")

    expires_at = _normalize_text(portal_token.get("expires_at")) or _default_portal_token_expiry()

    params = (
        customer_name,
        _normalize_text(portal_token.get("email")),
        _serialize_shipment_refs(portal_token.get("shipment_refs", [])),
        expires_at,
        token,
    )

    existing = conn.execute(
        "SELECT token FROM portal_tokens WHERE token = ?",
        (token,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE portal_tokens
            SET customer_name = ?, email = ?, shipment_refs = ?, expires_at = ?
            WHERE token = ?
            """,
            params,
        )
    else:
        conn.execute(
            """
            INSERT INTO portal_tokens (token, customer_name, email, shipment_refs, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                token,
                customer_name,
                _normalize_text(portal_token.get("email")),
                _serialize_shipment_refs(portal_token.get("shipment_refs", [])),
                expires_at,
            ),
        )
    return token


def refresh_customer_invoice_statuses(conn):
    conn.execute(
        """
        UPDATE customer_invoices
        SET status = 'Overdue',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'Sent'
          AND due_date IS NOT NULL
          AND date(due_date) < date('now')
          AND paid_at IS NULL
        """
    )
    conn.execute(
        """
        UPDATE customer_invoices
        SET status = 'Sent',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'Overdue'
          AND paid_at IS NULL
          AND (due_date IS NULL OR date(due_date) >= date('now'))
        """
    )


def _seed_demo_customer_invoices(conn, demo_shipments):
    today = date.today()
    shipments_by_ref = {shipment["shipment_ref"]: shipment for shipment in demo_shipments}
    demo_rows = [
        {
            "shipment_ref": "TMS-DEMO-001",
            "amount": 3200.00,
            "currency": "USD",
            "exchange_rate": 1.0,
            "status": "Draft",
            "due_date": today + timedelta(days=14),
            "paid_at": None,
        },
        {
            "shipment_ref": "TMS-DEMO-002",
            "amount": 3861.00,
            "currency": "CAD",
            "exchange_rate": 1.35,
            "status": "Sent",
            "due_date": today + timedelta(days=10),
            "paid_at": None,
        },
        {
            "shipment_ref": "TMS-DEMO-003",
            "amount": 1968.80,
            "currency": "EUR",
            "exchange_rate": 0.92,
            "status": "Overdue",
            "due_date": today - timedelta(days=4),
            "paid_at": None,
        },
        {
            "shipment_ref": "TMS-DEMO-004",
            "amount": 2244.60,
            "currency": "GBP",
            "exchange_rate": 0.87,
            "status": "Paid",
            "due_date": today - timedelta(days=18),
            "paid_at": datetime.combine(today - timedelta(days=7), datetime.min.time()).isoformat(
                timespec="seconds"
            ),
        },
    ]

    for row in demo_rows:
        shipment = shipments_by_ref.get(row["shipment_ref"])
        if not shipment:
            continue

        conn.execute(
            """
            INSERT INTO customer_invoices
                (shipment_ref, customer_name, amount, currency, exchange_rate, status, due_date, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["shipment_ref"],
                shipment["shipper_name"],
                row["amount"],
                row["currency"],
                row["exchange_rate"],
                row["status"],
                row["due_date"].isoformat(),
                row["paid_at"],
            ),
        )


def preload_demo_data(conn=None):
    should_close = conn is None
    conn = conn or get_db()
    demo_shipments = _build_demo_shipments()

    try:
        conn.execute("DELETE FROM customer_invoices")
        conn.execute("DELETE FROM load_shipments")
        conn.execute("DELETE FROM loads")
        conn.execute("DELETE FROM freight_claims")
        conn.execute("DELETE FROM tender_responses")
        conn.execute("DELETE FROM tenders")
        conn.execute("DELETE FROM tracking_pings")
        conn.execute("DELETE FROM tracking_driver_tokens")
        conn.execute("DELETE FROM quotes")
        conn.execute("DELETE FROM intake_documents")
        conn.execute("DELETE FROM shipment_events")
        conn.execute("DELETE FROM shipments")
        conn.execute("DELETE FROM tms_carriers")
        conn.execute("DELETE FROM tms_lanes")
        conn.execute("DELETE FROM portal_tokens")

        carrier_ids = {}
        for carrier in DEMO_CARRIERS:
            carrier_ids[carrier["scac"]] = _upsert_carrier(conn, carrier)

        for lane in DEMO_LANES:
            _upsert_lane(conn, lane)

        for shipment in demo_shipments:
            existing = conn.execute(
                "SELECT id FROM shipments WHERE shipment_ref = ?",
                (shipment["shipment_ref"],),
            ).fetchone()

            shipment_params = (
                shipment["status"],
                shipment.get("customer_name") or shipment["shipper_name"],
                shipment["shipper_name"],
                shipment["shipper_address"],
                shipment["consignee_name"],
                shipment["consignee_address"],
                shipment["carrier_name"],
                carrier_ids[shipment["carrier_scac"]],
                shipment["origin_port"],
                shipment["destination_port"],
                shipment["mode"],
                shipment["etd"],
                shipment["eta"],
                shipment["cargo_description"],
                shipment["containers"],
                shipment["weight_kg"],
                shipment["volume_cbm"],
                shipment["freight_rate"],
                shipment["currency"],
                shipment["incoterm"],
                shipment["notes"],
                shipment["lane_code"],
            )

            if existing:
                conn.execute(
                    """
                    UPDATE shipments SET
                        status = ?, customer_name = ?, shipper_name = ?, shipper_address = ?, consignee_name = ?, consignee_address = ?,
                        carrier_name = ?, carrier_id = ?, origin_port = ?, destination_port = ?, mode = ?, etd = ?, eta = ?,
                        cargo_description = ?, containers = ?, weight_kg = ?, volume_cbm = ?, freight_rate = ?,
                        currency = ?, incoterm = ?, notes = ?, lane_code = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    shipment_params + (existing["id"],),
                )
                shipment_id = existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO shipments
                    (
                        shipment_ref, status, customer_name, shipper_name, shipper_address, consignee_name, consignee_address,
                        carrier_name, carrier_id, origin_port, destination_port, mode, etd, eta, cargo_description,
                        containers, weight_kg, volume_cbm, freight_rate, currency, incoterm, notes, lane_code
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (shipment["shipment_ref"],) + shipment_params,
                )
                shipment_id = cursor.lastrowid

            event_exists = conn.execute(
                """
                SELECT 1 FROM shipment_events
                WHERE shipment_id = ? AND event_type = 'Demo Ready'
                """,
                (shipment_id,),
            ).fetchone()
            if not event_exists:
                conn.execute(
                    """
                    INSERT INTO shipment_events (shipment_id, event_type, description, location)
                    VALUES (?, 'Demo Ready', ?, ?)
                    """,
                    (
                        shipment_id,
                        f"{shipment['shipment_ref']} loaded for sandbox walkthrough.",
                        shipment["origin_port"],
                    ),
                )

        backfill_shipment_co2(conn=conn)
        for portal_token in DEMO_PORTAL_TOKENS:
            _upsert_portal_token(conn, portal_token)

        _seed_demo_customer_invoices(conn, demo_shipments)
        refresh_customer_invoice_statuses(conn)
        _upsert_setting(conn, "updated_at", datetime.now().isoformat(timespec="seconds"))
        conn.commit()
    finally:
        if should_close:
            conn.close()


def get_setup_state():
    init_tms_db()
    conn = get_db()
    try:
        settings = _get_settings(conn)
        counts = {
            "shipments": conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
            "carriers": conn.execute("SELECT COUNT(*) FROM tms_carriers").fetchone()[0],
            "lanes": conn.execute("SELECT COUNT(*) FROM tms_lanes").fetchone()[0],
            "invoices": conn.execute("SELECT COUNT(*) FROM customer_invoices").fetchone()[0],
        }
        return {
            "settings": settings,
            "counts": counts,
            "setup_complete": settings.get("setup_complete") == "1",
            "demo_carriers": DEMO_CARRIERS,
            "demo_lanes": DEMO_LANES,
            "demo_shipments": _build_demo_shipments(),
        }
    finally:
        conn.close()


def save_setup(company_name, primary_color, logo_file=None):
    clean_name = (company_name or "").strip()
    if not clean_name:
        raise ValueError("Company name is required.")

    init_tms_db()
    conn = get_db()
    try:
        settings = _get_settings(conn)
        logo_data = _encode_logo(logo_file)

        _upsert_setting(conn, "company_name", clean_name)
        _upsert_setting(conn, "primary_color", _normalize_color(primary_color))
        _upsert_setting(conn, "setup_complete", "1")
        _upsert_setting(conn, "updated_at", datetime.now().isoformat(timespec="seconds"))

        if logo_data is not None:
            _upsert_setting(conn, "company_logo", logo_data)
        elif "company_logo" not in settings:
            _upsert_setting(conn, "company_logo", "")

        preload_demo_data(conn)
        conn.commit()
    finally:
        conn.close()

    return get_setup_state()


_EMAIL_SETTING_KEYS = (
    "smtp_host", "smtp_port", "smtp_user", "smtp_pass",
    "smtp_from", "smtp_from_name", "smtp_use_tls", "smtp_use_ssl",
    "imap_host", "imap_port", "imap_user", "imap_pass", "imap_ssl",
)
_EMAIL_SECRET_SETTING_KEYS = {"smtp_pass", "imap_pass"}
_ENCRYPTED_SETTING_KEYS = _EMAIL_SECRET_SETTING_KEYS | {"trade_api_key"}
_ENCRYPTED_SETTING_PREFIX = "enc:v1:"


def _encode_secure_setting(key, value):
    if key not in _ENCRYPTED_SETTING_KEYS:
        return value
    clean_value = str(value or "")
    if not clean_value:
        return ""
    if clean_value.startswith(_ENCRYPTED_SETTING_PREFIX):
        return clean_value
    from .tms_integrations import encrypt_key
    encrypted = encrypt_key(clean_value)
    return f"{_ENCRYPTED_SETTING_PREFIX}{encrypted}" if encrypted else ""


def _decode_secure_setting(key, value):
    if key not in _ENCRYPTED_SETTING_KEYS:
        return value or ""
    clean_value = str(value or "")
    if not clean_value:
        return ""
    if not clean_value.startswith(_ENCRYPTED_SETTING_PREFIX):
        return clean_value
    from .tms_integrations import decrypt_key
    return decrypt_key(clean_value[len(_ENCRYPTED_SETTING_PREFIX):])


def get_email_settings(*, include_secrets=False) -> dict:
    """Return current SMTP/IMAP settings from tms_settings."""
    init_tms_db()
    conn = get_db()
    try:
        settings = _get_settings(conn)
    finally:
        conn.close()
    result = {k: settings.get(k, DEFAULT_SETTINGS.get(k, "")) for k in _EMAIL_SETTING_KEYS}
    if not include_secrets:
        for key in _EMAIL_SECRET_SETTING_KEYS:
            result[f"{key}_configured"] = bool(result.get(key))
            result[key] = ""
    return result


def save_email_settings(data: dict) -> None:
    """Persist SMTP/IMAP settings. Only whitelisted keys are written."""
    init_tms_db()
    conn = get_db()
    try:
        existing_settings = _get_settings(conn)
        for key in _EMAIL_SETTING_KEYS:
            if key in data:
                val = str(data[key]).strip() if data[key] is not None else ""
                if key in _EMAIL_SECRET_SETTING_KEYS and not val:
                    clear_requested = str(data.get(f"clear_{key}", "")).strip().lower() in {"1", "true", "yes", "on"}
                    if clear_requested:
                        _upsert_setting(conn, key, "")
                    elif existing_settings.get(key):
                        continue
                    else:
                        _upsert_setting(conn, key, "")
                    continue
                if key in _EMAIL_SECRET_SETTING_KEYS:
                    val = _encode_secure_setting(key, val)
                _upsert_setting(conn, key, val)
        conn.commit()
    finally:
        conn.close()


def _hash_api_key_value(api_key_value):
    clean_api_key = _normalize_text(api_key_value)
    if not clean_api_key:
        return ""
    return hashlib.sha256(clean_api_key.encode("utf-8")).hexdigest()


def _looks_like_api_key_hash(value):
    return bool(_API_KEY_HASH_HEX_RE.fullmatch(str(value or "").strip().lower()))


def _api_key_hint(api_key_value):
    clean_api_key = _normalize_text(api_key_value)
    if len(clean_api_key) <= 12:
        return clean_api_key
    return f"{clean_api_key[:8]}...{clean_api_key[-4:]}"


def _api_key_row_to_dict(row):
    if not row:
        return None

    api_key = dict(row)
    api_key["permissions"] = _deserialize_permissions(api_key.get("permissions"))
    return api_key


def list_api_keys():
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT key, key_hint, customer_name, permissions, created_at, last_used
            FROM api_keys
            ORDER BY datetime(created_at) DESC, key ASC
            """
        ).fetchall()
        return [_api_key_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def create_api_key(customer_name, permissions):
    init_tms_db()
    clean_customer_name = _normalize_text(customer_name)
    clean_permissions = _dedupe_permissions(permissions)
    if not clean_customer_name:
        raise ValueError("Customer name is required.")
    if not clean_permissions:
        raise ValueError("Select at least one permission.")

    conn = get_db()
    try:
        api_key_value = ""
        while not api_key_value:
            candidate = f"tms_sbx_{secrets.token_urlsafe(24)}"
            existing = conn.execute(
                "SELECT key FROM api_keys WHERE key = ?",
                (_hash_api_key_value(candidate),),
            ).fetchone()
            if not existing:
                api_key_value = candidate

        conn.execute(
            """
            INSERT INTO api_keys (key, key_hint, customer_name, permissions)
            VALUES (?, ?, ?, ?)
            """,
            (
                _hash_api_key_value(api_key_value),
                _api_key_hint(api_key_value),
                clean_customer_name,
                _serialize_permissions(clean_permissions),
            ),
        )
        conn.commit()
        created = get_api_key(api_key_value)
        if created:
            created["key"] = api_key_value
            created["key_hint"] = _api_key_hint(api_key_value)
        return created
    finally:
        conn.close()


def get_api_key(api_key_value):
    init_tms_db()
    clean_api_key = _normalize_text(api_key_value)
    if not clean_api_key:
        return None

    conn = get_db()
    try:
        hashed_key = _hash_api_key_value(clean_api_key)
        row = conn.execute(
            """
            SELECT key, key_hint, customer_name, permissions, created_at, last_used
            FROM api_keys
            WHERE key = ?
            """,
            (hashed_key,),
        ).fetchone()
        if not row and _looks_like_api_key_hash(clean_api_key):
            row = conn.execute(
                """
                SELECT key, key_hint, customer_name, permissions, created_at, last_used
                FROM api_keys
                WHERE key = ?
                """,
                (clean_api_key.lower(),),
            ).fetchone()
        return _api_key_row_to_dict(row)
    finally:
        conn.close()


def revoke_api_key(api_key_value):
    init_tms_db()
    clean_api_key = _normalize_text(api_key_value)
    if not clean_api_key:
        raise ValueError("API key is required.")

    conn = get_db()
    try:
        hashed_key = _hash_api_key_value(clean_api_key)
        existing = conn.execute(
            """
            SELECT key, key_hint, customer_name, permissions, created_at, last_used
            FROM api_keys
            WHERE key IN (?, ?)
            ORDER BY CASE WHEN key = ? THEN 0 ELSE 1 END
            """,
            (clean_api_key.lower(), hashed_key, clean_api_key.lower()),
        ).fetchone()
        if not existing:
            raise ValueError("API key not found.")
        conn.execute("DELETE FROM api_keys WHERE key = ?", (existing["key"],))
        conn.commit()
        return _api_key_row_to_dict(existing)
    finally:
        conn.close()


def touch_api_key_last_used(api_key_value):
    init_tms_db()
    clean_api_key = _normalize_text(api_key_value)
    if not clean_api_key:
        return

    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE api_keys
            SET last_used = CURRENT_TIMESTAMP
            WHERE key = ?
            """,
            (_hash_api_key_value(clean_api_key),),
        )
        conn.commit()
    finally:
        conn.close()


def list_customer_shipments(customer_name):
    init_tms_db()
    clean_customer_name = _normalize_text(customer_name)
    if not clean_customer_name:
        return []

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM shipments
            WHERE LOWER(COALESCE(NULLIF(TRIM(customer_name), ''), TRIM(shipper_name), '')) = LOWER(?)
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (clean_customer_name,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_customer_shipment_snapshot(customer_name, ref):
    clean_customer_name = _normalize_text(customer_name)
    snapshot = get_shipment_snapshot(ref)
    if not snapshot or not clean_customer_name:
        return None

    shipment_customer_name = _normalize_text(
        snapshot["shipment"].get("customer_name") or snapshot["shipment"].get("shipper_name")
    )
    if shipment_customer_name.lower() != clean_customer_name.lower():
        return None
    return snapshot


def create_customer_shipment(customer_name, payload):
    init_tms_db()
    clean_customer_name = _normalize_text(customer_name)
    if not clean_customer_name:
        raise ValueError("Customer name is required.")

    ref = generate_ref()
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO shipments
                (
                    shipment_ref, status, customer_name, shipper_name, shipper_address, consignee_name, consignee_address,
                    carrier_name, origin_port, destination_port, mode, etd, eta, cargo_description, containers,
                    weight_kg, volume_cbm, freight_rate, currency, incoterm, notes
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref,
                _normalize_text(payload.get("status")) or "Draft",
                clean_customer_name,
                _normalize_text(payload.get("shipper_name")) or clean_customer_name,
                _normalize_text(payload.get("shipper_address")),
                _normalize_text(payload.get("consignee_name")),
                _normalize_text(payload.get("consignee_address")),
                _normalize_text(payload.get("carrier_name")),
                _normalize_text(payload.get("origin_port")),
                _normalize_text(payload.get("destination_port")),
                _normalize_mode(payload.get("mode")),
                _normalize_text(payload.get("etd")),
                _normalize_text(payload.get("eta")),
                _normalize_text(payload.get("cargo_description")),
                _normalize_text(payload.get("containers")),
                _parse_optional_number(payload.get("weight_kg"), "Weight (kg)"),
                _parse_optional_number(payload.get("volume_cbm"), "Volume (cbm)"),
                _parse_optional_number(payload.get("freight_rate"), "Freight rate"),
                _normalize_currency(payload.get("currency")),
                _normalize_text(payload.get("incoterm")) or "FOB",
                _normalize_text(payload.get("notes")),
            ),
        )
        refresh_shipment_carbon(conn, shipment_id=cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO shipment_events (shipment_id, event_type, description, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (
                cursor.lastrowid,
                "Created",
                f"Shipment {ref} created via API",
                "api",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_customer_shipment_snapshot(clean_customer_name, ref)


def lookup_api_rate(origin, destination, mode="", containers="", reference_date=None):
    init_tms_db()
    clean_origin = _normalize_lane_value(origin)
    clean_destination = _normalize_lane_value(destination)
    clean_mode = _normalize_mode(mode)
    clean_containers = _normalize_text(containers)
    if not clean_origin or not clean_destination:
        raise ValueError("Origin and destination are required.")

    conn = get_db()
    try:
        lane = conn.execute(
            """
            SELECT *
            FROM tms_lanes
            WHERE LOWER(origin_name) = LOWER(?)
              AND LOWER(destination_name) = LOWER(?)
            ORDER BY active DESC, datetime(updated_at) DESC, id DESC
            LIMIT 1
            """,
            (clean_origin, clean_destination),
        ).fetchone()
        resolved_mode = clean_mode or (lane["mode"] if lane else "")
        contract_rate = None
        if resolved_mode:
            contract_rate = find_best_contract_rate(
                origin=clean_origin,
                destination=clean_destination,
                mode=resolved_mode,
                containers=clean_containers,
                reference_date=reference_date,
                conn=conn,
            )

        history_params = [clean_origin, clean_destination]
        mode_sql = ""
        if clean_mode:
            mode_sql = "AND LOWER(COALESCE(mode, '')) = LOWER(?)"
            history_params.append(clean_mode)

        history_row = conn.execute(
            f"""
            SELECT
                currency,
                COUNT(*) AS sample_size,
                ROUND(MIN(freight_rate), 2) AS rate_low,
                ROUND(AVG(freight_rate), 2) AS rate_average,
                ROUND(MAX(freight_rate), 2) AS rate_high
            FROM shipments
            WHERE LOWER(COALESCE(origin_port, '')) = LOWER(?)
              AND LOWER(COALESCE(destination_port, '')) = LOWER(?)
              AND freight_rate IS NOT NULL
              AND freight_rate > 0
              AND status NOT IN ('Draft', 'Cancelled')
              {mode_sql}
            GROUP BY currency
            ORDER BY sample_size DESC, rate_average ASC, currency ASC
            LIMIT 1
            """,
            history_params,
        ).fetchone()

        recent_refs = [
            row["shipment_ref"]
            for row in conn.execute(
                f"""
                SELECT shipment_ref
                FROM shipments
                WHERE LOWER(COALESCE(origin_port, '')) = LOWER(?)
                  AND LOWER(COALESCE(destination_port, '')) = LOWER(?)
                  AND freight_rate IS NOT NULL
                  AND freight_rate > 0
                  AND status NOT IN ('Draft', 'Cancelled')
                  {mode_sql}
                ORDER BY date(COALESCE(etd, created_at)) DESC, id DESC
                LIMIT 3
                """,
                history_params,
            ).fetchall()
        ]

        if not contract_rate and not history_row:
            return None

        response = {
            "origin": clean_origin,
            "destination": clean_destination,
            "mode": resolved_mode,
            "containers": clean_containers,
            "source": "contract_rate" if contract_rate else "shipment_history",
            "lane": dict(lane) if lane else None,
            "history": None,
            "contract_rate": None,
            "recent_shipment_refs": recent_refs,
        }

        if history_row:
            response["history"] = {
                "currency": history_row["currency"],
                "sample_size": int(history_row["sample_size"] or 0),
                "rate_low": float(history_row["rate_low"] or 0),
                "rate_average": float(history_row["rate_average"] or 0),
                "rate_high": float(history_row["rate_high"] or 0),
            }

        if contract_rate:
            response["contract_rate"] = {
                "currency": contract_rate["currency"],
                "matched_rate": contract_rate["matched_rate"],
                "matched_rate_label": contract_rate["matched_rate_label"],
                "valid_from": contract_rate["valid_from"],
                "valid_to": contract_rate["valid_to"],
                "status_label": contract_rate["status_label"],
            }

        return response
    finally:
        conn.close()


def save_portal_token(token, customer_name, email="", shipment_refs=None, expires_at=None):
    init_tms_db()
    conn = get_db()
    try:
        normalized_token = _upsert_portal_token(
            conn,
            {
                "token": token,
                "customer_name": customer_name,
                "email": email,
                "shipment_refs": shipment_refs or [],
                "expires_at": expires_at,
            },
        )
        conn.commit()
        return normalized_token
    finally:
        conn.close()


def get_portal_token(token):
    init_tms_db()
    normalized_token = _normalize_portal_token(token)
    if not normalized_token:
        return None

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM portal_tokens WHERE upper(token) = ?",
            (normalized_token,),
        ).fetchone()
        portal_token = _portal_row_to_dict(row)
        return portal_token if _portal_token_is_active(portal_token) else None
    finally:
        conn.close()


def resolve_portal_login(access_code):
    init_tms_db()
    normalized_code = _normalize_portal_token(access_code)
    if not normalized_code:
        return None

    conn = get_db()
    try:
        exact_match = conn.execute(
            "SELECT * FROM portal_tokens WHERE upper(token) = ?",
            (normalized_code,),
        ).fetchone()
        if exact_match:
            portal_token = _portal_row_to_dict(exact_match)
            return portal_token if _portal_token_is_active(portal_token) else None

        matches = []
        for row in conn.execute("SELECT * FROM portal_tokens ORDER BY created_at DESC").fetchall():
            portal_token = _portal_row_to_dict(row)
            if portal_token["pin"] == normalized_code and _portal_token_is_active(portal_token):
                matches.append(portal_token)

        return matches[0] if len(matches) == 1 else None
    finally:
        conn.close()


def _parse_optional_number(value, label):
    raw = _normalize_text(value)
    if not raw:
        return 0

    try:
        parsed = round(float(raw), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc

    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed


def _parse_nullable_number(value, label):
    raw = _normalize_text(value)
    if not raw:
        return None

    try:
        parsed = round(float(raw), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc

    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed


def _parse_nullable_iso_date(value, label):
    raw = _normalize_text(value)
    if not raw:
        return None

    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid date.") from exc


def _parse_tracking_datetime(value):
    raw = (value or "").strip() if isinstance(value, str) else ""
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        parsed = None

    if parsed is None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    return parsed


def _format_tracking_datetime(value):
    parsed = _parse_tracking_datetime(value)
    if not parsed:
        return "-"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    if parsed.time() == datetime.min.time():
        return parsed.strftime("%b %d, %Y")
    return parsed.strftime("%b %d, %Y %H:%M UTC")


def _build_eta_summary(status, eta_value):
    if status == "Delivered":
        return "Delivered"
    if status == "Cancelled":
        return "Tracking closed"

    eta_dt = _parse_tracking_datetime(eta_value)
    if not eta_dt:
        return "ETA pending"

    days_out = (eta_dt.date() - datetime.utcnow().date()).days
    if days_out > 1:
        return f"ETA in {days_out} days"
    if days_out == 1:
        return "ETA tomorrow"
    if days_out == 0:
        return "ETA today"
    if days_out == -1:
        return "ETA was yesterday"
    return f"ETA was {abs(days_out)} days ago"


def _calculate_progress(status, etd_value, eta_value):
    base_progress = STATUS_PROGRESS.get(status, 18)
    if status in {"Delivered", "Cancelled"}:
        return base_progress

    etd_dt = _parse_tracking_datetime(etd_value)
    eta_dt = _parse_tracking_datetime(eta_value)
    if not etd_dt or not eta_dt or eta_dt <= etd_dt:
        return base_progress

    now = datetime.utcnow()
    if etd_dt.tzinfo is not None:
        now = datetime.now(timezone.utc)

    elapsed = (now - etd_dt).total_seconds()
    duration = (eta_dt - etd_dt).total_seconds()
    if duration <= 0:
        return base_progress

    time_progress = int(max(12, min(96, round((elapsed / duration) * 100))))
    return max(base_progress, time_progress)


def _normalize_location_key(value):
    return re.sub(r"\s+", " ", _normalize_text(value)).lower()


def _build_geocode_source_url(location):
    clean_location = _normalize_text(location)
    if not clean_location:
        return ""
    query = urlencode(
        {
            "q": clean_location,
            "format": "jsonv2",
            "limit": 1,
        }
    )
    return f"{NOMINATIM_SEARCH_URL}?{query}"


def _upsert_location_geocode(conn, normalized_location, record):
    conn.execute(
        """
        INSERT INTO location_geocodes (location_name, lat, lng, display_name, source_url, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(location_name) DO UPDATE SET
            lat = excluded.lat,
            lng = excluded.lng,
            display_name = excluded.display_name,
            source_url = excluded.source_url,
            updated_at = excluded.updated_at
        """,
        (
            normalized_location,
            record["lat"],
            record["lng"],
            record["display_name"],
            record["source_url"],
        ),
    )


def _resolve_location_geocode(location, conn=None):
    clean_location = _normalize_text(location)
    normalized_location = _normalize_location_key(clean_location)
    if not normalized_location:
        return None

    if normalized_location in KNOWN_LOCATION_COORDINATES:
        lat, lng = KNOWN_LOCATION_COORDINATES[normalized_location]
        _LOCATION_COORD_CACHE[normalized_location] = (lat, lng)
        return {
            "lat": round(float(lat), 6),
            "lng": round(float(lng), 6),
            "display_name": clean_location or normalized_location.title(),
            "source_url": _build_geocode_source_url(clean_location or normalized_location),
        }

    if normalized_location in _LOCATION_COORD_CACHE:
        coords = _LOCATION_COORD_CACHE[normalized_location]
        if not coords:
            return None
        source_url = _build_geocode_source_url(clean_location or normalized_location)
        display_name = clean_location or normalized_location.title()
        db_conn = None
        should_close = conn is None
        if should_close:
            init_tms_db()
            db_conn = get_db()
        else:
            db_conn = conn
        try:
            cached_row = db_conn.execute(
                """
                SELECT display_name, source_url
                FROM location_geocodes
                WHERE location_name = ?
                """,
                (normalized_location,),
            ).fetchone()
        finally:
            if should_close:
                db_conn.close()
        if cached_row:
            display_name = cached_row["display_name"] or display_name
            source_url = cached_row["source_url"] or source_url
        return {
            "lat": round(float(coords[0]), 6),
            "lng": round(float(coords[1]), 6),
            "display_name": display_name,
            "source_url": source_url,
        }

    should_close = conn is None
    db_conn = conn or get_db()
    cached_row = None
    try:
        cached_row = db_conn.execute(
            """
            SELECT lat, lng, display_name, source_url
            FROM location_geocodes
            WHERE location_name = ?
            """,
            (normalized_location,),
        ).fetchone()
        if cached_row:
            coords = (round(float(cached_row["lat"]), 6), round(float(cached_row["lng"]), 6))
            _LOCATION_COORD_CACHE[normalized_location] = coords
            return {
                "lat": coords[0],
                "lng": coords[1],
                "display_name": cached_row["display_name"] or clean_location or normalized_location.title(),
                "source_url": cached_row["source_url"] or _build_geocode_source_url(clean_location or normalized_location),
            }

        city_key = normalized_location.split(",")[0]
        for known_location, coords in KNOWN_LOCATION_COORDINATES.items():
            if known_location.split(",")[0] == city_key:
                _LOCATION_COORD_CACHE[normalized_location] = coords
                return {
                    "lat": round(float(coords[0]), 6),
                    "lng": round(float(coords[1]), 6),
                    "display_name": clean_location or normalized_location.title(),
                    "source_url": _build_geocode_source_url(clean_location or normalized_location),
                }

        record = None
        try:
            source_url = _build_geocode_source_url(clean_location)
            request = Request(
                source_url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": GEOCODE_USER_AGENT,
                },
            )
            with urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload:
                record = {
                    "lat": round(float(payload[0]["lat"]), 6),
                    "lng": round(float(payload[0]["lon"]), 6),
                    "display_name": payload[0].get("display_name", clean_location),
                    "source_url": source_url,
                }
                _upsert_location_geocode(db_conn, normalized_location, record)
                if should_close:
                    db_conn.commit()
        except Exception:
            record = None

        _LOCATION_COORD_CACHE[normalized_location] = (
            (record["lat"], record["lng"]) if record else None
        )
        return record
    finally:
        if should_close:
            db_conn.close()


def _lookup_location_coordinates(location, conn=None):
    record = _resolve_location_geocode(location, conn=conn)
    if not record:
        return None
    return (record["lat"], record["lng"])


def _distance_km(coord_a, coord_b):
    if not coord_a or not coord_b:
        return None

    lat1, lon1 = coord_a
    lat2, lon2 = coord_b
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def calculate_shipment_co2_details(shipment, conn=None):
    shipment = dict(shipment or {})
    mode_key = normalize_carbon_mode(shipment.get("mode"))
    mode_label = CARBON_MODE_LABELS.get(mode_key)
    emission_factor = CARBON_EMISSION_FACTORS.get(mode_key)
    origin_record = _resolve_location_geocode(shipment.get("origin_port"), conn=conn)
    destination_record = _resolve_location_geocode(shipment.get("destination_port"), conn=conn)
    origin_coords = (
        (origin_record["lat"], origin_record["lng"]) if origin_record else None
    )
    destination_coords = (
        (destination_record["lat"], destination_record["lng"]) if destination_record else None
    )
    distance_km = _distance_km(origin_coords, destination_coords)
    weight_kg = float(shipment.get("weight_kg") or 0)
    co2_kg = None
    calculation_status = "calculated"

    if weight_kg <= 0:
        calculation_status = "missing_weight"
    elif not emission_factor:
        calculation_status = "unsupported_mode"
    elif distance_km is None:
        calculation_status = "unresolved_route"
    else:
        co2_kg = round(distance_km * (weight_kg / 1000.0) * emission_factor, 2)

    freight_rate = float(shipment.get("freight_rate") or 0)
    currency = _normalize_currency(shipment.get("currency"))
    carbon_intensity_kg_per_usd = None
    if co2_kg is not None and freight_rate > 0 and currency == "USD":
        carbon_intensity_kg_per_usd = round(co2_kg / freight_rate, 4)

    return {
        "co2_kg": co2_kg,
        "distance_km": round(distance_km, 2) if distance_km is not None else None,
        "weight_tonnes": round(weight_kg / 1000.0, 3) if weight_kg > 0 else None,
        "mode_key": mode_key,
        "mode_label": mode_label,
        "emission_factor_kg_per_tonne_km": emission_factor,
        "framework_label": CARBON_FRAMEWORK_LABEL,
        "framework_note": CARBON_FRAMEWORK_NOTE,
        "carbon_intensity_kg_per_usd": carbon_intensity_kg_per_usd,
        "calculation_status": calculation_status,
        "origin_source_url": origin_record["source_url"] if origin_record else "",
        "destination_source_url": destination_record["source_url"] if destination_record else "",
    }


def refresh_shipment_carbon(conn, shipment_id=None, shipment_ref=None):
    if shipment_id is None and not shipment_ref:
        raise ValueError("Shipment id or reference is required to refresh carbon data.")

    if shipment_id is not None:
        row = conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM shipments WHERE shipment_ref = ?", (shipment_ref,)).fetchone()
    if not row:
        return None

    details = calculate_shipment_co2_details(row, conn=conn)
    conn.execute(
        "UPDATE shipments SET co2_kg = ? WHERE id = ?",
        (details["co2_kg"], row["id"]),
    )
    return details


def backfill_shipment_co2(conn=None, shipment_refs=None, only_missing=False):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()

    refs = _dedupe_shipment_refs(shipment_refs or [])
    where_clauses = []
    params = []
    if refs:
        placeholders = ",".join("?" for _ in refs)
        where_clauses.append(f"shipment_ref IN ({placeholders})")
        params.extend(refs)
    if only_missing:
        where_clauses.append("co2_kg IS NULL")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    try:
        rows = conn.execute(f"SELECT id, shipment_ref FROM shipments {where_sql}", params).fetchall()
        for row in rows:
            refresh_shipment_carbon(conn, shipment_id=row["id"])
        if should_close:
            conn.commit()
        return len(rows)
    finally:
        if should_close:
            conn.close()


def _unique_locations(locations):
    ordered_locations = []
    seen = set()
    for location in locations:
        clean_location = _normalize_text(location)
        normalized_location = _normalize_location_key(clean_location)
        if not normalized_location or normalized_location in seen:
            continue
        ordered_locations.append(clean_location)
        seen.add(normalized_location)
    return ordered_locations


def _nearest_neighbor_order(locations, preferred_start=None, anchor=None):
    ordered_locations = _unique_locations(locations)
    if not ordered_locations:
        return []

    coords_by_location = {
        location: _lookup_location_coordinates(location)
        for location in ordered_locations
    }
    preferred_key = _normalize_location_key(preferred_start)
    anchor_coords = _lookup_location_coordinates(anchor)

    def _start_key(location):
        location_key = _normalize_location_key(location)
        location_coords = coords_by_location.get(location)
        anchor_distance = _distance_km(anchor_coords, location_coords)
        return (
            0 if preferred_key and location_key == preferred_key else 1,
            1 if location_coords is None else 0,
            anchor_distance if anchor_distance is not None else float("inf"),
            location_key,
        )

    current_location = min(ordered_locations, key=_start_key)
    remaining_locations = [
        location
        for location in ordered_locations
        if _normalize_location_key(location) != _normalize_location_key(current_location)
    ]
    route = [current_location]

    while remaining_locations:
        current_coords = coords_by_location.get(current_location)

        def _next_key(location):
            location_coords = coords_by_location.get(location)
            step_distance = _distance_km(current_coords, location_coords)
            return (
                1 if location_coords is None else 0,
                step_distance if step_distance is not None else float("inf"),
                _normalize_location_key(location),
            )

        current_location = min(remaining_locations, key=_next_key)
        route.append(current_location)
        remaining_locations = [
            location
            for location in remaining_locations
            if _normalize_location_key(location) != _normalize_location_key(current_location)
        ]

    return route


def _compress_location_path(locations):
    path = []
    for location in locations:
        clean_location = _normalize_text(location)
        if not clean_location:
            continue
        if path and _normalize_location_key(path[-1]) == _normalize_location_key(clean_location):
            continue
        path.append(clean_location)
    return path


def _build_load_route_plan(shipments):
    shipment_rows = [dict(shipment) for shipment in shipments]
    if not shipment_rows:
        return {
            "origin": "",
            "destination": "",
            "path": [],
            "stops": [],
            "stop_cards": [],
            "shipments": [],
        }

    pickup_labels = {}
    delivery_labels = {}
    pickup_counts = Counter()
    delivery_counts = Counter()

    for shipment in shipment_rows:
        origin = _normalize_text(shipment.get("origin_port"))
        destination = _normalize_text(shipment.get("destination_port"))
        if origin:
            origin_key = _normalize_location_key(origin)
            pickup_labels.setdefault(origin_key, origin)
            pickup_counts[origin_key] += 1
        if destination:
            destination_key = _normalize_location_key(destination)
            delivery_labels.setdefault(destination_key, destination)
            delivery_counts[destination_key] += 1

    primary_origin = ""
    if pickup_counts:
        primary_origin_key = min(
            pickup_counts,
            key=lambda item: (-pickup_counts[item], item),
        )
        primary_origin = pickup_labels[primary_origin_key]

    ordered_pickups = _nearest_neighbor_order(
        list(pickup_labels.values()),
        preferred_start=primary_origin,
    )
    delivery_anchor = ordered_pickups[-1] if ordered_pickups else ""
    ordered_deliveries = _nearest_neighbor_order(
        list(delivery_labels.values()),
        anchor=delivery_anchor,
    )

    route_path = _compress_location_path(ordered_pickups + ordered_deliveries)
    route_stops = route_path[1:-1] if len(route_path) > 2 else []
    pickup_order = {
        _normalize_location_key(location): index
        for index, location in enumerate(ordered_pickups)
    }
    delivery_order = {
        _normalize_location_key(location): index
        for index, location in enumerate(ordered_deliveries)
    }
    delivery_offset = len(ordered_pickups)

    manifest_rows = sorted(
        shipment_rows,
        key=lambda shipment: (
            pickup_order.get(_normalize_location_key(shipment.get("origin_port")), 999),
            delivery_order.get(_normalize_location_key(shipment.get("destination_port")), 999),
            _normalize_text(shipment.get("etd")),
            _normalize_text(shipment.get("eta")),
            shipment.get("shipment_ref", ""),
        ),
    )

    for index, shipment in enumerate(manifest_rows, start=1):
        origin_key = _normalize_location_key(shipment.get("origin_port"))
        destination_key = _normalize_location_key(shipment.get("destination_port"))
        shipment["manifest_sequence"] = index
        shipment["pickup_stop"] = pickup_order.get(origin_key, 0) + 1 if origin_key in pickup_order else None
        shipment["delivery_stop"] = (
            delivery_offset + delivery_order.get(destination_key, 0) + 1
            if destination_key in delivery_order
            else None
        )
        shipment["route_leg_label"] = " -> ".join(
            [
                part
                for part in [
                    _normalize_text(shipment.get("origin_port")),
                    _normalize_text(shipment.get("destination_port")),
                ]
                if part
            ]
        ) or "Route pending"

    stop_cards = []
    for index, location in enumerate(route_path):
        if len(route_path) == 1:
            role = "Origin / Destination"
        elif index == 0:
            role = "Origin"
        elif index == len(route_path) - 1:
            role = "Destination"
        else:
            role = f"Stop {index}"
        stop_cards.append(
            {
                "sequence": index + 1,
                "role": role,
                "location": location,
            }
        )

    return {
        "origin": route_path[0] if route_path else "",
        "destination": route_path[-1] if route_path else "",
        "path": route_path,
        "stops": route_stops,
        "stop_cards": stop_cards,
        "shipments": manifest_rows,
    }


def _summarize_load_route(route_plan):
    path = route_plan.get("path", [])
    if not path:
        return "Route pending"
    if len(path) == 1:
        return path[0]
    if len(path) == 2:
        return f"{path[0]} -> {path[1]}"
    stop_count = len(path) - 2
    stop_label = "stop" if stop_count == 1 else "stops"
    return f"{path[0]} -> {stop_count} {stop_label} -> {path[-1]}"


def _build_load_utilization(total_weight, total_cbm):
    total_weight = round(float(total_weight or 0), 2)
    total_cbm = round(float(total_cbm or 0), 2)
    weight_percent = round((total_weight / DEFAULT_LOAD_CAPACITY_KG) * 100, 1)
    cube_percent = round((total_cbm / DEFAULT_LOAD_CAPACITY_CBM) * 100, 1)
    return {
        "total_weight": total_weight,
        "total_cbm": total_cbm,
        "weight_capacity": DEFAULT_LOAD_CAPACITY_KG,
        "cube_capacity": DEFAULT_LOAD_CAPACITY_CBM,
        "weight_percent": weight_percent,
        "cube_percent": cube_percent,
        "overall_percent": round(max(weight_percent, cube_percent), 1),
        "is_over_capacity": weight_percent > 100 or cube_percent > 100,
    }


def _fetch_load_shipments(conn, load_id):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT s.*
            FROM load_shipments ls
            JOIN shipments s ON s.shipment_ref = ls.shipment_ref
            WHERE ls.load_id = ?
            """,
            (load_id,),
        ).fetchall()
    ]


def _sync_load_totals(conn, load_id, shipments=None):
    shipment_rows = shipments if shipments is not None else _fetch_load_shipments(conn, load_id)
    total_weight = round(sum(float(shipment.get("weight_kg") or 0) for shipment in shipment_rows), 2)
    total_cbm = round(sum(float(shipment.get("volume_cbm") or 0) for shipment in shipment_rows), 2)
    conn.execute(
        """
        UPDATE loads
        SET total_weight = ?, total_cbm = ?
        WHERE id = ?
        """,
        (total_weight, total_cbm, load_id),
    )
    return total_weight, total_cbm


def _build_load_record(conn, load_row, shipments=None):
    load = dict(load_row)
    shipment_rows = shipments if shipments is not None else _fetch_load_shipments(conn, load["id"])
    total_weight, total_cbm = _sync_load_totals(conn, load["id"], shipments=shipment_rows)
    route_plan = _build_load_route_plan(shipment_rows)
    load["total_weight"] = total_weight
    load["total_cbm"] = total_cbm
    load["shipment_count"] = len(shipment_rows)
    load["route"] = route_plan
    load["route_summary"] = _summarize_load_route(route_plan)
    load["utilization"] = _build_load_utilization(total_weight, total_cbm)
    return load


def _validate_load_status(status):
    clean_status = _normalize_text(status) or LOAD_STATUSES[0]
    if clean_status not in LOAD_STATUSES:
        raise ValueError("Load status is invalid.")
    return clean_status


def _normalize_tracking_timestamp(value, default_now=False):
    parsed = value if isinstance(value, datetime) else _parse_tracking_datetime(value)
    if not parsed:
        if not default_now:
            raise ValueError("Timestamp is required.")
        parsed = datetime.utcnow()
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _parse_tracking_coordinate(value, label, minimum, maximum):
    raw = _normalize_text("" if value is None else str(value))
    if not raw:
        raise ValueError(f"{label} is required.")
    try:
        parsed = round(float(raw), 6)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return parsed


def _parse_tracking_speed(value):
    raw = _normalize_text("" if value is None else str(value))
    if not raw:
        return None
    try:
        parsed = round(float(raw), 2)
    except ValueError as exc:
        raise ValueError("Speed must be a valid number.") from exc
    if parsed < 0:
        raise ValueError("Speed cannot be negative.")
    return parsed


def _parse_optional_integer(value, label):
    raw = _normalize_text("" if value is None else str(value))
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError(f"{label} must be a whole number.")
    return int(raw)


def _serialize_tracking_ping(row):
    if not row:
        return None
    ping = dict(row)
    ping["lat"] = round(float(ping["lat"]), 6)
    ping["lng"] = round(float(ping["lng"]), 6)
    ping["speed"] = round(float(ping["speed"]), 2) if ping.get("speed") is not None else None
    ping["timestamp_display"] = _format_tracking_datetime(ping.get("timestamp"))
    return ping


def list_tracking_pings(shipment_ref, conn=None):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        return []

    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, shipment_ref, lat, lng, speed, timestamp
            FROM tracking_pings
            WHERE shipment_ref = ?
            ORDER BY datetime(timestamp) ASC, id ASC
            """,
            (clean_ref,),
        ).fetchall()
        return [_serialize_tracking_ping(row) for row in rows]
    finally:
        if should_close:
            conn.close()


def get_or_create_tracking_driver_token(shipment_ref, carrier_id=None):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        raise ValueError("Shipment reference is required.")

    init_tms_db()
    parsed_carrier_id = _parse_optional_integer(carrier_id, "Carrier ID")
    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT shipment_ref, carrier_id FROM shipments WHERE shipment_ref = ?",
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise LookupError("Shipment not found.")

        existing = conn.execute(
            "SELECT token, carrier_id FROM tracking_driver_tokens WHERE shipment_ref = ?",
            (clean_ref,),
        ).fetchone()
        if existing:
            if parsed_carrier_id and not existing["carrier_id"]:
                conn.execute(
                    """
                    UPDATE tracking_driver_tokens
                    SET carrier_id = ?
                    WHERE shipment_ref = ?
                    """,
                    (parsed_carrier_id, clean_ref),
                )
                conn.commit()
            return existing["token"]

        assigned_carrier_id = shipment["carrier_id"] or parsed_carrier_id
        while True:
            token = secrets.token_urlsafe(18)
            try:
                conn.execute(
                    """
                    INSERT INTO tracking_driver_tokens (token, shipment_ref, carrier_id)
                    VALUES (?, ?, ?)
                    """,
                    (token, clean_ref, assigned_carrier_id),
                )
                conn.commit()
                return token
            except sqlite3.IntegrityError:
                continue
    finally:
        conn.close()


def get_driver_tracking_context(token):
    clean_token = _normalize_text(token)
    if not clean_token:
        return None

    init_tms_db()
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT
                t.token,
                t.shipment_ref,
                COALESCE(t.carrier_id, s.carrier_id) AS carrier_id,
                t.created_at,
                t.last_used_at,
                s.id AS shipment_id,
                s.status,
                s.carrier_name,
                s.origin_port,
                s.destination_port,
                s.etd,
                s.eta
            FROM tracking_driver_tokens t
            JOIN shipments s ON s.shipment_ref = t.shipment_ref
            WHERE t.token = ?
            """,
            (clean_token,),
        ).fetchone()
        if not row:
            return None

        shipment = dict(row)
        latest_ping = conn.execute(
            """
            SELECT id, shipment_ref, lat, lng, speed, timestamp
            FROM tracking_pings
            WHERE shipment_ref = ?
            ORDER BY datetime(timestamp) DESC, id DESC
            LIMIT 1
            """,
            (shipment["shipment_ref"],),
        ).fetchone()
        return {
            "token": clean_token,
            "shipment": shipment,
            "latest_ping": _serialize_tracking_ping(latest_ping),
            "settings": _get_settings(conn),
        }
    finally:
        conn.close()


def touch_tracking_driver_token(token):
    clean_token = _normalize_text(token)
    if not clean_token:
        return

    init_tms_db()
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE tracking_driver_tokens
            SET last_used_at = CURRENT_TIMESTAMP
            WHERE token = ?
            """,
            (clean_token,),
        )
        conn.commit()
    finally:
        conn.close()


def save_tracking_ping(carrier_id, shipment_ref, lat, lng, speed=None, timestamp=None):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        raise ValueError("Shipment reference is required.")

    parsed_carrier_id = _parse_optional_integer(carrier_id, "Carrier ID")
    latitude = _parse_tracking_coordinate(lat, "Latitude", -90, 90)
    longitude = _parse_tracking_coordinate(lng, "Longitude", -180, 180)
    speed_value = _parse_tracking_speed(speed)
    timestamp_value = _normalize_tracking_timestamp(timestamp, default_now=True)

    init_tms_db()
    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT id, shipment_ref, carrier_id FROM shipments WHERE shipment_ref = ?",
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise LookupError("Shipment not found.")
        if parsed_carrier_id and shipment["carrier_id"] and parsed_carrier_id != shipment["carrier_id"]:
            raise ValueError("Carrier ID does not match this shipment.")

        had_existing_pings = conn.execute(
            "SELECT 1 FROM tracking_pings WHERE shipment_ref = ? LIMIT 1",
            (clean_ref,),
        ).fetchone() is not None

        cursor = conn.execute(
            """
            INSERT INTO tracking_pings (shipment_ref, lat, lng, speed, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clean_ref, latitude, longitude, speed_value, timestamp_value),
        )

        if not had_existing_pings:
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description, location)
                VALUES (?, ?, ?, ?)
                """,
                (
                    shipment["id"],
                    "GPS Tracking Started",
                    "First live GPS ping received for this shipment.",
                    f"{latitude:.4f}, {longitude:.4f}",
                ),
            )

        conn.commit()
        row = conn.execute(
            """
            SELECT id, shipment_ref, lat, lng, speed, timestamp
            FROM tracking_pings
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return _serialize_tracking_ping(row)
    finally:
        conn.close()


def _build_live_eta_details(shipment, last_ping, origin_coords, destination_coords):
    eta_value = shipment.get("eta")
    eta_details = {
        "value": eta_value,
        "display": _format_tracking_datetime(eta_value),
        "summary": _build_eta_summary(shipment.get("status"), eta_value),
        "source_label": "Scheduled ETA",
        "is_live": False,
        "remaining_km": None,
    }
    if not last_ping or shipment.get("status") in {"Delivered", "Cancelled"}:
        return eta_details
    if not destination_coords:
        return eta_details

    current_coords = (last_ping["lat"], last_ping["lng"])
    remaining_km = _distance_km(current_coords, destination_coords)
    if remaining_km is None:
        return eta_details
    eta_details["remaining_km"] = round(remaining_km, 1)

    planned_etd = _parse_tracking_datetime(shipment.get("etd"))
    planned_eta = _parse_tracking_datetime(shipment.get("eta"))
    if not origin_coords or not planned_etd or not planned_eta or planned_eta <= planned_etd:
        return eta_details

    total_km = _distance_km(origin_coords, destination_coords)
    if not total_km or total_km <= 0:
        return eta_details

    remaining_ratio = max(0.0, min(1.15, remaining_km / total_km))
    ping_dt = _parse_tracking_datetime(last_ping.get("timestamp")) or datetime.utcnow()
    if ping_dt.tzinfo is not None:
        ping_dt = ping_dt.astimezone(timezone.utc).replace(tzinfo=None)
    recalculated_eta = ping_dt + ((planned_eta - planned_etd) * remaining_ratio)
    recalculated_eta_value = recalculated_eta.strftime("%Y-%m-%d %H:%M:%S")

    eta_details["value"] = recalculated_eta_value
    eta_details["display"] = _format_tracking_datetime(recalculated_eta_value)
    eta_details["summary"] = _build_eta_summary(shipment.get("status"), recalculated_eta_value)
    eta_details["source_label"] = "GPS ETA"
    eta_details["is_live"] = True
    return eta_details


def _calculate_live_progress(status, etd_value, eta_value, last_ping, origin_coords, destination_coords):
    if last_ping and origin_coords and destination_coords and status not in {"Delivered", "Cancelled"}:
        total_km = _distance_km(origin_coords, destination_coords)
        remaining_km = _distance_km((last_ping["lat"], last_ping["lng"]), destination_coords)
        if total_km and remaining_km is not None and total_km > 0:
            live_progress = round((1 - min(max(remaining_km / total_km, 0), 1)) * 100)
            return max(STATUS_PROGRESS.get(status, 18), min(96, live_progress))
    return _calculate_progress(status, etd_value, eta_value)


def _build_tracking_map_data(shipment, pings, origin_coords, destination_coords):
    trail = [
        {
            "lat": ping["lat"],
            "lng": ping["lng"],
            "timestamp_display": ping["timestamp_display"],
            "speed": ping["speed"],
        }
        for ping in pings
    ]
    origin_marker = (
        {
            "lat": round(origin_coords[0], 6),
            "lng": round(origin_coords[1], 6),
            "label": shipment.get("origin_port") or "Origin",
        }
        if origin_coords
        else None
    )
    destination_marker = (
        {
            "lat": round(destination_coords[0], 6),
            "lng": round(destination_coords[1], 6),
            "label": shipment.get("destination_port") or "Destination",
        }
        if destination_coords
        else None
    )
    last_ping = trail[-1] if trail else None
    center = last_ping or origin_marker or destination_marker
    return {
        "trail": trail,
        "last_ping": last_ping,
        "origin": origin_marker,
        "destination": destination_marker,
        "center": [center["lat"], center["lng"]] if center else None,
        "has_live_data": bool(trail),
        "has_map_data": bool(center),
    }


def get_shipment_snapshot(ref):
    init_tms_db()
    conn = get_db()
    try:
        shipment_row = conn.execute(
            """
            SELECT
                s.*,
                tc.dot_number AS carrier_dot_number,
                tc.safety_rating AS carrier_safety_rating,
                tc.insurance_status AS carrier_insurance_status,
                tc.auth_status AS carrier_auth_status,
                tc.insurance_expires_at AS carrier_insurance_expires_at,
                tc.last_checked AS carrier_last_checked,
                tc.fmcsa_source_url AS carrier_fmcsa_source_url,
                d.name AS driver_name,
                d.license_number AS driver_license_number,
                d.phone AS driver_phone,
                d.country AS driver_country,
                d.status AS driver_status,
                d.checkin_token AS driver_checkin_token,
                d.last_location AS driver_last_location,
                d.last_checkin_at AS driver_last_checkin_at,
                d.last_issue AS driver_last_issue,
                v.truck_number AS vehicle_truck_number,
                v.vehicle_type AS vehicle_type,
                v.capacity_weight AS vehicle_capacity_weight,
                v.capacity_cbm AS vehicle_capacity_cbm,
                v.country AS vehicle_country,
                v.status AS vehicle_status
            FROM shipments s
            LEFT JOIN tms_carriers tc ON tc.id = s.carrier_id
            LEFT JOIN drivers d ON d.id = s.driver_id
            LEFT JOIN vehicles v ON v.id = s.vehicle_id
            WHERE s.shipment_ref = ?
            """,
            (ref,),
        ).fetchone()
        if not shipment_row:
            return None

        shipment = dict(shipment_row)
        shipment["carrier_safety_rating"] = _normalize_safety_rating(shipment.get("carrier_safety_rating"))
        shipment["carrier_safety_badge_class"] = _safety_badge_class(shipment.get("carrier_safety_rating"))
        shipment["carrier_insurance_alert"] = ""
        expires_on = _parse_mmddyyyy_date(shipment.get("carrier_insurance_expires_at"))
        if expires_on:
            days_remaining = (expires_on - datetime.utcnow().date()).days
            if days_remaining < 0:
                shipment["carrier_insurance_alert"] = f"Carrier insurance expired on {expires_on.isoformat()}."
            elif days_remaining <= 30:
                shipment["carrier_insurance_alert"] = f"Carrier insurance expires in {days_remaining} day{'s' if days_remaining != 1 else ''}."
        contract_rate = None
        if shipment.get("contract_rate_id"):
            rate_row = conn.execute(
                "SELECT * FROM contract_rates WHERE id = ?",
                (shipment["contract_rate_id"],),
            ).fetchone()
            if rate_row:
                contract_rate = _build_contract_rate_row(
                    rate_row,
                    containers=shipment.get("containers", ""),
                    reference_date=shipment.get("etd"),
                )
                contract_rate["match_source"] = "applied"

        if contract_rate is None:
            contract_rate = find_best_contract_rate(
                origin=shipment.get("origin_port", ""),
                destination=shipment.get("destination_port", ""),
                mode=shipment.get("mode", ""),
                containers=shipment.get("containers", ""),
                reference_date=shipment.get("etd"),
                conn=conn,
            )
            if contract_rate:
                contract_rate["match_source"] = "live"

        shipment["matched_contract_rate"] = contract_rate
        load_assignment = conn.execute(
            """
            SELECT l.load_ref, l.status
            FROM load_shipments ls
            JOIN loads l ON l.id = ls.load_id
            WHERE ls.shipment_ref = ?
            """,
            (ref,),
        ).fetchone()
        shipment["load_ref"] = load_assignment["load_ref"] if load_assignment else ""
        shipment["load_status"] = load_assignment["status"] if load_assignment else ""
        events = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM shipment_events WHERE shipment_id=? ORDER BY event_date DESC, id DESC",
                (shipment["id"],),
            ).fetchall()
        ]
        return {
            "shipment": shipment,
            "events": events,
            "settings": _get_settings(conn),
        }
    finally:
        conn.close()


def _build_tracking_context(shipment, events, settings, pings=None):
    shipment = dict(shipment)
    events = [dict(event) for event in events]
    latest_event = events[0] if events else None
    pings = list(pings) if pings is not None else list_tracking_pings(shipment.get("shipment_ref"))
    last_ping = pings[-1] if pings else None
    origin_coords = _lookup_location_coordinates(shipment.get("origin_port"))
    destination_coords = _lookup_location_coordinates(shipment.get("destination_port"))
    eta_details = _build_live_eta_details(shipment, last_ping, origin_coords, destination_coords)
    tracking_map = _build_tracking_map_data(shipment, pings, origin_coords, destination_coords)

    if last_ping:
        current_location = f"{last_ping['lat']:.4f}, {last_ping['lng']:.4f}"
        last_updated_value = last_ping.get("timestamp")
    else:
        current_location = next(
            (event.get("location") for event in events if event.get("location")),
            shipment.get("origin_port") or "",
        )
        last_updated_value = latest_event.get("event_date") if latest_event else shipment.get("updated_at")

    for event in events:
        event["event_date_display"] = _format_tracking_datetime(event.get("event_date"))

    shipment["status_variant"] = STATUS_VARIANTS.get(shipment.get("status"), "secondary")
    shipment["etd_display"] = _format_tracking_datetime(shipment.get("etd"))
    shipment["eta_display"] = _format_tracking_datetime(shipment.get("eta"))
    shipment["last_updated_display"] = _format_tracking_datetime(
        last_updated_value
    )

    tracking = {
        "route_label": " to ".join(
            [part for part in [shipment.get("origin_port"), shipment.get("destination_port")] if part]
        ) or "Route pending",
        "eta_value": eta_details["value"],
        "eta_display": eta_details["display"],
        "eta_summary": eta_details["summary"],
        "eta_source_label": eta_details["source_label"],
        "eta_is_live": eta_details["is_live"],
        "progress_percent": _calculate_live_progress(
            shipment.get("status"),
            shipment.get("etd"),
            shipment.get("eta"),
            last_ping,
            origin_coords,
            destination_coords,
        ),
        "event_count": len(events),
        "current_location": current_location or "Location pending",
        "latest_event": latest_event,
        "gps_ping_count": len(pings),
        "last_ping_display": last_ping["timestamp_display"] if last_ping else "Awaiting first GPS ping",
        "last_speed": last_ping.get("speed") if last_ping else None,
        "has_live_data": bool(last_ping),
        "remaining_km": eta_details["remaining_km"],
    }

    return {
        "shipment": shipment,
        "events": events,
        "settings": settings,
        "tracking": tracking,
        "tracking_map": tracking_map,
        "tracking_pings": pings,
    }


def get_tracking_page_context(ref):
    snapshot = get_shipment_snapshot(ref)
    if not snapshot:
        return None
    return _build_tracking_context(snapshot["shipment"], snapshot["events"], snapshot["settings"])


def _coerce_tracking_compare_datetime(value):
    parsed = _parse_tracking_datetime(value)
    if not parsed:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _interpolate_coordinates(origin_coords, destination_coords, ratio):
    if not origin_coords or not destination_coords:
        return None
    bounded_ratio = max(0.0, min(1.0, float(ratio or 0)))
    return (
        round(origin_coords[0] + ((destination_coords[0] - origin_coords[0]) * bounded_ratio), 6),
        round(origin_coords[1] + ((destination_coords[1] - origin_coords[1]) * bounded_ratio), 6),
    )


def _resolve_control_tower_marker(
    shipment,
    tracking,
    tracking_map,
    origin_coords,
    destination_coords,
    fallback_coords=None,
):
    last_ping = tracking_map.get("last_ping")
    if last_ping:
        return {
            "lat": round(float(last_ping["lat"]), 6),
            "lng": round(float(last_ping["lng"]), 6),
            "source": "gps",
        }

    if origin_coords and destination_coords:
        if shipment.get("status") == "Draft":
            interpolated_coords = origin_coords
            source = "origin"
        else:
            progress_ratio = max(0.08, min(0.92, float(tracking.get("progress_percent") or 0) / 100))
            interpolated_coords = _interpolate_coordinates(origin_coords, destination_coords, progress_ratio)
            source = "estimated"
        return {
            "lat": interpolated_coords[0],
            "lng": interpolated_coords[1],
            "source": source,
        }

    if origin_coords:
        return {
            "lat": round(float(origin_coords[0]), 6),
            "lng": round(float(origin_coords[1]), 6),
            "source": "origin",
        }

    if destination_coords:
        return {
            "lat": round(float(destination_coords[0]), 6),
            "lng": round(float(destination_coords[1]), 6),
            "source": "destination",
        }

    if fallback_coords:
        return {
            "lat": round(float(fallback_coords[0]), 6),
            "lng": round(float(fallback_coords[1]), 6),
            "source": "location",
        }

    return None


def _derive_control_tower_health(shipment, tracking, tracking_map):
    if shipment.get("status") == "Draft":
        return {
            "key": "draft",
            "label": CONTROL_TOWER_HEALTH_LABELS["draft"],
            "reason": "Shipment is still in draft and awaiting dispatch.",
        }

    eta_dt = _coerce_tracking_compare_datetime(
        tracking.get("eta_value") or shipment.get("eta")
    )
    eta_summary = tracking.get("eta_summary") or "ETA pending"
    now = datetime.utcnow()
    last_ping = tracking_map.get("last_ping")
    remaining_km = tracking.get("remaining_km")

    if not eta_dt:
        return {
            "key": "at_risk",
            "label": CONTROL_TOWER_HEALTH_LABELS["at_risk"],
            "reason": "ETA is missing for this active shipment.",
        }

    if eta_dt < now:
        return {
            "key": "delayed",
            "label": CONTROL_TOWER_HEALTH_LABELS["delayed"],
            "reason": eta_summary,
        }

    planned_progress = _calculate_progress(
        shipment.get("status"),
        shipment.get("etd"),
        shipment.get("eta"),
    )
    live_progress = float(tracking.get("progress_percent") or 0)
    progress_gap = max(0, round(planned_progress - live_progress))
    hours_to_eta = (eta_dt - now).total_seconds() / 3600

    if last_ping and progress_gap >= 18:
        if remaining_km is not None:
            reason = f"{remaining_km:,.0f} km remaining with {eta_summary.lower()}."
        else:
            reason = f"Live route progress trails schedule by {progress_gap}%."
        return {
            "key": "at_risk",
            "label": CONTROL_TOWER_HEALTH_LABELS["at_risk"],
            "reason": reason,
        }

    if last_ping and hours_to_eta <= 24:
        if last_ping and remaining_km is not None:
            reason = f"{remaining_km:,.0f} km remaining with {eta_summary.lower()}."
        elif last_ping:
            reason = eta_summary
        else:
            reason = f"No GPS ping and {eta_summary.lower()}."
        return {
            "key": "at_risk",
            "label": CONTROL_TOWER_HEALTH_LABELS["at_risk"],
            "reason": reason,
        }

    return {
        "key": "on_time",
        "label": CONTROL_TOWER_HEALTH_LABELS["on_time"],
        "reason": "Shipment is tracking to plan.",
    }


def get_control_tower_context():
    init_tms_db()
    conn = get_db()
    try:
        settings = _get_settings(conn)
        placeholders = ",".join("?" for _ in CONTROL_TOWER_ACTIVE_STATUSES)
        shipment_rows = conn.execute(
            f"""
            SELECT *
            FROM shipments
            WHERE status IN ({placeholders})
            ORDER BY
                CASE status
                    WHEN 'In Transit' THEN 0
                    WHEN 'Active' THEN 1
                    WHEN 'Booked' THEN 2
                    WHEN 'Draft' THEN 3
                    ELSE 4
                END,
                COALESCE(datetime(eta), datetime('2999-12-31 00:00:00')) ASC,
                datetime(created_at) DESC,
                id DESC
            """,
            CONTROL_TOWER_ACTIVE_STATUSES,
        ).fetchall()

        if not shipment_rows:
            return {
                "settings": settings,
                "shipments": [],
                "counts": {
                    "total": 0,
                    "on_time": 0,
                    "at_risk": 0,
                    "delayed": 0,
                    "draft": 0,
                },
                "filters": {
                    "statuses": [
                        {"value": key, "label": label}
                        for key, label in CONTROL_TOWER_HEALTH_LABELS.items()
                    ],
                    "carriers": [],
                    "modes": [],
                },
                "exceptions": [],
                "refreshed_at": _format_tracking_datetime(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
            }

        shipment_ids = [row["id"] for row in shipment_rows]
        shipment_refs = [row["shipment_ref"] for row in shipment_rows]

        events_by_id = {shipment_id: [] for shipment_id in shipment_ids}
        event_placeholders = ",".join("?" for _ in shipment_ids)
        for row in conn.execute(
            f"""
            SELECT *
            FROM shipment_events
            WHERE shipment_id IN ({event_placeholders})
            ORDER BY event_date DESC, id DESC
            """,
            shipment_ids,
        ).fetchall():
            events_by_id[row["shipment_id"]].append(dict(row))

        pings_by_ref = {shipment_ref: [] for shipment_ref in shipment_refs}
        ping_placeholders = ",".join("?" for _ in shipment_refs)
        for row in conn.execute(
            f"""
            SELECT id, shipment_ref, lat, lng, speed, timestamp
            FROM tracking_pings
            WHERE shipment_ref IN ({ping_placeholders})
            ORDER BY shipment_ref ASC, datetime(timestamp) ASC, id ASC
            """,
            shipment_refs,
        ).fetchall():
            pings_by_ref[row["shipment_ref"]].append(_serialize_tracking_ping(row))

        shipments = []
        for row in shipment_rows:
            shipment = dict(row)
            tracking_context = _build_tracking_context(
                shipment,
                events_by_id.get(shipment["id"], []),
                settings,
                pings=pings_by_ref.get(shipment["shipment_ref"], []),
            )
            shipment_data = tracking_context["shipment"]
            tracking = tracking_context["tracking"]
            tracking_map = tracking_context["tracking_map"]
            origin_marker = tracking_map.get("origin")
            destination_marker = tracking_map.get("destination")
            origin_coords = (
                (origin_marker["lat"], origin_marker["lng"])
                if origin_marker
                else None
            )
            destination_coords = (
                (destination_marker["lat"], destination_marker["lng"])
                if destination_marker
                else None
            )
            fallback_coords = None
            current_location = tracking.get("current_location")
            if current_location and current_location != "Location pending":
                fallback_coords = _lookup_location_coordinates(current_location)

            health = _derive_control_tower_health(shipment_data, tracking, tracking_map)
            marker = _resolve_control_tower_marker(
                shipment_data,
                tracking,
                tracking_map,
                origin_coords,
                destination_coords,
                fallback_coords=fallback_coords,
            )
            eta_dt = _coerce_tracking_compare_datetime(shipment_data.get("eta"))
            shipments.append(
                {
                    "shipment_ref": shipment_data.get("shipment_ref"),
                    "shipment_status": shipment_data.get("status"),
                    "health_key": health["key"],
                    "health_label": health["label"],
                    "health_reason": health["reason"],
                    "carrier_name": shipment_data.get("carrier_name") or "Unassigned",
                    "mode": shipment_data.get("mode") or "Unspecified",
                    "origin_port": shipment_data.get("origin_port") or "",
                    "destination_port": shipment_data.get("destination_port") or "",
                    "route_label": tracking.get("route_label"),
                    "current_location": tracking.get("current_location"),
                    "progress_percent": tracking.get("progress_percent"),
                    "eta_display": tracking.get("eta_display"),
                    "eta_summary": tracking.get("eta_summary"),
                    "eta_source_label": tracking.get("eta_source_label"),
                    "eta_value": shipment_data.get("eta") or "",
                    "etd_display": shipment_data.get("etd_display"),
                    "gps_ping_count": tracking.get("gps_ping_count"),
                    "has_live_data": tracking.get("has_live_data"),
                    "last_ping_display": tracking.get("last_ping_display"),
                    "remaining_km": tracking.get("remaining_km"),
                    "marker": marker,
                    "origin_marker": origin_marker,
                    "destination_marker": destination_marker,
                    "gps_path": tracking_map.get("trail", []),
                    "last_ping": tracking_map.get("last_ping"),
                    "view_url": f"/tms/shipments/{shipment_data.get('shipment_ref')}",
                    "updated_at_display": shipment_data.get("last_updated_display"),
                    "sort_eta": eta_dt.isoformat() if eta_dt else "",
                }
            )

        shipments.sort(
            key=lambda shipment: (
                CONTROL_TOWER_HEALTH_PRIORITY.get(shipment["health_key"], 99),
                shipment["sort_eta"] or "9999-12-31T00:00:00",
                shipment["shipment_ref"] or "",
            )
        )

        counts = {
            "total": len(shipments),
            "on_time": 0,
            "at_risk": 0,
            "delayed": 0,
            "draft": 0,
        }
        for shipment in shipments:
            counts[shipment["health_key"]] = counts.get(shipment["health_key"], 0) + 1
            shipment.pop("sort_eta", None)

        exceptions = [
            {
                "shipment_ref": shipment["shipment_ref"],
                "health_key": shipment["health_key"],
                "health_label": shipment["health_label"],
                "health_reason": shipment["health_reason"],
                "carrier_name": shipment["carrier_name"],
                "route_label": shipment["route_label"],
                "eta_display": shipment["eta_display"],
                "view_url": shipment["view_url"],
            }
            for shipment in shipments
            if shipment["health_key"] in {"delayed", "at_risk"}
        ]

        return {
            "settings": settings,
            "shipments": shipments,
            "counts": counts,
            "filters": {
                "statuses": [
                    {"value": key, "label": CONTROL_TOWER_HEALTH_LABELS[key]}
                    for key in ("on_time", "at_risk", "delayed", "draft")
                ],
                "carriers": sorted(
                    {
                        shipment["carrier_name"]
                        for shipment in shipments
                        if shipment["carrier_name"] and shipment["carrier_name"] != "Unassigned"
                    },
                    key=str.lower,
                ),
                "modes": sorted(
                    {
                        shipment["mode"]
                        for shipment in shipments
                        if shipment["mode"] and shipment["mode"] != "Unspecified"
                    },
                    key=str.lower,
                ),
            },
            "exceptions": exceptions,
            "refreshed_at": _format_tracking_datetime(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        }
    finally:
        conn.close()


def _fetch_shipments_for_refs(conn, shipment_refs):
    refs = _dedupe_shipment_refs(shipment_refs)
    if not refs:
        return []

    placeholders = ",".join("?" for _ in refs)
    shipment_rows = conn.execute(
        f"SELECT * FROM shipments WHERE shipment_ref IN ({placeholders})",
        refs,
    ).fetchall()
    shipment_map = {row["shipment_ref"]: dict(row) for row in shipment_rows}
    if not shipment_map:
        return []

    shipment_ids = [shipment["id"] for shipment in shipment_map.values()]
    event_placeholders = ",".join("?" for _ in shipment_ids)
    events_by_id = {shipment_id: [] for shipment_id in shipment_ids}
    for row in conn.execute(
        f"""
        SELECT * FROM shipment_events
        WHERE shipment_id IN ({event_placeholders})
        ORDER BY event_date DESC, id DESC
        """,
        shipment_ids,
    ).fetchall():
        events_by_id[row["shipment_id"]].append(dict(row))

    shipments = []
    for ref in refs:
        shipment = shipment_map.get(ref)
        if shipment:
            shipments.append(
                {
                    "shipment": shipment,
                    "events": events_by_id.get(shipment["id"], []),
                }
            )
    return shipments


def get_portal_dashboard_context(token, selected_ref=None):
    init_tms_db()
    portal_token = get_portal_token(token)
    if not portal_token:
        return None

    conn = get_db()
    try:
        settings = _get_settings(conn)
        shipment_items = []
        for item in _fetch_shipments_for_refs(conn, portal_token["shipment_refs"]):
            shipment_items.append(_build_tracking_context(item["shipment"], item["events"], settings))

        selected_ref = _normalize_text(selected_ref)
        selected_item = next(
            (item for item in shipment_items if item["shipment"]["shipment_ref"] == selected_ref),
            None,
        )
        if selected_item is None and shipment_items:
            selected_item = shipment_items[0]

        stats = {
            "shipments": len(shipment_items),
            "active": sum(
                1
                for item in shipment_items
                if item["shipment"].get("status") in {"Active", "Booked", "In Transit"}
            ),
            "delivered": sum(
                1 for item in shipment_items if item["shipment"].get("status") == "Delivered"
            ),
            "pending_documents": sum(
                1
                for item in shipment_items
                if item["shipment"].get("status") not in {"Delivered", "Cancelled"}
            ),
        }

        return {
            "portal_token": portal_token,
            "shipments": shipment_items,
            "selected_shipment": selected_item["shipment"] if selected_item else None,
            "selected_events": selected_item["events"] if selected_item else [],
            "selected_tracking": selected_item["tracking"] if selected_item else None,
            "settings": settings,
            "stats": stats,
        }
    finally:
        conn.close()


def get_portal_shipment_snapshot(token, ref):
    context = get_portal_dashboard_context(token, selected_ref=ref)
    if not context or not context["selected_shipment"]:
        return None
    if context["selected_shipment"]["shipment_ref"] != _normalize_text(ref):
        return None
    return {
        "portal_token": context["portal_token"],
        "shipment": context["selected_shipment"],
        "events": context["selected_events"],
        "tracking": context["selected_tracking"],
        "settings": context["settings"],
    }


def create_portal_shipment_request(token, form_data):
    portal_token = get_portal_token(token)
    if not portal_token:
        raise ValueError("Portal access was not found.")

    shipper_name = _normalize_text(form_data.get("shipper_name")) or portal_token["customer_name"]
    consignee_name = _normalize_text(form_data.get("consignee_name"))
    origin_port = _normalize_text(form_data.get("origin_port"))
    destination_port = _normalize_text(form_data.get("destination_port"))
    cargo_description = _normalize_text(form_data.get("cargo_description"))
    if not consignee_name:
        raise ValueError("Consignee name is required.")
    if not origin_port:
        raise ValueError("Origin is required.")
    if not destination_port:
        raise ValueError("Destination is required.")
    if not cargo_description:
        raise ValueError("Cargo description is required.")

    ref = generate_ref()
    notes = _normalize_text(form_data.get("notes"))
    notes_prefix = f"Portal request submitted by {portal_token['customer_name']}"
    if portal_token.get("email"):
        notes_prefix += f" ({portal_token['email']})"
    if notes:
        notes = f"{notes_prefix}\n{notes}"
    else:
        notes = notes_prefix

    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO shipments
            (
                shipment_ref, status, shipper_name, shipper_address, consignee_name, consignee_address,
                origin_port, destination_port, mode, etd, eta, cargo_description, containers,
                weight_kg, volume_cbm, freight_rate, currency, incoterm, notes
            )
            VALUES (?, 'Draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                ref,
                shipper_name,
                _normalize_text(form_data.get("shipper_address")),
                consignee_name,
                _normalize_text(form_data.get("consignee_address")),
                origin_port,
                destination_port,
                _normalize_text(form_data.get("mode")) or "FTL",
                _normalize_text(form_data.get("etd")),
                _normalize_text(form_data.get("eta")),
                cargo_description,
                _normalize_text(form_data.get("containers")),
                _parse_optional_number(form_data.get("weight_kg"), "Weight"),
                _parse_optional_number(form_data.get("volume_cbm"), "Volume"),
                _normalize_text(form_data.get("currency")) or "USD",
                _normalize_text(form_data.get("incoterm")) or "FOB",
                notes,
            ),
        )
        shipment_id = cursor.lastrowid
        refresh_shipment_carbon(conn, shipment_id=shipment_id)
        conn.execute(
            """
            INSERT INTO shipment_events (shipment_id, event_type, description, location, created_by)
            VALUES (?, 'Request Submitted', ?, ?, 'portal')
            """,
            (
                shipment_id,
                f"Shipment request {ref} submitted through the customer portal.",
                origin_port,
            ),
        )
        conn.execute(
            """
            UPDATE portal_tokens
            SET shipment_refs = ?
            WHERE token = ?
            """,
            (
                _serialize_shipment_refs(portal_token["shipment_refs"] + [ref]),
                portal_token["token"],
            ),
        )
        conn.commit()
        return ref
    finally:
        conn.close()


def create_portal_quote_request(token, form_data):
    portal_token = get_portal_token(token)
    if not portal_token:
        raise ValueError("Portal access was not found.")

    origin = _normalize_text(form_data.get("origin"))
    destination = _normalize_text(form_data.get("destination"))
    cargo_description = _normalize_text(form_data.get("cargo_description"))
    equipment_type = _normalize_text(form_data.get("equipment_type"))
    if not origin:
        raise ValueError("Origin is required.")
    if not destination:
        raise ValueError("Destination is required.")
    if not cargo_description:
        raise ValueError("Cargo description is required.")
    if not equipment_type:
        raise ValueError("Equipment type is required.")

    pickup_date = _parse_nullable_iso_date(form_data.get("pickup_date"), "Pickup date")
    delivery_date = _parse_nullable_iso_date(form_data.get("delivery_date"), "Delivery date")
    if pickup_date and delivery_date and delivery_date < pickup_date:
        raise ValueError("Delivery date must be on or after pickup date.")

    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO portal_quote_requests (
                portal_token,
                customer_name,
                origin,
                destination,
                cargo_description,
                weight_kg,
                volume_cbm,
                equipment_type,
                pickup_date,
                delivery_date,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portal_token["token"],
                portal_token["customer_name"],
                origin,
                destination,
                cargo_description,
                _parse_nullable_number(form_data.get("weight_kg"), "Weight"),
                _parse_nullable_number(form_data.get("volume_cbm"), "Volume"),
                equipment_type,
                pickup_date,
                delivery_date,
                _normalize_text(form_data.get("notes")),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_portal_quote_request(request_id, portal_token=None):
    init_tms_db()
    try:
        request_number = int(request_id)
    except (TypeError, ValueError):
        return None

    normalized_token = _normalize_portal_token(portal_token) if portal_token else ""
    conn = get_db()
    try:
        sql = """
            SELECT r.*, pt.email AS customer_email
            FROM portal_quote_requests r
            LEFT JOIN portal_tokens pt ON upper(pt.token) = upper(r.portal_token)
            WHERE r.id = ?
        """
        params = [request_number]
        if normalized_token:
            sql += " AND upper(r.portal_token) = ?"
            params.append(normalized_token)
        row = conn.execute(sql, params).fetchone()
        return _portal_quote_request_row_to_dict(row)
    finally:
        conn.close()


def list_portal_quote_requests(portal_token=None):
    init_tms_db()
    normalized_token = _normalize_portal_token(portal_token) if portal_token else ""
    conn = get_db()
    try:
        sql = """
            SELECT r.*, pt.email AS customer_email
            FROM portal_quote_requests r
            LEFT JOIN portal_tokens pt ON upper(pt.token) = upper(r.portal_token)
        """
        params = []
        if normalized_token:
            sql += " WHERE upper(r.portal_token) = ?"
            params.append(normalized_token)
        sql += """
            ORDER BY
                CASE lower(r.status)
                    WHEN 'pending' THEN 0
                    WHEN 'quoted' THEN 1
                    WHEN 'booked' THEN 2
                    WHEN 'cancelled' THEN 3
                    ELSE 4
                END,
                datetime(r.created_at) DESC,
                r.id DESC
        """
        rows = conn.execute(sql, params).fetchall()
        return [_portal_quote_request_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def quote_portal_quote_request(request_id, quoted_rate, quoted_by="", notes=""):
    init_tms_db()
    try:
        request_number = int(request_id)
    except (TypeError, ValueError):
        raise ValueError("Portal quote request was not found.")

    raw_rate = _normalize_text(quoted_rate)
    if not raw_rate:
        raise ValueError("Quoted rate is required.")

    try:
        parsed_rate = round(float(raw_rate), 2)
    except ValueError as exc:
        raise ValueError("Quoted rate must be a valid number.") from exc
    if parsed_rate <= 0:
        raise ValueError("Quoted rate must be greater than zero.")

    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT r.*, pt.email AS customer_email
            FROM portal_quote_requests r
            LEFT JOIN portal_tokens pt ON upper(pt.token) = upper(r.portal_token)
            WHERE r.id = ?
            """,
            (request_number,),
        ).fetchone()
        portal_request = _portal_quote_request_row_to_dict(row)
        if not portal_request:
            raise ValueError("Portal quote request was not found.")
        if portal_request["status"] != "pending":
            raise ValueError("Only pending portal quote requests can be quoted.")

        dispatcher_note = _normalize_text(notes)
        updated_notes = portal_request["notes"]
        if dispatcher_note:
            updated_notes = (
                f"{updated_notes}\n\nDispatcher quote note:\n{dispatcher_note}"
                if updated_notes
                else f"Dispatcher quote note:\n{dispatcher_note}"
            )

        conn.execute(
            """
            UPDATE portal_quote_requests
            SET status = 'quoted',
                quoted_rate = ?,
                quoted_by = ?,
                quoted_at = CURRENT_TIMESTAMP,
                notes = ?
            WHERE id = ?
            """,
            (
                parsed_rate,
                _normalize_text(quoted_by) or "dispatcher",
                updated_notes,
                request_number,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return get_portal_quote_request(request_number)


def generate_load_ref():
    init_tms_db()
    conn = get_db()
    try:
        current_max = conn.execute("SELECT COALESCE(MAX(id), 0) FROM loads").fetchone()[0]
        return f"LOAD-{datetime.now().year}-{current_max + 1:04d}"
    finally:
        conn.close()


def list_available_load_shipments():
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT s.*
            FROM shipments s
            LEFT JOIN load_shipments ls ON ls.shipment_ref = s.shipment_ref
            WHERE ls.shipment_ref IS NULL
              AND s.status NOT IN ('Delivered', 'Cancelled')
            ORDER BY
                CASE s.status
                    WHEN 'Booked' THEN 0
                    WHEN 'Active' THEN 1
                    WHEN 'Draft' THEN 2
                    WHEN 'In Transit' THEN 3
                    ELSE 4
                END,
                COALESCE(NULLIF(s.etd, ''), '9999-12-31') ASC,
                s.created_at DESC
            """
        ).fetchall()
        shipments = []
        for row in rows:
            shipment = dict(row)
            shipment["route_label"] = " -> ".join(
                [
                    part
                    for part in [
                        _normalize_text(shipment.get("origin_port")),
                        _normalize_text(shipment.get("destination_port")),
                    ]
                    if part
                ]
            ) or "Route pending"
            shipments.append(shipment)
        return shipments
    finally:
        conn.close()


def list_loads():
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT l.*, tc.name AS carrier_name
            FROM loads l
            LEFT JOIN tms_carriers tc ON tc.id = l.carrier_id
            ORDER BY datetime(l.created_at) DESC, l.id DESC
            """
        ).fetchall()
        loads = []
        for row in rows:
            load = _build_load_record(conn, row)
            loads.append(load)
        conn.commit()
        return loads
    finally:
        conn.close()


def get_load_snapshot(load_ref):
    init_tms_db()
    clean_ref = _normalize_text(load_ref)
    if not clean_ref:
        return None

    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT l.*, tc.name AS carrier_name
            FROM loads l
            LEFT JOIN tms_carriers tc ON tc.id = l.carrier_id
            WHERE l.load_ref = ?
            """,
            (clean_ref,),
        ).fetchone()
        if not row:
            return None

        load = _build_load_record(conn, row)
        conn.commit()
        return load
    finally:
        conn.close()


def create_load(*, shipment_refs, carrier_id=None, status="Planning"):
    init_tms_db()
    refs = _dedupe_shipment_refs(shipment_refs)
    if not refs:
        raise ValueError("Select at least one shipment to build a load.")

    load_status = _validate_load_status(status)
    clean_carrier_id = _normalize_text(carrier_id)
    carrier_id_value = None
    if clean_carrier_id:
        try:
            carrier_id_value = int(clean_carrier_id)
        except ValueError as exc:
            raise ValueError("Carrier selection is invalid.") from exc

    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in refs)
        shipment_rows = conn.execute(
            f"SELECT * FROM shipments WHERE shipment_ref IN ({placeholders})",
            refs,
        ).fetchall()
        shipment_map = {row["shipment_ref"]: dict(row) for row in shipment_rows}
        missing_refs = [ref for ref in refs if ref not in shipment_map]
        if missing_refs:
            raise ValueError(f"Shipments not found: {', '.join(missing_refs)}")

        assigned_rows = conn.execute(
            f"""
            SELECT ls.shipment_ref, l.load_ref
            FROM load_shipments ls
            JOIN loads l ON l.id = ls.load_id
            WHERE ls.shipment_ref IN ({placeholders})
            """,
            refs,
        ).fetchall()
        if assigned_rows:
            assignments = ", ".join(
                f"{row['shipment_ref']} ({row['load_ref']})"
                for row in assigned_rows
            )
            raise ValueError(f"Shipments already assigned to a load: {assignments}")

        if carrier_id_value is not None:
            carrier_exists = conn.execute(
                "SELECT id FROM tms_carriers WHERE id = ?",
                (carrier_id_value,),
            ).fetchone()
            if not carrier_exists:
                raise ValueError("Selected carrier was not found.")
        else:
            carrier_ids = {
                shipment.get("carrier_id")
                for shipment in shipment_map.values()
                if shipment.get("carrier_id")
            }
            if len(carrier_ids) == 1:
                carrier_id_value = carrier_ids.pop()

        load_ref = generate_load_ref()
        cursor = conn.execute(
            """
            INSERT INTO loads (load_ref, carrier_id, status, total_weight, total_cbm)
            VALUES (?, ?, ?, 0, 0)
            """,
            (load_ref, carrier_id_value, load_status),
        )
        load_id = cursor.lastrowid

        ordered_shipments = [shipment_map[ref] for ref in refs]
        for shipment in ordered_shipments:
            conn.execute(
                """
                INSERT INTO load_shipments (load_id, shipment_ref)
                VALUES (?, ?)
                """,
                (load_id, shipment["shipment_ref"]),
            )
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description)
                VALUES (?, 'Load Assigned', ?)
                """,
                (
                    shipment["id"],
                    f"Assigned to load {load_ref}.",
                ),
            )

        load_row = conn.execute(
            """
            SELECT l.*, tc.name AS carrier_name
            FROM loads l
            LEFT JOIN tms_carriers tc ON tc.id = l.carrier_id
            WHERE l.id = ?
            """,
            (load_id,),
        ).fetchone()
        load = _build_load_record(conn, load_row, shipments=ordered_shipments)
        conn.commit()
        return load
    finally:
        conn.close()


def update_load_status(load_ref, status):
    init_tms_db()
    clean_ref = _normalize_text(load_ref)
    if not clean_ref:
        raise ValueError("Load reference is required.")

    load_status = _validate_load_status(status)
    conn = get_db()
    try:
        load_row = conn.execute(
            """
            SELECT l.*, tc.name AS carrier_name
            FROM loads l
            LEFT JOIN tms_carriers tc ON tc.id = l.carrier_id
            WHERE l.load_ref = ?
            """,
            (clean_ref,),
        ).fetchone()
        if not load_row:
            raise ValueError("Load not found.")

        conn.execute(
            """
            UPDATE loads
            SET status = ?
            WHERE load_ref = ?
            """,
            (load_status, clean_ref),
        )
        for shipment in _fetch_load_shipments(conn, load_row["id"]):
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description)
                VALUES (?, 'Load Status', ?)
                """,
                (
                    shipment["id"],
                    f"Load {clean_ref} status updated to {load_status}.",
                ),
            )

        refreshed_row = conn.execute(
            """
            SELECT l.*, tc.name AS carrier_name
            FROM loads l
            LEFT JOIN tms_carriers tc ON tc.id = l.carrier_id
            WHERE l.load_ref = ?
            """,
            (clean_ref,),
        ).fetchone()
        load = _build_load_record(conn, refreshed_row)
        conn.commit()
        return load
    finally:
        conn.close()


def generate_ref():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM shipments")
    count = c.fetchone()[0] + 1
    conn.close()
    return f"TMS-{datetime.now().year}-{count:04d}"


def _generate_dock_booking_token(conn):
    while True:
        token = secrets.token_urlsafe(18)
        exists = conn.execute(
            "SELECT 1 FROM dock_appointments WHERE booking_token = ? LIMIT 1",
            (token,),
        ).fetchone()
        if not exists:
            return token


def _load_dock_row(conn, dock_id):
    return conn.execute(
        "SELECT * FROM docks WHERE id = ?",
        (dock_id,),
    ).fetchone()


def _load_dock_appointment_row(conn, *, appointment_id=None, shipment_ref=None, token=None):
    if appointment_id is not None:
        where_sql = "WHERE da.id = ?"
        params = [int(appointment_id)]
    elif shipment_ref is not None:
        where_sql = "WHERE UPPER(COALESCE(da.shipment_ref, '')) = UPPER(?)"
        params = [_normalize_text(shipment_ref)]
    elif token is not None:
        where_sql = "WHERE da.booking_token = ?"
        params = [_normalize_text(token)]
    else:
        raise ValueError("A dock appointment lookup requires an ID, shipment reference, or token.")

    return conn.execute(
        f"""
        SELECT
            da.*,
            d.name AS dock_name,
            d.dock_type,
            d.location AS dock_location,
            d.default_duration_minutes AS dock_default_duration_minutes,
            d.active AS dock_active,
            s.id AS shipment_id,
            s.status AS shipment_status,
            s.carrier_name AS shipment_carrier_name,
            s.shipper_name,
            s.consignee_name
        FROM dock_appointments da
        LEFT JOIN docks d ON d.id = da.dock_id
        LEFT JOIN shipments s ON UPPER(COALESCE(s.shipment_ref, '')) = UPPER(COALESCE(da.shipment_ref, ''))
        {where_sql}
        LIMIT 1
        """,
        params,
    ).fetchone()


def _find_conflicting_dock_appointment(conn, dock_id, scheduled_start, scheduled_end, exclude_id=None):
    params = [dock_id, scheduled_end.strftime("%Y-%m-%d %H:%M:%S"), scheduled_start.strftime("%Y-%m-%d %H:%M:%S")]
    exclude_sql = ""
    if exclude_id is not None:
        exclude_sql = "AND da.id != ?"
        params.append(int(exclude_id))

    row = conn.execute(
        f"""
        SELECT
            da.*,
            d.name AS dock_name,
            d.dock_type
        FROM dock_appointments da
        LEFT JOIN docks d ON d.id = da.dock_id
        WHERE da.dock_id = ?
          AND COALESCE(da.status, 'Scheduled') NOT IN ('Complete', 'No-Show')
          AND COALESCE(da.scheduled_start, '') != ''
          AND COALESCE(da.scheduled_end, '') != ''
          AND datetime(da.scheduled_start) < datetime(?)
          AND datetime(da.scheduled_end) > datetime(?)
          {exclude_sql}
        ORDER BY datetime(da.scheduled_start) ASC, da.id ASC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return _hydrate_dock_appointment_row(row)


def _coerce_dock_schedule_date(value):
    if isinstance(value, date):
        return value

    raw = _normalize_text(value)
    if not raw:
        return datetime.now().date()

    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("Schedule date must be a valid ISO date.") from exc


def list_docks(active_only=False):
    init_tms_db()
    conn = get_db()
    try:
        where_sql = "WHERE COALESCE(active, 1) = 1" if active_only else ""
        rows = conn.execute(
            f"""
            SELECT *
            FROM docks
            {where_sql}
            ORDER BY COALESCE(active, 1) DESC, name COLLATE NOCASE ASC, id ASC
            """
        ).fetchall()
        return [_serialize_dock(row) for row in rows]
    finally:
        conn.close()


def get_dock(dock_id):
    parsed_dock_id = _parse_optional_integer(dock_id, "Dock")
    if parsed_dock_id is None:
        return None

    init_tms_db()
    conn = get_db()
    try:
        row = _load_dock_row(conn, parsed_dock_id)
        return _serialize_dock(row) if row else None
    finally:
        conn.close()


def save_dock(dock_id=None, *, name, dock_type, location="", default_duration_minutes=60, active=1):
    clean_name = _normalize_text(name)
    if not clean_name:
        raise ValueError("Dock name is required.")

    clean_type = _normalize_dock_type(dock_type)
    clean_location = _normalize_text(location)
    duration_minutes = _parse_duration_minutes(default_duration_minutes, "Default appointment duration")
    active_value = 0 if str(active).strip() in {"0", "false", "False", ""} else 1
    parsed_dock_id = _parse_optional_integer(dock_id, "Dock") if dock_id is not None else None

    init_tms_db()
    conn = get_db()
    try:
        duplicate = conn.execute(
            """
            SELECT id
            FROM docks
            WHERE lower(COALESCE(name, '')) = lower(?)
              AND (? IS NULL OR id != ?)
            LIMIT 1
            """,
            (clean_name, parsed_dock_id, parsed_dock_id),
        ).fetchone()
        if duplicate:
            raise ValueError("A dock with that name already exists.")

        if parsed_dock_id is None:
            cursor = conn.execute(
                """
                INSERT INTO docks (name, dock_type, location, default_duration_minutes, active, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (clean_name, clean_type, clean_location, duration_minutes, active_value),
            )
            parsed_dock_id = cursor.lastrowid
        else:
            existing = _load_dock_row(conn, parsed_dock_id)
            if not existing:
                raise ValueError("Dock not found.")
            conn.execute(
                """
                UPDATE docks
                SET name = ?, dock_type = ?, location = ?, default_duration_minutes = ?, active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (clean_name, clean_type, clean_location, duration_minutes, active_value, parsed_dock_id),
            )

        conn.commit()
        return _serialize_dock(_load_dock_row(conn, parsed_dock_id))
    finally:
        conn.close()


def get_dock_appointment(appointment_id=None, *, shipment_ref=None, token=None):
    if appointment_id is None and shipment_ref is None and token is None:
        return None

    init_tms_db()
    conn = get_db()
    try:
        row = _load_dock_appointment_row(
            conn,
            appointment_id=appointment_id,
            shipment_ref=shipment_ref,
            token=token,
        )
        return _hydrate_dock_appointment_row(row)
    finally:
        conn.close()


def list_dock_appointments(*, start=None, end=None, dock_id=None, shipment_ref=None, include_unscheduled=False):
    init_tms_db()
    conn = get_db()
    try:
        where_clauses = []
        params = []

        if dock_id is not None:
            where_clauses.append("da.dock_id = ?")
            params.append(_parse_optional_integer(dock_id, "Dock"))
        if shipment_ref is not None:
            where_clauses.append("UPPER(COALESCE(da.shipment_ref, '')) = UPPER(?)")
            params.append(_normalize_text(shipment_ref))
        if not include_unscheduled:
            where_clauses.append("COALESCE(da.scheduled_start, '') != ''")

        if start is not None:
            start_value = _coerce_dock_schedule_date(start)
            where_clauses.append("datetime(da.scheduled_end) >= datetime(?)")
            params.append(datetime.combine(start_value, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S"))
        if end is not None:
            end_value = _coerce_dock_schedule_date(end)
            where_clauses.append("datetime(da.scheduled_start) < datetime(?)")
            params.append(datetime.combine(end_value, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S"))

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        rows = conn.execute(
            f"""
            SELECT
                da.*,
                d.name AS dock_name,
                d.dock_type,
                d.location AS dock_location,
                d.default_duration_minutes AS dock_default_duration_minutes,
                s.id AS shipment_id,
                s.status AS shipment_status,
                s.carrier_name AS shipment_carrier_name,
                s.shipper_name,
                s.consignee_name
            FROM dock_appointments da
            LEFT JOIN docks d ON d.id = da.dock_id
            LEFT JOIN shipments s ON UPPER(COALESCE(s.shipment_ref, '')) = UPPER(COALESCE(da.shipment_ref, ''))
            {where_sql}
            ORDER BY
                CASE WHEN COALESCE(da.scheduled_start, '') = '' THEN 1 ELSE 0 END,
                datetime(COALESCE(da.scheduled_start, da.created_at)) ASC,
                da.id ASC
            """,
            params,
        ).fetchall()
        return [_hydrate_dock_appointment_row(row) for row in rows]
    finally:
        conn.close()


def get_or_create_dock_booking_token(shipment_ref):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        raise ValueError("Shipment reference is required.")

    init_tms_db()
    conn = get_db()
    try:
        shipment = conn.execute(
            """
            SELECT id, shipment_ref, carrier_name
            FROM shipments
            WHERE UPPER(shipment_ref) = UPPER(?)
            """,
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise LookupError("Shipment not found.")

        existing = _load_dock_appointment_row(conn, shipment_ref=shipment["shipment_ref"])
        if existing and existing["booking_token"]:
            return existing["booking_token"]

        token = _generate_dock_booking_token(conn)
        if existing:
            conn.execute(
                """
                UPDATE dock_appointments
                SET booking_token = ?, carrier_name = COALESCE(NULLIF(carrier_name, ''), ?), updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (token, shipment["carrier_name"] or "", existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO dock_appointments
                    (shipment_ref, booking_token, appointment_type, status, duration_minutes, carrier_name, booked_by, updated_at)
                VALUES (?, ?, 'inbound', 'Scheduled', 60, ?, 'carrier-link', CURRENT_TIMESTAMP)
                """,
                (shipment["shipment_ref"], token, shipment["carrier_name"] or ""),
            )
        conn.commit()
        return token
    finally:
        conn.close()


def save_dock_appointment(
    *,
    shipment_ref,
    dock_id,
    scheduled_start,
    appointment_type="inbound",
    status="Scheduled",
    notes="",
    booked_by="dispatch",
    contact_name="",
    contact_email="",
    appointment_id=None,
):
    clean_ref = _normalize_text(shipment_ref)
    if not clean_ref:
        raise ValueError("Shipment reference is required.")

    parsed_dock_id = _parse_optional_integer(dock_id, "Dock")
    if parsed_dock_id is None:
        raise ValueError("Dock is required.")

    clean_type = _normalize_dock_appointment_type(appointment_type)
    clean_status = _normalize_dock_appointment_status(status)
    clean_notes = _normalize_text(notes)
    clean_booked_by = _normalize_text(booked_by) or "dispatch"
    clean_contact_name = _normalize_text(contact_name)
    clean_contact_email = _normalize_text(contact_email)
    start_dt = _parse_dock_datetime(scheduled_start, "Appointment start")
    parsed_appointment_id = (
        _parse_optional_integer(appointment_id, "Appointment")
        if appointment_id is not None
        else None
    )

    init_tms_db()
    conn = get_db()
    try:
        shipment = conn.execute(
            """
            SELECT id, shipment_ref, carrier_name
            FROM shipments
            WHERE UPPER(shipment_ref) = UPPER(?)
            """,
            (clean_ref,),
        ).fetchone()
        if not shipment:
            raise ValueError("Shipment not found.")

        dock_row = _load_dock_row(conn, parsed_dock_id)
        if not dock_row:
            raise ValueError("Dock not found.")
        dock = _serialize_dock(dock_row)
        if not dock["active"]:
            raise ValueError("Selected dock is inactive.")
        if dock["dock_type"] not in {"both", clean_type}:
            raise ValueError(f"{dock['name']} only accepts {dock['dock_type']} appointments.")

        duration_minutes = int(dock["default_duration_minutes"] or 60)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        existing = None
        if parsed_appointment_id is not None:
            existing = _load_dock_appointment_row(conn, appointment_id=parsed_appointment_id)
            if not existing:
                raise ValueError("Appointment not found.")
            if _normalize_text(existing["shipment_ref"]) and existing["shipment_ref"].upper() != shipment["shipment_ref"].upper():
                raise ValueError("Appointment does not belong to that shipment.")
        else:
            existing = _load_dock_appointment_row(conn, shipment_ref=shipment["shipment_ref"])

        conflict = _find_conflicting_dock_appointment(
            conn,
            parsed_dock_id,
            start_dt,
            end_dt,
            exclude_id=existing["id"] if existing else None,
        )
        if conflict:
            raise ValueError(
                f"{conflict['dock_name'] or 'This dock'} is already booked for {conflict['schedule_label']}."
            )

        carrier_name = shipment["carrier_name"] or (existing["carrier_name"] if existing else "") or ""
        token = (
            existing["booking_token"]
            if existing and existing["booking_token"]
            else _generate_dock_booking_token(conn)
        )
        event_type = "Dock Appointment Scheduled"
        event_description = (
            f"{dock['name']} booked for {clean_type} from "
            f"{start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')}."
        )
        if existing and existing["scheduled_start"]:
            event_type = "Dock Appointment Rescheduled"
            event_description = (
                f"{dock['name']} rescheduled for {clean_type} from "
                f"{start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')}."
            )

        if existing:
            conn.execute(
                """
                UPDATE dock_appointments
                SET shipment_ref = ?, dock_id = ?, booking_token = ?, appointment_type = ?, status = ?,
                    scheduled_start = ?, scheduled_end = ?, duration_minutes = ?, carrier_name = ?,
                    contact_name = ?, contact_email = ?, notes = ?, booked_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    shipment["shipment_ref"],
                    parsed_dock_id,
                    token,
                    clean_type,
                    clean_status,
                    start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    duration_minutes,
                    carrier_name,
                    clean_contact_name,
                    clean_contact_email,
                    clean_notes,
                    clean_booked_by,
                    existing["id"],
                ),
            )
            appointment_row = _load_dock_appointment_row(conn, appointment_id=existing["id"])
        else:
            cursor = conn.execute(
                """
                INSERT INTO dock_appointments
                    (shipment_ref, dock_id, booking_token, appointment_type, status, scheduled_start, scheduled_end,
                     duration_minutes, carrier_name, contact_name, contact_email, notes, booked_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    shipment["shipment_ref"],
                    parsed_dock_id,
                    token,
                    clean_type,
                    clean_status,
                    start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    duration_minutes,
                    carrier_name,
                    clean_contact_name,
                    clean_contact_email,
                    clean_notes,
                    clean_booked_by,
                ),
            )
            appointment_row = _load_dock_appointment_row(conn, appointment_id=cursor.lastrowid)

        conn.execute(
            """
            INSERT INTO shipment_events (shipment_id, event_type, description)
            VALUES (?, ?, ?)
            """,
            (shipment["id"], event_type, event_description),
        )
        conn.commit()
        return _hydrate_dock_appointment_row(appointment_row)
    finally:
        conn.close()


def update_dock_appointment_status(appointment_id, status):
    parsed_appointment_id = _parse_optional_integer(appointment_id, "Appointment")
    if parsed_appointment_id is None:
        raise ValueError("Appointment is required.")

    clean_status = _normalize_dock_appointment_status(status)

    init_tms_db()
    conn = get_db()
    try:
        appointment = _load_dock_appointment_row(conn, appointment_id=parsed_appointment_id)
        if not appointment:
            raise ValueError("Appointment not found.")

        conn.execute(
            """
            UPDATE dock_appointments
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (clean_status, parsed_appointment_id),
        )

        if appointment["shipment_id"]:
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description)
                VALUES (?, ?, ?)
                """,
                (
                    appointment["shipment_id"],
                    "Dock Appointment Status",
                    f"Dock appointment updated to {clean_status}.",
                ),
            )

        conn.commit()
        return _hydrate_dock_appointment_row(
            _load_dock_appointment_row(conn, appointment_id=parsed_appointment_id)
        )
    finally:
        conn.close()


def build_dock_calendar(*, start_date=None, days=DOCK_DEFAULT_LOOKAHEAD_DAYS):
    calendar_start = _coerce_dock_schedule_date(start_date)
    safe_days = max(int(days or DOCK_DEFAULT_LOOKAHEAD_DAYS), 1)
    calendar_end = calendar_start + timedelta(days=safe_days)

    docks = list_docks(active_only=False)
    appointments = list_dock_appointments(
        start=calendar_start,
        end=calendar_end,
        include_unscheduled=False,
    )

    day_rows = []
    for offset in range(safe_days):
        day_value = calendar_start + timedelta(days=offset)
        day_rows.append(
            {
                "date": day_value,
                "iso": day_value.isoformat(),
                "label": day_value.strftime("%a %b %d"),
            }
        )

    appointments_by_dock = {}
    for dock in docks:
        dock["appointments_by_day"] = {day["iso"]: [] for day in day_rows}
        appointments_by_dock[dock["id"]] = dock

    for appointment in appointments:
        dock = appointments_by_dock.get(appointment.get("dock_id"))
        if not dock:
            continue
        day_key = appointment.get("schedule_date_key")
        if day_key in dock["appointments_by_day"]:
            dock["appointments_by_day"][day_key].append(appointment)

    for dock in docks:
        for items in dock["appointments_by_day"].values():
            items.sort(key=lambda item: item.get("scheduled_start") or "")

    return {
        "week_start": calendar_start,
        "week_end": calendar_end - timedelta(days=1),
        "days": day_rows,
        "docks": docks,
    }


def list_available_dock_slots(
    *,
    appointment_type="inbound",
    start_date=None,
    days=DOCK_DEFAULT_LOOKAHEAD_DAYS,
    exclude_appointment_id=None,
):
    requested_type = _normalize_dock_appointment_type(appointment_type)
    calendar_start = _coerce_dock_schedule_date(start_date)
    safe_days = max(int(days or DOCK_DEFAULT_LOOKAHEAD_DAYS), 1)
    calendar_end = calendar_start + timedelta(days=safe_days)
    now_value = datetime.now().replace(second=0, microsecond=0)

    init_tms_db()
    conn = get_db()
    try:
        dock_rows = conn.execute(
            """
            SELECT *
            FROM docks
            WHERE COALESCE(active, 1) = 1
              AND dock_type IN (?, 'both')
            ORDER BY name COLLATE NOCASE ASC, id ASC
            """,
            (requested_type,),
        ).fetchall()
        docks = [_serialize_dock(row) for row in dock_rows]

        appointment_rows = conn.execute(
            """
            SELECT *
            FROM dock_appointments
            WHERE COALESCE(scheduled_start, '') != ''
              AND COALESCE(status, 'Scheduled') NOT IN ('Complete', 'No-Show')
              AND datetime(scheduled_start) < datetime(?)
              AND datetime(scheduled_end) > datetime(?)
            """,
            (
                datetime.combine(calendar_end, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.combine(calendar_start, datetime.min.time()).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        ).fetchall()
    finally:
        conn.close()

    appointments_by_dock = {}
    parsed_exclude_id = (
        _parse_optional_integer(exclude_appointment_id, "Appointment")
        if exclude_appointment_id is not None
        else None
    )
    for row in appointment_rows:
        appointment = _hydrate_dock_appointment_row(row)
        if parsed_exclude_id is not None and appointment["id"] == parsed_exclude_id:
            continue
        appointments_by_dock.setdefault(appointment["dock_id"], []).append(appointment)

    availability = []
    for offset in range(safe_days):
        day_value = calendar_start + timedelta(days=offset)
        day_entry = {
            "date": day_value,
            "iso": day_value.isoformat(),
            "label": day_value.strftime("%a %b %d"),
            "docks": [],
        }
        for dock in docks:
            duration_minutes = int(dock["default_duration_minutes"] or 60)
            slot_start = datetime.combine(day_value, datetime.min.time()) + timedelta(hours=DOCK_SLOT_START_HOUR)
            slot_end_boundary = datetime.combine(day_value, datetime.min.time()) + timedelta(hours=DOCK_SLOT_END_HOUR)
            slots = []
            while slot_start + timedelta(minutes=duration_minutes) <= slot_end_boundary:
                slot_end = slot_start + timedelta(minutes=duration_minutes)
                if slot_start > now_value:
                    conflict = None
                    for appointment in appointments_by_dock.get(dock["id"], []):
                        existing_start = _parse_tracking_datetime(appointment.get("scheduled_start"))
                        existing_end = _parse_tracking_datetime(appointment.get("scheduled_end"))
                        if not existing_start or not existing_end:
                            continue
                        if existing_start.tzinfo is not None:
                            existing_start = existing_start.astimezone(timezone.utc).replace(tzinfo=None)
                        if existing_end.tzinfo is not None:
                            existing_end = existing_end.astimezone(timezone.utc).replace(tzinfo=None)
                        if existing_start < slot_end and existing_end > slot_start:
                            conflict = appointment
                            break
                    if conflict is None:
                        slots.append(
                            {
                                "dock_id": dock["id"],
                                "dock_name": dock["name"],
                                "start_value": slot_start.strftime("%Y-%m-%dT%H:%M"),
                                "start_label": slot_start.strftime("%H:%M"),
                                "end_label": slot_end.strftime("%H:%M"),
                                "slot_label": f"{slot_start.strftime('%H:%M')} to {slot_end.strftime('%H:%M')}",
                                "duration_minutes": duration_minutes,
                            }
                        )
                slot_start += timedelta(minutes=duration_minutes)

            dock_entry = dict(dock)
            dock_entry["slots"] = slots
            dock_entry["slot_count"] = len(slots)
            day_entry["docks"].append(dock_entry)
        availability.append(day_entry)

    return availability


def list_carriers(page=1, page_size=25, search_query=""):
    init_tms_db()
    clean_query = _normalize_text(search_query)
    page = max(int(page or 1), 1)
    offset = (page - 1) * page_size
    params = []
    where_sql = ""

    if clean_query:
        like = f"%{clean_query}%"
        params.extend([like, like, like, like, like, like])
        where_sql = """
            WHERE name LIKE ?
               OR COALESCE(scac, '') LIKE ?
               OR COALESCE(dot_number, '') LIKE ?
               OR COALESCE(country, '') LIKE ?
               OR COALESCE(contact_email, '') LIKE ?
               OR COALESCE(contact_phone, '') LIKE ?
        """

    conn = get_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM tms_carriers {where_sql}",
            params,
        ).fetchone()[0]
        page_count = max(1, ceil(total / page_size)) if total else 1
        safe_page = min(page, page_count)
        rows = conn.execute(
            f"""
            SELECT *
            FROM tms_carriers
            {where_sql}
            ORDER BY active DESC, name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, (safe_page - 1) * page_size],
        ).fetchall()
        return {
            "rows": [_decorate_carrier_row(row) for row in rows],
            "total": total,
            "page": safe_page,
            "page_count": page_count,
            "page_size": page_size,
            "search_query": clean_query,
        }
    finally:
        conn.close()


def get_carrier(carrier_id):
    init_tms_db()
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (carrier_id,)).fetchone()
    finally:
        conn.close()


def get_carrier_with_history(carrier_id):
    init_tms_db()
    conn = get_db()
    try:
        carrier = conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (carrier_id,)).fetchone()
        if not carrier:
            return None, [], {
                "shipments": 0,
                "delivered": 0,
                "active": 0,
                "revenue": 0,
            }

        shipments = conn.execute(
            """
            SELECT *
            FROM shipments
            WHERE carrier_id = ?
               OR LOWER(TRIM(COALESCE(carrier_name, ''))) = LOWER(TRIM(?))
            ORDER BY COALESCE(etd, created_at) DESC, created_at DESC
            """,
            (carrier_id, carrier["name"]),
        ).fetchall()
        stats = {
            "shipments": len(shipments),
            "delivered": sum(1 for row in shipments if row["status"] == "Delivered"),
            "active": sum(1 for row in shipments if row["status"] in {"Active", "Booked", "In Transit"}),
            "revenue": sum((row["freight_rate"] or 0) for row in shipments),
        }
        return _decorate_carrier_row(carrier), shipments, stats
    finally:
        conn.close()


def save_carrier(
    carrier_id=None,
    *,
    name,
    scac="",
    dot_number="",
    mc_number="",
    contact_name="",
    country="",
    contact_email="",
    contact_phone="",
    address="",
    city="",
    state_province="",
    postal_code="",
    equipment_types="",
    service_areas="",
    insurance_company="",
    insurance_policy="",
    cargo_insurance_amount="",
    liability_amount="",
    payment_terms="NET30",
    active=1,
):
    init_tms_db()
    clean_name = _normalize_text(name)
    clean_scac = _normalize_scac(scac)
    clean_dot_number = _normalize_dot_number(dot_number)
    clean_mc_number = _normalize_text(mc_number)
    clean_contact_name = _normalize_text(contact_name)
    clean_country = _normalize_text(country)
    clean_email = _normalize_text(contact_email)
    clean_phone = _normalize_text(contact_phone)
    clean_address = _normalize_text(address)
    clean_city = _normalize_text(city)
    clean_state_province = _normalize_text(state_province)
    clean_postal_code = _normalize_text(postal_code)
    clean_equipment_types = _normalize_text(equipment_types)
    clean_service_areas = _normalize_text(service_areas)
    clean_insurance_company = _normalize_text(insurance_company)
    clean_insurance_policy = _normalize_text(insurance_policy)
    clean_cargo_insurance_amount = _parse_nullable_number(cargo_insurance_amount, "Cargo insurance amount")
    clean_liability_amount = _parse_nullable_number(liability_amount, "Liability amount")
    clean_payment_terms = _normalize_choice(
        payment_terms,
        ("NET30", "NET15", "NET60", "QUICK PAY"),
        "Payment terms",
        "NET30",
    )
    active_value = 1 if str(active).strip() not in {"0", "false", "False", ""} else 0

    if not clean_name:
        raise ValueError("Carrier name is required.")

    conn = get_db()
    try:
        duplicate_name = conn.execute(
            """
            SELECT id FROM tms_carriers
            WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))
              AND id != ?
            """,
            (clean_name, carrier_id or 0),
        ).fetchone()
        if duplicate_name:
            raise ValueError("A carrier with that name already exists.")

        if clean_scac:
            duplicate_scac = conn.execute(
                """
                SELECT id FROM tms_carriers
                WHERE UPPER(COALESCE(scac, '')) = ?
                  AND id != ?
                """,
                (clean_scac, carrier_id or 0),
            ).fetchone()
            if duplicate_scac:
                raise ValueError("That SCAC is already assigned to another carrier.")

        if clean_dot_number:
            duplicate_dot = conn.execute(
                """
                SELECT id FROM tms_carriers
                WHERE COALESCE(dot_number, '') = ?
                  AND id != ?
                """,
                (clean_dot_number, carrier_id or 0),
            ).fetchone()
            if duplicate_dot:
                raise ValueError("That DOT number is already assigned to another carrier.")

        if carrier_id:
            existing = conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (carrier_id,)).fetchone()
            if not existing:
                raise ValueError("Carrier not found.")
            conn.execute(
                """
                UPDATE tms_carriers
                SET name = ?, scac = ?, dot_number = ?, mc_number = ?, contact_name = ?, country = ?,
                    contact_email = ?, contact_phone = ?, address = ?, city = ?, state_province = ?,
                    postal_code = ?, equipment_types = ?, service_areas = ?, insurance_company = ?,
                    insurance_policy = ?, cargo_insurance_amount = ?, liability_amount = ?,
                    payment_terms = ?, active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    clean_name,
                    clean_scac,
                    clean_dot_number,
                    clean_mc_number,
                    clean_contact_name,
                    clean_country,
                    clean_email,
                    clean_phone,
                    clean_address,
                    clean_city,
                    clean_state_province,
                    clean_postal_code,
                    clean_equipment_types,
                    clean_service_areas,
                    clean_insurance_company,
                    clean_insurance_policy,
                    clean_cargo_insurance_amount,
                    clean_liability_amount,
                    clean_payment_terms,
                    active_value,
                    carrier_id,
                ),
            )
            conn.execute(
                "UPDATE shipments SET carrier_name = ? WHERE carrier_id = ?",
                (clean_name, carrier_id),
            )
            saved_id = carrier_id
        else:
            cursor = conn.execute(
                """
                INSERT INTO tms_carriers
                    (
                        name, scac, dot_number, mc_number, contact_name, country, contact_email,
                        contact_phone, address, city, state_province, postal_code, equipment_types,
                        service_areas, insurance_company, insurance_policy, cargo_insurance_amount,
                        liability_amount, payment_terms, active, updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    clean_name,
                    clean_scac,
                    clean_dot_number,
                    clean_mc_number,
                    clean_contact_name,
                    clean_country,
                    clean_email,
                    clean_phone,
                    clean_address,
                    clean_city,
                    clean_state_province,
                    clean_postal_code,
                    clean_equipment_types,
                    clean_service_areas,
                    clean_insurance_company,
                    clean_insurance_policy,
                    clean_cargo_insurance_amount,
                    clean_liability_amount,
                    clean_payment_terms,
                    active_value,
                ),
            )
            saved_id = cursor.lastrowid

        if not clean_dot_number:
            conn.execute(
                """
                UPDATE tms_carriers
                SET safety_rating = '', insurance_status = '', auth_status = '',
                    insurance_expires_at = NULL, last_checked = NULL, fmcsa_source_url = ''
                WHERE id = ?
                """,
                (saved_id,),
            )

        conn.commit()
    finally:
        conn.close()

    if clean_dot_number:
        try:
            refresh_carrier_safety(saved_id)
        except Exception as exc:
            print(f"[FMCSA] Carrier {saved_id} refresh skipped: {exc}")
    return saved_id


def delete_carrier(carrier_id):
    init_tms_db()
    conn = get_db()
    try:
        carrier = conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (carrier_id,)).fetchone()
        if not carrier:
            raise ValueError("Carrier not found.")

        tender_count = conn.execute(
            "SELECT COUNT(*) FROM tender_responses WHERE carrier_id = ?",
            (carrier_id,),
        ).fetchone()[0]
        if tender_count:
            raise ValueError("This carrier has tender history and cannot be deleted.")

        claim_count = conn.execute(
            "SELECT COUNT(*) FROM freight_claims WHERE carrier_id = ?",
            (carrier_id,),
        ).fetchone()[0]
        if claim_count:
            raise ValueError("This carrier has claim history and cannot be deleted.")

        conn.execute("UPDATE shipments SET carrier_id = NULL WHERE carrier_id = ?", (carrier_id,))
        conn.execute("DELETE FROM tms_carriers WHERE id = ?", (carrier_id,))
        conn.commit()
        return carrier["name"]
    finally:
        conn.close()


def _build_duty_log_row(row):
    duty_log = dict(row)
    duty_log["start_time_display"] = _format_tracking_datetime(duty_log.get("start_time"))
    duty_log["end_time_display"] = _format_tracking_datetime(duty_log.get("end_time"))
    duty_log["start_time_input"] = _format_datetime_input(duty_log.get("start_time"))
    duty_log["end_time_input"] = _format_datetime_input(duty_log.get("end_time"))
    duty_log["hours_logged"] = round(float(duty_log.get("hours_logged") or 0), 2)
    duty_log["status_class"] = {
        "Driving": "warning",
        "On Duty": "primary",
        "Off Duty": "secondary",
        "Sleeper": "info",
    }.get(duty_log.get("duty_status"), "secondary")
    return duty_log


def list_drivers(conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
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
                ) AS active_truck_number,
                (
                    SELECT MAX(COALESCE(dl.end_time, dl.start_time))
                    FROM duty_logs dl
                    WHERE dl.driver_id = d.id
                ) AS last_duty_at
            FROM drivers d
            ORDER BY
                CASE d.status
                    WHEN 'On Trip' THEN 0
                    WHEN 'Active' THEN 1
                    ELSE 2
                END,
                d.name COLLATE NOCASE ASC,
                d.id DESC
            """
        ).fetchall()
    finally:
        if should_close:
            conn.close()


def get_driver(driver_id, conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        return conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
    finally:
        if should_close:
            conn.close()


def get_driver_with_history(driver_id, conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        driver = get_driver(driver_id, conn=conn)
        if not driver:
            return None, [], [], {"shipments": 0, "active_shipments": 0, "driving_hours": 0.0, "alerts": 0}

        shipments = conn.execute(
            """
            SELECT s.*, v.truck_number, v.vehicle_type
            FROM shipments s
            LEFT JOIN vehicles v ON v.id = s.vehicle_id
            WHERE s.driver_id = ?
            ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
            """,
            (driver_id,),
        ).fetchall()
        duty_logs = [
            _build_duty_log_row(row)
            for row in conn.execute(
                """
                SELECT dl.*, s.shipment_ref
                FROM duty_logs dl
                LEFT JOIN shipments s ON s.id = dl.shipment_id
                WHERE dl.driver_id = ?
                ORDER BY COALESCE(dl.end_time, dl.start_time) DESC, dl.id DESC
                LIMIT 25
                """,
                (driver_id,),
            ).fetchall()
        ]
        stats = {
            "shipments": len(shipments),
            "active_shipments": sum(1 for row in shipments if row["status"] not in {"Delivered", "Cancelled"}),
            "driving_hours": round(
                sum(log["hours_logged"] for log in duty_logs if log["duty_status"] == "Driving"),
                2,
            ),
            "alerts": sum(1 for log in duty_logs if log["exceeds_driving_limit"]),
        }
        return driver, shipments, duty_logs, stats
    finally:
        if should_close:
            conn.close()


def save_driver(
    driver_id=None,
    *,
    name,
    license_number,
    phone="",
    country="",
    cdl_class="",
    cdl_expiry="",
    medical_card_expiry="",
    drug_test_date="",
    hire_date="",
    emergency_contact_name="",
    emergency_contact_phone="",
    hazmat_endorsement=0,
    twic_card=0,
    license_state="",
    email="",
    status="Active",
):
    init_tms_db()
    clean_name = _normalize_text(name)
    clean_license = _normalize_text(license_number).upper()
    clean_phone = _normalize_text(phone)
    clean_country = _normalize_text(country)
    clean_cdl_class = _normalize_text(cdl_class)
    clean_cdl_expiry = _normalize_text(cdl_expiry)
    clean_medical_card_expiry = _normalize_text(medical_card_expiry)
    clean_drug_test_date = _normalize_text(drug_test_date)
    clean_hire_date = _normalize_text(hire_date)
    clean_emergency_contact_name = _normalize_text(emergency_contact_name)
    clean_emergency_contact_phone = _normalize_text(emergency_contact_phone)
    hazmat_endorsement_value = 1 if str(hazmat_endorsement).strip() not in {"0", "false", "False", ""} else 0
    twic_card_value = 1 if str(twic_card).strip() not in {"0", "false", "False", ""} else 0
    clean_license_state = _normalize_text(license_state)
    clean_email = _normalize_text(email)
    clean_status = _normalize_driver_status(status)

    if not clean_name:
        raise ValueError("Driver name is required.")
    if not clean_license:
        raise ValueError("License number is required.")

    conn = get_db()
    try:
        duplicate_license = conn.execute(
            """
            SELECT id
            FROM drivers
            WHERE UPPER(TRIM(license_number)) = ?
              AND id != ?
            """,
            (clean_license, driver_id or 0),
        ).fetchone()
        if duplicate_license:
            raise ValueError("That license number is already assigned to another driver.")

        if driver_id:
            existing = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
            if not existing:
                raise ValueError("Driver not found.")
            conn.execute(
                """
                UPDATE drivers
                SET name = ?, license_number = ?, phone = ?, country = ?, cdl_class = ?, cdl_expiry = ?,
                    medical_card_expiry = ?, drug_test_date = ?, hire_date = ?, emergency_contact_name = ?,
                    emergency_contact_phone = ?, hazmat_endorsement = ?, twic_card = ?, license_state = ?,
                    email = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    clean_name,
                    clean_license,
                    clean_phone,
                    clean_country,
                    clean_cdl_class,
                    clean_cdl_expiry,
                    clean_medical_card_expiry,
                    clean_drug_test_date,
                    clean_hire_date,
                    clean_emergency_contact_name,
                    clean_emergency_contact_phone,
                    hazmat_endorsement_value,
                    twic_card_value,
                    clean_license_state,
                    clean_email,
                    clean_status,
                    driver_id,
                ),
            )
            saved_id = driver_id
        else:
            cursor = conn.execute(
                """
                INSERT INTO drivers
                    (
                        name, license_number, phone, country, cdl_class, cdl_expiry,
                        medical_card_expiry, drug_test_date, hire_date, emergency_contact_name,
                        emergency_contact_phone, hazmat_endorsement, twic_card, license_state,
                        email, status, checkin_token, updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    clean_name,
                    clean_license,
                    clean_phone,
                    clean_country,
                    clean_cdl_class,
                    clean_cdl_expiry,
                    clean_medical_card_expiry,
                    clean_drug_test_date,
                    clean_hire_date,
                    clean_emergency_contact_name,
                    clean_emergency_contact_phone,
                    hazmat_endorsement_value,
                    twic_card_value,
                    clean_license_state,
                    clean_email,
                    clean_status,
                    _generate_driver_token(conn),
                ),
            )
            saved_id = cursor.lastrowid

        conn.commit()
        return saved_id
    finally:
        conn.close()


def delete_driver(driver_id):
    init_tms_db()
    conn = get_db()
    try:
        driver = conn.execute("SELECT * FROM drivers WHERE id = ?", (driver_id,)).fetchone()
        if not driver:
            raise ValueError("Driver not found.")

        conn.execute("UPDATE shipments SET driver_id = NULL WHERE driver_id = ?", (driver_id,))
        conn.execute("DELETE FROM drivers WHERE id = ?", (driver_id,))
        conn.commit()
        return driver["name"]
    finally:
        conn.close()


def list_vehicles(conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        return conn.execute(
            """
            SELECT
                v.*,
                (
                    SELECT s.shipment_ref
                    FROM shipments s
                    WHERE s.vehicle_id = v.id
                      AND s.status NOT IN ('Delivered', 'Cancelled')
                    ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
                    LIMIT 1
                ) AS active_shipment_ref,
                (
                    SELECT d.name
                    FROM shipments s
                    JOIN drivers d ON d.id = s.driver_id
                    WHERE s.vehicle_id = v.id
                      AND s.status NOT IN ('Delivered', 'Cancelled')
                    ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
                    LIMIT 1
                ) AS active_driver_name
            FROM vehicles v
            ORDER BY
                CASE v.status
                    WHEN 'On Trip' THEN 0
                    WHEN 'Active' THEN 1
                    WHEN 'Maintenance' THEN 2
                    ELSE 3
                END,
                v.truck_number COLLATE NOCASE ASC,
                v.id DESC
            """
        ).fetchall()
    finally:
        if should_close:
            conn.close()


def get_vehicle(vehicle_id, conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        return conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    finally:
        if should_close:
            conn.close()


def get_vehicle_with_history(vehicle_id, conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        vehicle = get_vehicle(vehicle_id, conn=conn)
        if not vehicle:
            return None, [], {"shipments": 0, "active_shipments": 0, "total_weight": 0.0, "total_cbm": 0.0}

        shipments = conn.execute(
            """
            SELECT s.*, d.name AS driver_name, d.phone AS driver_phone
            FROM shipments s
            LEFT JOIN drivers d ON d.id = s.driver_id
            WHERE s.vehicle_id = ?
            ORDER BY COALESCE(s.etd, s.created_at) DESC, s.id DESC
            """,
            (vehicle_id,),
        ).fetchall()
        stats = {
            "shipments": len(shipments),
            "active_shipments": sum(1 for row in shipments if row["status"] not in {"Delivered", "Cancelled"}),
            "total_weight": round(sum((row["weight_kg"] or 0) for row in shipments), 2),
            "total_cbm": round(sum((row["volume_cbm"] or 0) for row in shipments), 2),
        }
        return vehicle, shipments, stats
    finally:
        if should_close:
            conn.close()


def save_vehicle(
    vehicle_id=None,
    *,
    truck_number,
    vin="",
    license_plate="",
    year="",
    make="",
    model="",
    vehicle_type,
    capacity_weight="",
    capacity_cbm="",
    country="",
    registration_expiry="",
    insurance_expiry="",
    insurance_carrier="",
    odometer="",
    last_inspection_date="",
    next_inspection_due="",
    status="Active",
):
    init_tms_db()
    clean_truck_number = _normalize_text(truck_number).upper()
    clean_vin = _normalize_text(vin).upper()
    clean_license_plate = _normalize_text(license_plate).upper()
    clean_year = _parse_optional_integer(year, "Year")
    clean_make = _normalize_text(make)
    clean_model = _normalize_text(model)
    clean_vehicle_type = _normalize_text(vehicle_type)
    clean_country = _normalize_text(country)
    clean_registration_expiry = _parse_nullable_iso_date(registration_expiry, "Registration expiry")
    clean_insurance_expiry = _parse_nullable_iso_date(insurance_expiry, "Insurance expiry")
    clean_insurance_carrier = _normalize_text(insurance_carrier)
    clean_odometer = _parse_nullable_number(odometer, "Odometer")
    clean_last_inspection_date = _parse_nullable_iso_date(last_inspection_date, "Last inspection date")
    clean_next_inspection_due = _parse_nullable_iso_date(next_inspection_due, "Next inspection due")
    clean_status = _normalize_vehicle_status(status)
    clean_capacity_weight = _parse_non_negative_number(capacity_weight, "Capacity weight")
    clean_capacity_cbm = _parse_non_negative_number(capacity_cbm, "Capacity CBM")

    if not clean_truck_number:
        raise ValueError("Truck number is required.")
    if not clean_vehicle_type:
        raise ValueError("Vehicle type is required.")

    conn = get_db()
    try:
        duplicate_truck = conn.execute(
            """
            SELECT id
            FROM vehicles
            WHERE UPPER(TRIM(truck_number)) = ?
              AND id != ?
            """,
            (clean_truck_number, vehicle_id or 0),
        ).fetchone()
        if duplicate_truck:
            raise ValueError("That truck number is already assigned to another vehicle.")

        if vehicle_id:
            existing = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
            if not existing:
                raise ValueError("Vehicle not found.")
            conn.execute(
                """
                UPDATE vehicles
                SET truck_number = ?, vehicle_type = ?, capacity_weight = ?, capacity_cbm = ?,
                    country = ?, status = ?, vin = ?, license_plate = ?, year = ?, make = ?,
                    model = ?, registration_expiry = ?, insurance_expiry = ?, insurance_carrier = ?,
                    odometer = ?, last_inspection_date = ?, next_inspection_due = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    clean_truck_number,
                    clean_vehicle_type,
                    clean_capacity_weight,
                    clean_capacity_cbm,
                    clean_country,
                    clean_status,
                    clean_vin,
                    clean_license_plate,
                    clean_year,
                    clean_make,
                    clean_model,
                    clean_registration_expiry,
                    clean_insurance_expiry,
                    clean_insurance_carrier,
                    clean_odometer,
                    clean_last_inspection_date,
                    clean_next_inspection_due,
                    vehicle_id,
                ),
            )
            saved_id = vehicle_id
        else:
            cursor = conn.execute(
                """
                INSERT INTO vehicles
                    (
                        truck_number, vehicle_type, capacity_weight, capacity_cbm, country, status,
                        vin, license_plate, year, make, model, registration_expiry,
                        insurance_expiry, insurance_carrier, odometer, last_inspection_date,
                        next_inspection_due, updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    clean_truck_number,
                    clean_vehicle_type,
                    clean_capacity_weight,
                    clean_capacity_cbm,
                    clean_country,
                    clean_status,
                    clean_vin,
                    clean_license_plate,
                    clean_year,
                    clean_make,
                    clean_model,
                    clean_registration_expiry,
                    clean_insurance_expiry,
                    clean_insurance_carrier,
                    clean_odometer,
                    clean_last_inspection_date,
                    clean_next_inspection_due,
                ),
            )
            saved_id = cursor.lastrowid

        conn.commit()
        return saved_id
    finally:
        conn.close()


def delete_vehicle(vehicle_id):
    init_tms_db()
    conn = get_db()
    try:
        vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        if not vehicle:
            raise ValueError("Vehicle not found.")

        conn.execute("UPDATE shipments SET vehicle_id = NULL WHERE vehicle_id = ?", (vehicle_id,))
        conn.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
        conn.commit()
        return vehicle["truck_number"]
    finally:
        conn.close()


def save_duty_log(
    *,
    driver_id,
    duty_status,
    start_time,
    end_time,
    shipment_id=None,
    location="",
    notes="",
    conn=None,
):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()

    clean_status = _normalize_duty_status(duty_status)
    clean_location = _normalize_text(location)
    clean_notes = _normalize_text(notes)
    start_dt = _parse_datetime_value(start_time, "Duty start")
    end_dt = _parse_datetime_value(end_time, "Duty end")
    if end_dt <= start_dt:
        raise ValueError("Duty end must be after the duty start time.")

    hours_logged = round((end_dt - start_dt).total_seconds() / 3600, 2)
    exceeds_driving_limit = 1 if clean_status == "Driving" and hours_logged > 11 else 0

    try:
        driver = conn.execute("SELECT id FROM drivers WHERE id = ?", (driver_id,)).fetchone()
        if not driver:
            raise ValueError("Driver not found.")

        if shipment_id:
            shipment = conn.execute("SELECT id FROM shipments WHERE id = ?", (shipment_id,)).fetchone()
            if not shipment:
                raise ValueError("Shipment not found for this duty log.")

        cursor = conn.execute(
            """
            INSERT INTO duty_logs
                (driver_id, shipment_id, duty_status, start_time, end_time, hours_logged,
                 exceeds_driving_limit, location, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                driver_id,
                shipment_id,
                clean_status,
                start_dt.isoformat(timespec="minutes"),
                end_dt.isoformat(timespec="minutes"),
                hours_logged,
                exceeds_driving_limit,
                clean_location,
                clean_notes,
            ),
        )
        log_row = conn.execute("SELECT * FROM duty_logs WHERE id = ?", (cursor.lastrowid,)).fetchone()
        if should_close:
            conn.commit()
        return _build_duty_log_row(log_row)
    finally:
        if should_close:
            conn.close()


def get_driver_checkin_context(token):
    init_tms_db()
    clean_token = _normalize_text(token)
    if not clean_token:
        return None

    conn = get_db()
    try:
        driver = conn.execute(
            "SELECT * FROM drivers WHERE checkin_token = ?",
            (clean_token,),
        ).fetchone()
        if not driver:
            return None

        shipment = conn.execute(
            """
            SELECT s.*, v.truck_number, v.vehicle_type
            FROM shipments s
            LEFT JOIN vehicles v ON v.id = s.vehicle_id
            WHERE s.driver_id = ?
            ORDER BY
                CASE
                    WHEN s.status IN ('Delivered', 'Cancelled') THEN 1
                    ELSE 0
                END,
                COALESCE(s.etd, s.created_at) DESC,
                s.id DESC
            LIMIT 1
            """,
            (driver["id"],),
        ).fetchone()
        duty_logs = [
            _build_duty_log_row(row)
            for row in conn.execute(
                """
                SELECT dl.*, s.shipment_ref
                FROM duty_logs dl
                LEFT JOIN shipments s ON s.id = dl.shipment_id
                WHERE dl.driver_id = ?
                ORDER BY COALESCE(dl.end_time, dl.start_time) DESC, dl.id DESC
                LIMIT 8
                """,
                (driver["id"],),
            ).fetchall()
        ]
        return {
            "driver": dict(driver),
            "shipment": dict(shipment) if shipment else None,
            "duty_logs": duty_logs,
        }
    finally:
        conn.close()


def submit_driver_checkin(
    token,
    *,
    status,
    location="",
    issue="",
    duty_status="",
    duty_start="",
    duty_end="",
):
    init_tms_db()
    clean_token = _normalize_text(token)
    clean_location = _normalize_text(location)
    clean_issue = _normalize_text(issue)
    duty_fields_present = any(_normalize_text(value) for value in (duty_status, duty_start, duty_end))

    conn = get_db()
    try:
        driver = conn.execute(
            "SELECT * FROM drivers WHERE checkin_token = ?",
            (clean_token,),
        ).fetchone()
        if not driver:
            raise ValueError("Driver check-in link was not found.")

        clean_status = _normalize_driver_status(status or driver["status"])
        shipment = conn.execute(
            """
            SELECT *
            FROM shipments
            WHERE driver_id = ?
            ORDER BY
                CASE
                    WHEN status IN ('Delivered', 'Cancelled') THEN 1
                    ELSE 0
                END,
                COALESCE(etd, created_at) DESC,
                id DESC
            LIMIT 1
            """,
            (driver["id"],),
        ).fetchone()

        conn.execute(
            """
            UPDATE drivers
            SET status = ?, last_location = ?, last_issue = ?, last_checkin_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (clean_status, clean_location, clean_issue, driver["id"]),
        )

        if shipment and (clean_location or clean_status != driver["status"]):
            description = f"{driver['name']} checked in"
            if clean_location:
                description += f" from {clean_location}"
            description += f" with status {clean_status}"
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description, location, created_by)
                VALUES (?, 'Driver Check-In', ?, ?, 'driver')
                """,
                (shipment["id"], description, clean_location or None),
            )

        if shipment and clean_issue:
            conn.execute(
                """
                INSERT INTO shipment_events (shipment_id, event_type, description, location, created_by)
                VALUES (?, 'Driver Issue', ?, ?, 'driver')
                """,
                (
                    shipment["id"],
                    f"{driver['name']} reported an issue: {clean_issue}",
                    clean_location or None,
                ),
            )

        duty_log = None
        if duty_fields_present:
            if not (_normalize_text(duty_start) and _normalize_text(duty_end)):
                raise ValueError("Duty start and end are required to save a duty log.")
            duty_log = save_duty_log(
                driver_id=driver["id"],
                shipment_id=shipment["id"] if shipment else None,
                duty_status=duty_status or "Driving",
                start_time=duty_start,
                end_time=duty_end,
                location=clean_location,
                notes=clean_issue,
                conn=conn,
            )
            if shipment and duty_log["exceeds_driving_limit"]:
                conn.execute(
                    """
                    INSERT INTO shipment_events (shipment_id, event_type, description, location, created_by)
                    VALUES (?, 'HOS Alert', ?, ?, 'system')
                    """,
                    (
                        shipment["id"],
                        f"{driver['name']} logged {duty_log['hours_logged']:.2f} hours driving.",
                        clean_location or None,
                    ),
                )

        conn.commit()
        return {
            "driver_id": driver["id"],
            "shipment_ref": shipment["shipment_ref"] if shipment else "",
            "duty_log": duty_log,
            "status": clean_status,
            "issue": clean_issue,
            "location": clean_location,
        }
    finally:
        conn.close()


def list_contract_rates(search_query="", conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    clean_query = _normalize_text(search_query)
    params = []
    where_sql = ""
    if clean_query:
        like = f"%{clean_query}%"
        params.extend([like, like, like, like])
        where_sql = """
            WHERE origin LIKE ?
               OR destination LIKE ?
               OR mode LIKE ?
               OR currency LIKE ?
        """

    try:
        rows = conn.execute(
            f"""
            SELECT *
            FROM contract_rates
            {where_sql}
            ORDER BY
                CASE
                    WHEN date('now') BETWEEN date(valid_from) AND date(valid_to) THEN 0
                    WHEN date(valid_from) > date('now') THEN 1
                    ELSE 2
                END,
                date(valid_from) ASC,
                date(valid_to) ASC,
                updated_at DESC,
                id DESC
            """,
            params,
        ).fetchall()
        return [_build_contract_rate_row(row) for row in rows]
    finally:
        if should_close:
            conn.close()


def get_contract_rate(rate_id, conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        row = conn.execute("SELECT * FROM contract_rates WHERE id = ?", (rate_id,)).fetchone()
        return _build_contract_rate_row(row) if row else None
    finally:
        if should_close:
            conn.close()


def save_contract_rate(
    *,
    origin,
    destination,
    mode,
    rate_20ft="",
    rate_40ft="",
    rate_40hc="",
    currency="USD",
    valid_from,
    valid_to,
    rate_id=None,
    conn=None,
):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()

    clean_origin = _normalize_lane_value(origin)
    clean_destination = _normalize_lane_value(destination)
    clean_mode = _normalize_mode(mode)
    clean_currency = _normalize_currency(currency)
    amount_20ft = _parse_optional_amount(rate_20ft, "20ft rate")
    amount_40ft = _parse_optional_amount(rate_40ft, "40ft rate")
    amount_40hc = _parse_optional_amount(rate_40hc, "40HC rate")
    start_date = _parse_iso_date(valid_from, "Valid from")
    end_date = _parse_iso_date(valid_to, "Valid to")

    if not clean_origin:
        raise ValueError("Origin is required.")
    if not clean_destination:
        raise ValueError("Destination is required.")
    if not clean_mode:
        raise ValueError("Mode is required.")
    if all(rate is None for rate in (amount_20ft, amount_40ft, amount_40hc)):
        raise ValueError("Enter at least one contract rate.")
    if end_date < start_date:
        raise ValueError("Valid to must be on or after valid from.")

    try:
        duplicate = conn.execute(
            """
            SELECT id
            FROM contract_rates
            WHERE LOWER(origin) = LOWER(?)
              AND LOWER(destination) = LOWER(?)
              AND LOWER(mode) = LOWER(?)
              AND date(valid_from) = date(?)
              AND date(valid_to) = date(?)
              AND id != ?
            """,
            (
                clean_origin,
                clean_destination,
                clean_mode,
                start_date.isoformat(),
                end_date.isoformat(),
                rate_id or 0,
            ),
        ).fetchone()
        if duplicate:
            raise ValueError("A contract already exists for that lane, mode, and validity window.")

        if rate_id:
            existing = conn.execute("SELECT id FROM contract_rates WHERE id = ?", (rate_id,)).fetchone()
            if not existing:
                raise ValueError("Contract rate not found.")
            conn.execute(
                """
                UPDATE contract_rates
                SET origin = ?, destination = ?, mode = ?,
                    rate_20ft = ?, rate_40ft = ?, rate_40hc = ?,
                    currency = ?, valid_from = ?, valid_to = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    clean_origin,
                    clean_destination,
                    clean_mode,
                    amount_20ft,
                    amount_40ft,
                    amount_40hc,
                    clean_currency,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    rate_id,
                ),
            )
            saved_id = rate_id
        else:
            cursor = conn.execute(
                """
                INSERT INTO contract_rates
                    (origin, destination, mode, rate_20ft, rate_40ft, rate_40hc, currency, valid_from, valid_to, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    clean_origin,
                    clean_destination,
                    clean_mode,
                    amount_20ft,
                    amount_40ft,
                    amount_40hc,
                    clean_currency,
                    start_date.isoformat(),
                    end_date.isoformat(),
                ),
            )
            saved_id = cursor.lastrowid

        if should_close:
            conn.commit()
        row = conn.execute("SELECT * FROM contract_rates WHERE id = ?", (saved_id,)).fetchone()
        return _build_contract_rate_row(row)
    finally:
        if should_close:
            conn.close()


def delete_contract_rate(rate_id, conn=None):
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()
    try:
        contract_rate = conn.execute("SELECT * FROM contract_rates WHERE id = ?", (rate_id,)).fetchone()
        if not contract_rate:
            raise ValueError("Contract rate not found.")

        conn.execute("UPDATE shipments SET contract_rate_id = NULL WHERE contract_rate_id = ?", (rate_id,))
        conn.execute("DELETE FROM contract_rates WHERE id = ?", (rate_id,))
        if should_close:
            conn.commit()
        return _build_contract_rate_row(contract_rate)
    finally:
        if should_close:
            conn.close()


def find_best_contract_rate(
    *,
    origin,
    destination,
    mode,
    containers="",
    reference_date=None,
    conn=None,
):
    clean_origin = _normalize_lane_value(origin)
    clean_destination = _normalize_lane_value(destination)
    clean_mode = _normalize_mode(mode)
    if not clean_origin or not clean_destination or not clean_mode:
        return None

    lookup_date = _coerce_lookup_date(reference_date)
    should_close = conn is None
    if should_close:
        init_tms_db()
    conn = conn or get_db()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM contract_rates
            WHERE LOWER(origin) = LOWER(?)
              AND LOWER(destination) = LOWER(?)
              AND LOWER(mode) = LOWER(?)
              AND date(valid_from) <= date(?)
              AND date(valid_to) >= date(?)
            ORDER BY date(valid_to) ASC, updated_at DESC, id DESC
            """,
            (
                clean_origin,
                clean_destination,
                clean_mode,
                lookup_date.isoformat(),
                lookup_date.isoformat(),
            ),
        ).fetchall()

        best_match = None
        for row in rows:
            candidate = _build_contract_rate_row(row, containers=containers, reference_date=lookup_date)
            if candidate["matched_rate"] is None:
                continue
            if best_match is None or candidate["matched_rate"] < best_match["matched_rate"]:
                best_match = candidate
        return best_match
    finally:
        if should_close:
            conn.close()


def import_carriers_from_contacts_db():
    init_tms_db()
    if not os.path.exists(CONTACTS_DB):
        raise FileNotFoundError(f"Contacts database not found at {CONTACTS_DB}")

    conn = get_db()
    try:
        conn.execute("ATTACH DATABASE ? AS contacts_source", (CONTACTS_DB,))
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM contacts_source.sqlite_master WHERE type = 'table'").fetchall()
        }
        if "contacts" not in tables:
            raise ValueError("The contacts database does not contain a contacts table.")
        source_columns = {
            row["name"]
            for row in conn.execute("PRAGMA contacts_source.table_info(contacts)").fetchall()
        }
        dot_expr = (
            "COALESCE(MAX(NULLIF(TRIM(dot_number), '')), '')"
            if "dot_number" in source_columns
            else "''"
        )
        safety_expr = (
            "COALESCE(MAX(NULLIF(TRIM(safety_rating), '')), '')"
            if "safety_rating" in source_columns
            else "''"
        )

        conn.execute("DROP TABLE IF EXISTS temp.contact_import_source")
        conn.execute(
            """
            CREATE TEMP TABLE contact_import_source (
                name_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dot_number TEXT DEFAULT '',
                safety_rating TEXT DEFAULT '',
                country TEXT DEFAULT '',
                contact_email TEXT DEFAULT '',
                contact_phone TEXT DEFAULT ''
            )
            """
        )
        conn.execute(
            f"""
            INSERT INTO contact_import_source (name_key, name, dot_number, safety_rating, country, contact_email, contact_phone)
            SELECT
                LOWER(TRIM(company_name)) AS name_key,
                MIN(TRIM(company_name)) AS name,
                {dot_expr} AS dot_number,
                {safety_expr} AS safety_rating,
                COALESCE(MAX(NULLIF(TRIM(country), '')), '') AS country,
                COALESCE(MAX(NULLIF(TRIM(email), '')), '') AS contact_email,
                COALESCE(MAX(NULLIF(TRIM(phone_number), '')), '') AS contact_phone
            FROM contacts_source.contacts
            WHERE company_name IS NOT NULL
              AND TRIM(company_name) != ''
            GROUP BY LOWER(TRIM(company_name))
            """
        )

        inserted = conn.execute(
            """
            SELECT COUNT(*)
            FROM contact_import_source src
            WHERE NOT EXISTS (
                SELECT 1
                FROM tms_carriers carrier
                WHERE LOWER(TRIM(carrier.name)) = src.name_key
            )
            """
        ).fetchone()[0]

        updated = conn.execute(
            """
            SELECT COUNT(*)
            FROM tms_carriers carrier
            JOIN contact_import_source src
              ON LOWER(TRIM(carrier.name)) = src.name_key
            WHERE (COALESCE(TRIM(carrier.dot_number), '') = '' AND COALESCE(TRIM(src.dot_number), '') != '')
               OR (COALESCE(TRIM(carrier.safety_rating), '') = '' AND COALESCE(TRIM(src.safety_rating), '') != '')
               OR (COALESCE(TRIM(carrier.country), '') = '' AND COALESCE(TRIM(src.country), '') != '')
               OR (COALESCE(TRIM(carrier.contact_email), '') = '' AND COALESCE(TRIM(src.contact_email), '') != '')
               OR (COALESCE(TRIM(carrier.contact_phone), '') = '' AND COALESCE(TRIM(src.contact_phone), '') != '')
            """
        ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO tms_carriers
                (name, scac, dot_number, safety_rating, country, contact_email, contact_phone, active, created_at, updated_at)
            SELECT
                src.name,
                NULL,
                NULLIF(src.dot_number, ''),
                src.safety_rating,
                src.country,
                src.contact_email,
                src.contact_phone,
                1,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM contact_import_source src
            WHERE NOT EXISTS (
                SELECT 1
                FROM tms_carriers carrier
                WHERE LOWER(TRIM(carrier.name)) = src.name_key
            )
            """
        )

        conn.execute(
            """
            UPDATE tms_carriers
            SET dot_number = CASE
                    WHEN COALESCE(TRIM(dot_number), '') = ''
                    THEN COALESCE(
                        (SELECT src.dot_number FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))),
                        ''
                    )
                    ELSE dot_number
                END,
                safety_rating = CASE
                    WHEN COALESCE(TRIM(safety_rating), '') = ''
                    THEN COALESCE(
                        (SELECT src.safety_rating FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))),
                        ''
                    )
                    ELSE safety_rating
                END,
                country = CASE
                    WHEN COALESCE(TRIM(country), '') = ''
                    THEN COALESCE(
                        (SELECT src.country FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))),
                        ''
                    )
                    ELSE country
                END,
                contact_email = CASE
                    WHEN COALESCE(TRIM(contact_email), '') = ''
                    THEN COALESCE(
                        (SELECT src.contact_email FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))),
                        ''
                    )
                    ELSE contact_email
                END,
                contact_phone = CASE
                    WHEN COALESCE(TRIM(contact_phone), '') = ''
                    THEN COALESCE(
                        (SELECT src.contact_phone FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))),
                        ''
                    )
                    ELSE contact_phone
                END,
                updated_at = CASE
                    WHEN (COALESCE(TRIM(dot_number), '') = '' AND COALESCE((SELECT src.dot_number FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))), '') != '')
                      OR (COALESCE(TRIM(safety_rating), '') = '' AND COALESCE((SELECT src.safety_rating FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))), '') != '')
                      OR (COALESCE(TRIM(country), '') = '' AND COALESCE((SELECT src.country FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))), '') != '')
                      OR (COALESCE(TRIM(contact_email), '') = '' AND COALESCE((SELECT src.contact_email FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))), '') != '')
                      OR (COALESCE(TRIM(contact_phone), '') = '' AND COALESCE((SELECT src.contact_phone FROM contact_import_source src WHERE src.name_key = LOWER(TRIM(tms_carriers.name))), '') != '')
                    THEN CURRENT_TIMESTAMP
                    ELSE updated_at
                END
            WHERE LOWER(TRIM(name)) IN (SELECT name_key FROM contact_import_source)
            """
        )

        source_total = conn.execute("SELECT COUNT(*) FROM contact_import_source").fetchone()[0]
        conn.commit()
        return {
            "inserted": inserted,
            "updated": updated,
            "source_total": source_total,
        }
    finally:
        try:
            conn.execute("DETACH DATABASE contacts_source")
        except sqlite3.Error:
            pass
        conn.close()


# ---------------------------------------------------------------------------
# LTL / FTL Load Builder
# ---------------------------------------------------------------------------

EQUIPMENT_TYPES = {
    # Van & temp-control
    "dry_van":           {"label": "Dry Van",           "max_lbs": 44000, "icon": "bi-truck",             "group": "Van"},
    "reefer":            {"label": "Reefer",             "max_lbs": 42500, "icon": "bi-thermometer-snow",  "group": "Van"},
    "box_truck":         {"label": "Box Truck",          "max_lbs": 26000, "icon": "bi-truck-front",       "group": "Van"},
    # Flatbed & open deck
    "flatbed":           {"label": "Flatbed",            "max_lbs": 48000, "icon": "bi-view-stacked",      "group": "Flatbed"},
    "step_deck":         {"label": "Step Deck",          "max_lbs": 48000, "icon": "bi-layout-split",      "group": "Flatbed"},
    "double_drop":       {"label": "Double Drop",        "max_lbs": 40000, "icon": "bi-arrow-down-square", "group": "Flatbed"},
    "lowboy":            {"label": "Lowboy",             "max_lbs": 80000, "icon": "bi-box-arrow-down",    "group": "Flatbed"},
    "conestoga":         {"label": "Conestoga",          "max_lbs": 44000, "icon": "bi-shield-shaded",     "group": "Flatbed"},
    "curtainside":       {"label": "Curtainside",        "max_lbs": 44000, "icon": "bi-layout-sidebar",    "group": "Flatbed"},
    # Power & hotshot
    "power_only":        {"label": "Power Only",         "max_lbs": 48000, "icon": "bi-lightning-charge",  "group": "Power"},
    "hotshot":           {"label": "Hotshot Trailer",    "max_lbs": 16500, "icon": "bi-speedometer2",      "group": "Power"},
    # Bulk & specialty liquid/dry
    "tanker":            {"label": "Tanker",             "max_lbs": 44000, "icon": "bi-droplet-half",      "group": "Bulk"},
    "hopper_bottom":     {"label": "Hopper Bottom",      "max_lbs": 48000, "icon": "bi-funnel",            "group": "Bulk"},
    "pneumatic":         {"label": "Pneumatic Tanker",   "max_lbs": 44000, "icon": "bi-wind",              "group": "Bulk"},
    "end_dump":          {"label": "End Dump",           "max_lbs": 48000, "icon": "bi-chevron-bar-down",  "group": "Bulk"},
    "side_dump":         {"label": "Side Dump",          "max_lbs": 48000, "icon": "bi-chevron-bar-right", "group": "Bulk"},
    "walking_floor":     {"label": "Walking Floor",      "max_lbs": 44000, "icon": "bi-arrow-left-right",  "group": "Bulk"},
    # Specialty
    "car_hauler":        {"label": "Car Hauler",         "max_lbs": 26000, "icon": "bi-car-front",         "group": "Specialty"},
    "livestock":         {"label": "Livestock Trailer",  "max_lbs": 44000, "icon": "bi-columns-gap",       "group": "Specialty"},
    "container_chassis": {"label": "Container Chassis",  "max_lbs": 44000, "icon": "bi-box2",              "group": "Specialty"},
}


def _lb_generate_load_ref():
    """Generate a unique load reference for the LTL builder (LD-YYYY-NNNN)."""
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM loads").fetchone()[0] + 1
        return f"LD-{datetime.now().year}-{count:04d}"
    finally:
        conn.close()


def create_ltl_load(equipment_type="dry_van", trailer_number="", driver_id=None, notes=""):
    """Create a new LTL load shell. Returns the new load id."""
    init_tms_db()
    conn = get_db()
    try:
        ref = _lb_generate_load_ref()
        max_lbs = EQUIPMENT_TYPES.get(equipment_type, EQUIPMENT_TYPES["dry_van"])["max_lbs"]
        conn.execute(
            """INSERT INTO loads
               (load_ref, load_type, equipment_type, trailer_number, max_weight_lbs,
                driver_id, dispatcher_notes, status)
               VALUES (?,?,?,?,?,?,?,'Planning')""",
            (ref, "LTL", equipment_type, trailer_number or "", max_lbs, driver_id, notes or ""),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM loads WHERE load_ref=?", (ref,)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def add_shipment_to_load(load_id, shipment_ref):
    """Add a shipment to a load. Returns (ok: bool, message: str)."""
    init_tms_db()
    conn = get_db()
    try:
        load = conn.execute("SELECT * FROM loads WHERE id=?", (load_id,)).fetchone()
        if not load:
            return False, "Load not found"
        shipment = conn.execute(
            "SELECT weight_kg FROM shipments WHERE shipment_ref=?", (shipment_ref,)
        ).fetchone()
        if not shipment:
            return False, "Shipment not found"
        weight_lbs = (shipment["weight_kg"] or 0) * 2.20462
        current_lbs = (load["total_weight"] or 0) * 2.20462
        max_lbs = load["max_weight_lbs"] or 44000
        if current_lbs + weight_lbs > max_lbs:
            return False, (
                f"Exceeds max weight ({max_lbs:,.0f} lbs). "
                f"Load is at {current_lbs:,.0f} lbs."
            )
        conn.execute(
            "INSERT OR IGNORE INTO load_shipments (load_id, shipment_ref) VALUES (?,?)",
            (load_id, shipment_ref),
        )
        new_total_kg = (load["total_weight"] or 0) + (shipment["weight_kg"] or 0)
        conn.execute(
            "UPDATE loads SET total_weight=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_total_kg, load_id),
        )
        conn.commit()
        return True, "Added"
    except Exception as exc:
        return False, str(exc)
    finally:
        conn.close()


def remove_shipment_from_load(load_id, shipment_ref):
    """Remove a shipment from a load and adjust total weight."""
    init_tms_db()
    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT weight_kg FROM shipments WHERE shipment_ref=?", (shipment_ref,)
        ).fetchone()
        conn.execute(
            "DELETE FROM load_shipments WHERE load_id=? AND shipment_ref=?",
            (load_id, shipment_ref),
        )
        if shipment:
            load = conn.execute(
                "SELECT total_weight FROM loads WHERE id=?", (load_id,)
            ).fetchone()
            new_wt = max(0, (load["total_weight"] or 0) - (shipment["weight_kg"] or 0))
            conn.execute(
                "UPDATE loads SET total_weight=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_wt, load_id),
            )
        conn.commit()
    finally:
        conn.close()


def add_load_stop(
    load_id, stop_type, company_name, address, city, state, zip_code,
    shipment_ref="", scheduled_time="", notes=""
):
    """Append a stop to a load."""
    init_tms_db()
    conn = get_db()
    try:
        last = conn.execute(
            "SELECT MAX(stop_number) as mx FROM load_stops WHERE load_id=?", (load_id,)
        ).fetchone()
        next_num = (last["mx"] or 0) + 1
        conn.execute(
            """INSERT INTO load_stops
               (load_id, stop_number, stop_type, company_name, address,
                city, state, zip, shipment_ref, scheduled_time, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (load_id, next_num, stop_type, company_name, address,
             city, state, zip_code, shipment_ref, scheduled_time, notes),
        )
        conn.commit()
    finally:
        conn.close()


def reorder_load_stops(load_id, ordered_stop_ids):
    """Renumber stops based on new order list of stop IDs."""
    init_tms_db()
    conn = get_db()
    try:
        for i, stop_id in enumerate(ordered_stop_ids, 1):
            conn.execute(
                "UPDATE load_stops SET stop_number=? WHERE id=? AND load_id=?",
                (i, stop_id, load_id),
            )
        conn.commit()
    finally:
        conn.close()


def convert_load_to_ftl(load_id):
    """Convert an LTL load to FTL. Returns the load_ref."""
    init_tms_db()
    conn = get_db()
    try:
        conn.execute(
            "UPDATE loads SET load_type='FTL', status='Dispatched', "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (load_id,),
        )
        conn.commit()
        load = conn.execute("SELECT load_ref FROM loads WHERE id=?", (load_id,)).fetchone()
        return load["load_ref"] if load else None
    finally:
        conn.close()


def send_load_message(load_id, sender, message):
    """Insert a dispatcher/driver message for a load."""
    init_tms_db()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO load_messages (load_id, sender, message) VALUES (?,?,?)",
            (load_id, sender, message),
        )
        conn.commit()
    finally:
        conn.close()


def get_load_messages(load_id):
    """Return all messages for a load ordered oldest-first."""
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM load_messages WHERE load_id=? ORDER BY created_at ASC",
            (load_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def approve_stop_deviation(stop_id):
    """Mark a deviated stop as approved."""
    init_tms_db()
    conn = get_db()
    try:
        conn.execute(
            "UPDATE load_stops SET deviation_approved=1 WHERE id=?", (stop_id,)
        )
        conn.commit()
    finally:
        conn.close()


def release_load_to_accounting(load_id):
    """Mark all PODs on this load as released, flag the load billing_released."""
    init_tms_db()
    conn = get_db()
    try:
        load_shipments = conn.execute(
            "SELECT shipment_ref FROM load_shipments WHERE load_id=?", (load_id,)
        ).fetchall()
        for ls in load_shipments:
            conn.execute(
                "UPDATE pod_records SET billing_status='released' WHERE shipment_ref=?",
                (ls["shipment_ref"],),
            )
        conn.execute(
            "UPDATE loads SET billing_released=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (load_id,),
        )
        conn.commit()
    finally:
        conn.close()


def get_load_builder_context(load_id):
    """Full context dict for the load builder page."""
    init_tms_db()
    conn = get_db()
    try:
        load = conn.execute("SELECT * FROM loads WHERE id=?", (load_id,)).fetchone()
        if not load:
            return None
        load = dict(load)
        max_lbs = load.get("max_weight_lbs") or 44000
        current_lbs = (load.get("total_weight") or 0) * 2.20462
        load["current_lbs"] = round(current_lbs, 0)
        load["remaining_lbs"] = round(max(0, max_lbs - current_lbs), 0)
        load["fill_pct"] = min(100, round(current_lbs / max_lbs * 100, 1)) if max_lbs else 0
        load["is_ftl_ready"] = current_lbs >= max_lbs * 0.9
        load["equipment_label"] = EQUIPMENT_TYPES.get(
            load.get("equipment_type", "dry_van"), EQUIPMENT_TYPES["dry_van"]
        )["label"]

        # Driver name (may not exist in older DBs)
        driver_name = None
        if load.get("driver_id"):
            d = conn.execute(
                "SELECT name FROM drivers WHERE id=?", (load["driver_id"],)
            ).fetchone()
            if d:
                driver_name = d["name"]
        load["driver_name"] = driver_name

        # Shipments on this load
        shipments = conn.execute(
            """SELECT s.shipment_ref, s.cargo_description, s.weight_kg,
                      s.origin_port, s.destination_port, s.status
               FROM shipments s
               JOIN load_shipments ls ON ls.shipment_ref = s.shipment_ref
               WHERE ls.load_id = ?
               ORDER BY ls.rowid""",
            (load_id,),
        ).fetchall()
        load["shipments"] = [dict(s) for s in shipments]
        for s in load["shipments"]:
            s["weight_lbs"] = round((s.get("weight_kg") or 0) * 2.20462, 0)

        # Stops
        stops = conn.execute(
            "SELECT * FROM load_stops WHERE load_id=? ORDER BY stop_number", (load_id,)
        ).fetchall()
        load["stops"] = [dict(s) for s in stops]

        # Messages
        load["messages"] = get_load_messages(load_id)

        # Available shipments (not on any load, road/LTL mode)
        available = conn.execute(
            """SELECT s.shipment_ref, s.cargo_description, s.weight_kg,
                      s.origin_port, s.destination_port
               FROM shipments s
               WHERE s.mode IN ('LTL','ltl','road','Road')
               AND s.shipment_ref NOT IN (SELECT shipment_ref FROM load_shipments)
               AND s.status NOT IN ('Delivered','Cancelled')
               ORDER BY s.created_at DESC LIMIT 50"""
        ).fetchall()
        load["available_shipments"] = [dict(r) for r in available]
        for s in load["available_shipments"]:
            s["weight_lbs"] = round((s.get("weight_kg") or 0) * 2.20462, 0)

        # Driver options
        try:
            drivers = conn.execute(
                "SELECT id, name, status FROM drivers ORDER BY name"
            ).fetchall()
            load["drivers"] = [dict(d) for d in drivers]
        except Exception:
            load["drivers"] = []

        return load
    finally:
        conn.close()


def get_all_loads_context():
    """Summary list for the loads overview page."""
    init_tms_db()
    conn = get_db()
    try:
        loads = conn.execute(
            """SELECT l.*,
                      COUNT(ls.shipment_ref) as shipment_count,
                      d.name as driver_name
               FROM loads l
               LEFT JOIN load_shipments ls ON ls.load_id = l.id
               LEFT JOIN drivers d ON d.id = l.driver_id
               GROUP BY l.id
               ORDER BY l.created_at DESC"""
        ).fetchall()
        result = []
        for row in loads:
            r = dict(row)
            max_lbs = r.get("max_weight_lbs") or 44000
            current_lbs = (r.get("total_weight") or 0) * 2.20462
            r["fill_pct"] = min(100, round(current_lbs / max_lbs * 100, 1)) if max_lbs else 0
            r["current_lbs"] = round(current_lbs)
            r["equipment_label"] = EQUIPMENT_TYPES.get(
                r.get("equipment_type", "dry_van"), EQUIPMENT_TYPES["dry_van"]
            )["label"]
            result.append(r)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Multi-Leg Shipment Functions
# ---------------------------------------------------------------------------

LEG_MODES = ["Ocean", "Air", "Truck", "Rail", "Drayage", "LTL", "FTL", "Barge"]
LEG_STATUSES = ["Planned", "Booked", "In Transit", "Completed", "On Hold", "Cancelled"]


def add_shipment_leg(shipment_ref, leg_number, mode, carrier_name, origin, destination, etd="", eta="", container_ref="", notes=""):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO shipment_legs
               (shipment_ref, leg_number, mode, carrier_name, origin, destination, etd, eta, container_ref, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (shipment_ref, leg_number, mode, carrier_name, origin, destination, etd, eta, container_ref, notes)
        )
        conn.commit()
    finally:
        conn.close()


def get_shipment_legs(shipment_ref):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM shipment_legs WHERE shipment_ref=? ORDER BY leg_number", (shipment_ref,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_leg_status(leg_id, status):
    conn = get_db()
    try:
        conn.execute("UPDATE shipment_legs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, leg_id))
        conn.commit()
    finally:
        conn.close()


def delete_shipment_leg(leg_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM shipment_legs WHERE id=?", (leg_id,))
        conn.commit()
    finally:
        conn.close()


def reorder_shipment_legs(shipment_ref, ordered_leg_ids):
    conn = get_db()
    try:
        for i, leg_id in enumerate(ordered_leg_ids, 1):
            conn.execute("UPDATE shipment_legs SET leg_number=? WHERE id=? AND shipment_ref=?", (i, leg_id, shipment_ref))
        conn.commit()
    finally:
        conn.close()


# ── Customs & Compliance ─────────────────────────────────────────────────────

INCOTERMS = ["EXW", "FCA", "CPT", "CIP", "DAP", "DPU", "DDP", "FAS", "FOB", "CFR", "CIF"]
CUSTOMS_STATUSES = ["Pending", "Filed", "Cleared", "On Hold", "Rejected"]

HS_CODE_HINTS = {
    "electronics": "8471",
    "machinery": "8429",
    "clothing": "6109",
    "furniture": "9403",
    "chemicals": "2901",
    "food": "1901",
    "auto parts": "8708",
    "medical": "9018",
    "plastics": "3926",
    "steel": "7208",
}

RESTRICTED_COUNTRIES = {"IR", "KP", "SY", "CU", "RU", "BY"}
IMPORT_LICENSE_COUNTRIES = {"CN", "IN", "BR", "AR", "EG", "NG"}


def get_customs_record(shipment_ref):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM shipment_customs WHERE shipment_ref=?", (shipment_ref,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_customs_record(shipment_ref, data: dict):
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM shipment_customs WHERE shipment_ref=?", (shipment_ref,)).fetchone()
        fields = [
            "hs_code", "goods_description", "declared_value", "declared_currency",
            "origin_country", "destination_country", "incoterm",
            "export_license_required", "import_license_required",
            "restricted_goods", "restriction_notes",
            "estimated_duty_pct", "estimated_duty_amount",
            "customs_status", "entry_number", "broker_name", "broker_contact", "filing_notes",
        ]
        if existing:
            present = [f for f in fields if f in data]
            sets = ", ".join(f"{f}=?" for f in present) + ", updated_at=CURRENT_TIMESTAMP"
            vals = [data[f] for f in present] + [shipment_ref]
            conn.execute(f"UPDATE shipment_customs SET {sets} WHERE shipment_ref=?", vals)
        else:
            ins_fields = ["shipment_ref"] + [f for f in fields if f in data]
            ins_vals = [shipment_ref] + [data[f] for f in fields if f in data]
            placeholders = ",".join("?" * len(ins_vals))
            conn.execute(
                f"INSERT INTO shipment_customs ({','.join(ins_fields)}) VALUES ({placeholders})",
                ins_vals,
            )
        conn.commit()
    finally:
        conn.close()


def estimate_duty(hs_code, origin_country, destination_country, declared_value):
    """Simple duty estimator — returns (pct, amount). Real rates need a tariff API."""
    us_rates = {
        "84": 0.0,
        "85": 0.0,
        "87": 2.5,
        "61": 12.0,
        "62": 12.0,
        "64": 9.0,
        "39": 3.0,
        "72": 0.0,
        "90": 0.0,
    }
    chapter = hs_code[:2] if hs_code else ""
    pct = us_rates.get(chapter, 5.0)
    if destination_country == "US" and origin_country in ("CA", "MX"):
        pct = 0.0
    amount = round(declared_value * pct / 100, 2)
    return pct, amount


def check_compliance_flags(origin_country, destination_country, hs_code=""):
    """Returns dict of compliance flags."""
    flags = {
        "restricted": origin_country in RESTRICTED_COUNTRIES or destination_country in RESTRICTED_COUNTRIES,
        "export_license": len(hs_code) >= 4 and hs_code[:4] in ("8471", "8443", "9301", "9302", "9303"),
        "import_license": destination_country in IMPORT_LICENSE_COUNTRIES,
        "notes": [],
    }
    if flags["restricted"]:
        flags["notes"].append("Shipment involves a restricted/sanctioned country — verify OFAC compliance.")
    if flags["export_license"]:
        flags["notes"].append("HS code may require US export license (EAR/ITAR). Verify with compliance officer.")
    if flags["import_license"]:
        flags["notes"].append("Destination country may require import license for certain goods.")
    return flags


def get_customs_dashboard_context():
    """All shipments with customs records + status breakdown."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT sc.*, s.cargo_description, s.origin_port, s.destination_port, s.mode
               FROM shipment_customs sc
               JOIN shipments s ON s.shipment_ref = sc.shipment_ref
               ORDER BY sc.updated_at DESC"""
        ).fetchall()
        records = [dict(r) for r in rows]
        stats = {s: sum(1 for r in records if r["customs_status"] == s) for s in CUSTOMS_STATUSES}
        return {"records": records, "stats": stats}
    finally:
        conn.close()


# ── Route Planner ──────────────────────────────────────────────────────────────

STOP_TYPES = ["Pickup", "Drop", "Fuel", "Rest"]
ROUTE_STATUSES = ["Draft", "Assigned", "In Progress", "Completed"]


def generate_route_ref():
    return "RT-" + "".join(random.choices(string.digits, k=6))


def create_route_plan(shipment_ref="", load_number="", driver_id=None, notes=""):
    conn = get_db()
    try:
        ref = generate_route_ref()
        conn.execute(
            "INSERT INTO route_plans (route_ref, shipment_ref, load_number, driver_id, notes) VALUES (?,?,?,?,?)",
            (ref, shipment_ref, load_number, driver_id, notes),
        )
        conn.commit()
        return ref
    finally:
        conn.close()


def get_route_plan(route_ref):
    conn = get_db()
    try:
        plan = conn.execute("SELECT * FROM route_plans WHERE route_ref=?", (route_ref,)).fetchone()
        if not plan:
            return None, []
        stops = conn.execute(
            "SELECT * FROM route_stops WHERE route_ref=? ORDER BY stop_number", (route_ref,)
        ).fetchall()
        return dict(plan), [dict(s) for s in stops]
    finally:
        conn.close()


def get_all_route_plans():
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT rp.*, d.name as driver_name
               FROM route_plans rp
               LEFT JOIN drivers d ON d.id = rp.driver_id
               ORDER BY rp.created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def add_route_stop(route_ref, stop_data: dict):
    conn = get_db()
    try:
        max_stop = conn.execute(
            "SELECT MAX(stop_number) FROM route_stops WHERE route_ref=?", (route_ref,)
        ).fetchone()[0] or 0
        stop_num = max_stop + 1
        conn.execute(
            """INSERT INTO route_stops (route_ref, stop_number, stop_type, address, city, state, zip,
               contact_name, contact_phone, appointment_time, reference_number, shipment_ref,
               weight_lbs, pallets, special_instructions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                route_ref,
                stop_num,
                stop_data.get("stop_type", "Pickup"),
                stop_data.get("address", ""),
                stop_data.get("city", ""),
                stop_data.get("state", ""),
                stop_data.get("zip", ""),
                stop_data.get("contact_name", ""),
                stop_data.get("contact_phone", ""),
                stop_data.get("appointment_time", ""),
                stop_data.get("reference_number", ""),
                stop_data.get("shipment_ref", ""),
                float(stop_data.get("weight_lbs", 0)),
                int(stop_data.get("pallets", 0)),
                stop_data.get("special_instructions", ""),
            ),
        )
        conn.execute(
            "UPDATE route_plans SET total_stops=total_stops+1, updated_at=CURRENT_TIMESTAMP WHERE route_ref=?",
            (route_ref,),
        )
        conn.commit()
        # Return the newly inserted stop id
        stop_id = conn.execute(
            "SELECT id FROM route_stops WHERE route_ref=? AND stop_number=?", (route_ref, stop_num)
        ).fetchone()
        return stop_num, (stop_id["id"] if stop_id else None)
    finally:
        conn.close()


def reorder_stops(route_ref, ordered_refs: list):
    """ordered_refs = list of stop IDs in new order."""
    conn = get_db()
    try:
        for i, stop_id in enumerate(ordered_refs, 1):
            conn.execute(
                "UPDATE route_stops SET stop_number=? WHERE id=? AND route_ref=?",
                (i, stop_id, route_ref),
            )
        conn.execute(
            "UPDATE route_plans SET updated_at=CURRENT_TIMESTAMP WHERE route_ref=?", (route_ref,)
        )
        conn.commit()
    finally:
        conn.close()


def delete_route_stop(route_ref, stop_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM route_stops WHERE id=? AND route_ref=?", (stop_id, route_ref))
        stops = conn.execute(
            "SELECT id FROM route_stops WHERE route_ref=? ORDER BY stop_number", (route_ref,)
        ).fetchall()
        for i, s in enumerate(stops, 1):
            conn.execute("UPDATE route_stops SET stop_number=? WHERE id=?", (i, s["id"]))
        conn.execute(
            "UPDATE route_plans SET total_stops=MAX(0,total_stops-1), updated_at=CURRENT_TIMESTAMP WHERE route_ref=?",
            (route_ref,),
        )
        conn.commit()
    finally:
        conn.close()


def update_stop_status(route_ref, stop_id, status):
    conn = get_db()
    try:
        if status == "Completed":
            conn.execute(
                "UPDATE route_stops SET status=?, completed_at=CURRENT_TIMESTAMP WHERE id=? AND route_ref=?",
                (status, stop_id, route_ref),
            )
        else:
            conn.execute(
                "UPDATE route_stops SET status=?, completed_at=NULL WHERE id=? AND route_ref=?",
                (status, stop_id, route_ref),
            )
        conn.commit()
    finally:
        conn.close()


def assign_driver_to_route(route_ref, driver_id):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE route_plans SET driver_id=?, status='Assigned', updated_at=CURRENT_TIMESTAMP WHERE route_ref=?",
            (driver_id, route_ref),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LTL Load Builder — dedicated ltl_loads / ltl_load_shipments tables
# ---------------------------------------------------------------------------

LTL_STATUSES = ["Building", "Sealed", "Converted to FTL", "Dispatched"]
LTL_EQUIPMENT_TYPES = ["Dry Van", "Reefer", "Flatbed"]
LTL_MAX_WEIGHTS = {"Dry Van": 44000, "Reefer": 42500, "Flatbed": 48000}
LTL_MAX_PALLETS = {"Dry Van": 26, "Reefer": 24, "Flatbed": 24}


def ltl_generate_load_number():
    import random
    import string
    return "LTL-" + "".join(random.choices(string.digits, k=6))


def ltl_get_all():
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM ltl_loads ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def ltl_get(load_number):
    init_tms_db()
    conn = get_db()
    try:
        load = conn.execute("SELECT * FROM ltl_loads WHERE load_number=?", (load_number,)).fetchone()
        if not load:
            return None, []
        shipments = conn.execute(
            """SELECT ls.*, s.cargo_description, s.origin_port, s.destination_port, s.status
               FROM ltl_load_shipments ls
               LEFT JOIN shipments s ON s.shipment_ref = ls.shipment_ref
               WHERE ls.load_number=? ORDER BY ls.sequence""",
            (load_number,),
        ).fetchall()
        return dict(load), [dict(s) for s in shipments]
    finally:
        conn.close()


def ltl_create(data: dict):
    init_tms_db()
    conn = get_db()
    try:
        load_number = data.get("load_number") or ltl_generate_load_number()
        eq = data.get("equipment_type", "Dry Van")
        conn.execute(
            """INSERT INTO ltl_loads (load_number, trailer_number, equipment_type, max_weight_lbs, max_pallets,
               origin_city, destination_city, pickup_date, carrier, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                load_number,
                data.get("trailer_number", ""),
                eq,
                LTL_MAX_WEIGHTS.get(eq, 44000),
                LTL_MAX_PALLETS.get(eq, 26),
                data.get("origin_city", ""),
                data.get("destination_city", ""),
                data.get("pickup_date", ""),
                data.get("carrier", ""),
                data.get("notes", ""),
            ),
        )
        conn.commit()
        return load_number
    finally:
        conn.close()


def ltl_add_shipment(load_number, shipment_ref, weight_lbs, pallets, pickup_address="", delivery_address=""):
    init_tms_db()
    conn = get_db()
    try:
        load = conn.execute("SELECT * FROM ltl_loads WHERE load_number=?", (load_number,)).fetchone()
        if not load or load["status"] not in ("Building",):
            return False, "Load is not open for additions"
        new_weight = (load["current_weight_lbs"] or 0) + weight_lbs
        new_pallets = (load["current_pallets"] or 0) + pallets
        if new_weight > load["max_weight_lbs"]:
            return False, f"Exceeds max weight ({load['max_weight_lbs']:,.0f} lbs)"
        if new_pallets > load["max_pallets"]:
            return False, f"Exceeds max pallets ({load['max_pallets']})"
        seq = (
            conn.execute(
                "SELECT MAX(sequence) FROM ltl_load_shipments WHERE load_number=?", (load_number,)
            ).fetchone()[0]
            or 0
        ) + 1
        conn.execute(
            """INSERT OR IGNORE INTO ltl_load_shipments
               (load_number, shipment_ref, weight_lbs, pallets, sequence, pickup_address, delivery_address)
               VALUES (?,?,?,?,?,?,?)""",
            (load_number, shipment_ref, weight_lbs, pallets, seq, pickup_address, delivery_address),
        )
        conn.execute(
            """UPDATE ltl_loads SET current_weight_lbs=?, current_pallets=?,
               updated_at=CURRENT_TIMESTAMP WHERE load_number=?""",
            (new_weight, new_pallets, load_number),
        )
        conn.commit()
        return True, "Added"
    finally:
        conn.close()


def ltl_remove_shipment(load_number, shipment_ref):
    init_tms_db()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT weight_lbs, pallets FROM ltl_load_shipments WHERE load_number=? AND shipment_ref=?",
            (load_number, shipment_ref),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "DELETE FROM ltl_load_shipments WHERE load_number=? AND shipment_ref=?",
            (load_number, shipment_ref),
        )
        conn.execute(
            """UPDATE ltl_loads SET current_weight_lbs=current_weight_lbs-?,
               current_pallets=current_pallets-?, updated_at=CURRENT_TIMESTAMP WHERE load_number=?""",
            (row["weight_lbs"], row["pallets"], load_number),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def ltl_convert_to_ftl(load_number):
    """Seal the load, create a master FTL shipment ref, mark as Converted to FTL."""
    import random
    import string

    init_tms_db()
    conn = get_db()
    try:
        load = conn.execute("SELECT * FROM ltl_loads WHERE load_number=?", (load_number,)).fetchone()
        if not load:
            return False, "Load not found"
        if load["status"] != "Building":
            return False, f"Load is already {load['status']}"
        ftl_ref = "FTL-" + "".join(random.choices(string.digits, k=6))
        try:
            conn.execute(
                """INSERT OR IGNORE INTO shipments
                   (shipment_ref, cargo_description, origin_port, destination_port, mode, status, weight_kg)
                   VALUES (?, ?, ?, ?, 'FTL', 'Booked', ?)""",
                (
                    ftl_ref,
                    f"FTL Consolidated from {load_number}",
                    load["origin_city"],
                    load["destination_city"],
                    round((load["current_weight_lbs"] or 0) / 2.20462, 2),
                ),
            )
        except Exception:
            pass
        conn.execute(
            """UPDATE ltl_loads SET status='Converted to FTL', ftl_shipment_ref=?,
               updated_at=CURRENT_TIMESTAMP WHERE load_number=?""",
            (ftl_ref, load_number),
        )
        conn.commit()
        return True, ftl_ref
    finally:
        conn.close()


def ltl_fill_stats(load):
    """Returns (weight_pct, pallet_pct, lbs_to_ftl)."""
    weight_pct = (
        round(((load["current_weight_lbs"] or 0) / load["max_weight_lbs"]) * 100, 1)
        if load.get("max_weight_lbs")
        else 0
    )
    pallet_pct = (
        round(((load["current_pallets"] or 0) / load["max_pallets"]) * 100, 1)
        if load.get("max_pallets")
        else 0
    )
    lbs_to_ftl = max(0, (load["max_weight_lbs"] or 0) - (load["current_weight_lbs"] or 0))
    return weight_pct, pallet_pct, lbs_to_ftl


# ── Customer Order Intake ──────────────────────────────────────────────────────

PIPELINE_STAGES = ["Received", "Quoted", "Dispatched", "In Transit", "Delivered", "Billed"]
SERVICE_TYPES = ["LTL", "FTL", "Expedited", "White Glove", "Intermodal"]
EQUIPMENT_TYPES_ORDER = ["Dry Van", "Reefer", "Flatbed", "Step Deck", "Lowboy", "Tanker"]


def generate_order_ref():
    return "ORD-" + "".join(random.choices(string.digits, k=6))


def submit_customer_order(data: dict) -> str:
    """Creates a customer order and auto-generates a linked shipment. Returns order_ref."""
    conn = get_db()
    try:
        order_ref = generate_order_ref()
        shipment_ref = "SHP-" + "".join(random.choices(string.digits, k=6))

        conn.execute(
            """INSERT INTO customer_orders
               (order_ref, shipment_ref, customer_name, customer_email, customer_phone, customer_company,
                origin_address, origin_city, origin_state, origin_zip,
                destination_address, destination_city, destination_state, destination_zip,
                pickup_date, delivery_date, cargo_description, weight_lbs, pallets, pieces,
                equipment_type, service_type, special_instructions,
                hazmat, temperature_controlled, temp_min, temp_max, declared_value)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_ref, shipment_ref,
             data.get("customer_name", ""), data.get("customer_email", ""),
             data.get("customer_phone", ""), data.get("customer_company", ""),
             data.get("origin_address", ""), data.get("origin_city", ""),
             data.get("origin_state", ""), data.get("origin_zip", ""),
             data.get("destination_address", ""), data.get("destination_city", ""),
             data.get("destination_state", ""), data.get("destination_zip", ""),
             data.get("pickup_date", ""), data.get("delivery_date", ""),
             data.get("cargo_description", ""),
             float(data.get("weight_lbs") or 0), int(data.get("pallets") or 0),
             int(data.get("pieces") or 0),
             data.get("equipment_type", "Dry Van"), data.get("service_type", "LTL"),
             data.get("special_instructions", ""),
             1 if data.get("hazmat") else 0,
             1 if data.get("temperature_controlled") else 0,
             data.get("temp_min") or None, data.get("temp_max") or None,
             float(data.get("declared_value") or 0))
        )

        # Auto-create linked shipment
        origin = ", ".join(filter(None, [data.get("origin_city", ""), data.get("origin_state", "")]))
        destination = ", ".join(filter(None, [data.get("destination_city", ""), data.get("destination_state", "")]))
        conn.execute(
            """INSERT INTO shipments (shipment_ref, cargo_description, origin_port, destination_port,
               mode, status, weight_kg, containers, etd, customer_name)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (shipment_ref, data.get("cargo_description", "Customer Order"),
             origin, destination,
             data.get("service_type", "LTL"), "Draft",
             float(data.get("weight_lbs") or 0),
             data.get("equipment_type", "Dry Van"),
             data.get("pickup_date", ""),
             data.get("customer_name", ""))
        )
        conn.commit()
        return order_ref
    finally:
        conn.close()


def get_all_customer_orders():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM customer_orders ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pipeline_counts():
    conn = get_db()
    try:
        counts = {}
        for stage in PIPELINE_STAGES:
            counts[stage] = conn.execute(
                "SELECT COUNT(*) FROM customer_orders WHERE pipeline_stage=?", (stage,)
            ).fetchone()[0]
        return counts
    finally:
        conn.close()


def get_pipeline_orders():
    """Returns orders grouped by pipeline stage."""
    conn = get_db()
    try:
        result = {}
        for stage in PIPELINE_STAGES:
            rows = conn.execute(
                "SELECT * FROM customer_orders WHERE pipeline_stage=? ORDER BY created_at DESC",
                (stage,)
            ).fetchall()
            result[stage] = [dict(r) for r in rows]
        return result
    finally:
        conn.close()


def advance_order_stage(order_ref, new_stage):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE customer_orders SET pipeline_stage=?, updated_at=CURRENT_TIMESTAMP WHERE order_ref=?",
            (new_stage, order_ref)
        )
        conn.commit()
    finally:
        conn.close()


def get_customer_order(order_ref):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM customer_orders WHERE order_ref=?", (order_ref,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
