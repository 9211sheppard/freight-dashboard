import json
import re
from datetime import datetime

from .tms_db import _decode_secure_setting, get_db, init_tms_db


TRADE_SETTING_KEYS = ("trade_api_key", "trade_api_provider")
RESTRICTED_COUNTRY_ALIASES = {
    "cuba": "Cuba",
    "iran": "Iran",
    "north korea": "North Korea",
    "dprk": "North Korea",
    "democratic people s republic of korea": "North Korea",
    "russia": "Russia",
    "russian federation": "Russia",
}
HS_CODE_SEED = [
    ("1006", "Rice", "10", "Vegetable products"),
    ("2203", "Beer made from malt", "22", "Prepared foodstuffs"),
    ("2710", "Petroleum oils and oils from bituminous minerals", "27", "Mineral products"),
    ("3004", "Medicaments in measured doses", "30", "Products of the chemical or allied industries"),
    ("3923", "Plastic articles for the conveyance or packing of goods", "39", "Plastics and articles thereof"),
    ("4011", "New pneumatic rubber tires", "40", "Rubber and articles thereof"),
    ("4202", "Travel goods, handbags, and similar containers", "42", "Articles of leather; travel goods"),
    ("6109", "T-shirts, singlets, and other vests, knitted or crocheted", "61", "Articles of apparel and clothing accessories, knitted or crocheted"),
    ("6203", "Men's or boys' suits, ensembles, jackets, and trousers", "62", "Articles of apparel and clothing accessories, not knitted or crocheted"),
    ("6302", "Bed linen, table linen, toilet linen, and kitchen linen", "63", "Other made up textile articles"),
    ("6403", "Footwear with outer soles of rubber, plastics, leather, or composition leather", "64", "Footwear, gaiters, and the like"),
    ("7208", "Flat-rolled products of iron or non-alloy steel", "72", "Iron and steel"),
    ("7308", "Structures and parts of structures of iron or steel", "73", "Articles of iron or steel"),
    ("7601", "Unwrought aluminum", "76", "Aluminum and articles thereof"),
    ("8471", "Computers and automatic data processing machines and units", "84", "Machinery and mechanical appliances"),
    ("8501", "Electric motors and generators", "85", "Electrical machinery and equipment"),
    ("8504", "Electrical transformers and static converters", "85", "Electrical machinery and equipment"),
    ("8517", "Telephone sets and other communication apparatus", "85", "Electrical machinery and equipment"),
    ("8703", "Motor cars and other motor vehicles for the transport of persons", "87", "Vehicles other than railway or tramway rolling stock"),
    ("9403", "Other furniture and parts thereof", "94", "Furniture; bedding; lamps"),
]

_TRADE_SCHEMA_READY = False


def _normalize_hs_code(value):
    return re.sub(r"\D", "", value or "")


def _normalize_country(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _get_trade_settings(conn):
    settings = {key: "" for key in TRADE_SETTING_KEYS}
    rows = conn.execute(
        "SELECT key, value FROM tms_settings WHERE key IN (?, ?)",
        TRADE_SETTING_KEYS,
    ).fetchall()
    for row in rows:
        settings[row["key"]] = _decode_secure_setting(row["key"], row["value"])
    return settings


def _get_hs_record(conn, clean_code):
    if not clean_code:
        return None
    return conn.execute(
        """
        SELECT id, code, description, chapter, section
        FROM hs_codes
        WHERE code = ? OR ? LIKE code || '%'
        ORDER BY LENGTH(code) DESC, code
        LIMIT 1
        """,
        (clean_code, clean_code),
    ).fetchone()


def _get_tariff_rate_record(conn, clean_code, origin, dest):
    if not clean_code or not origin or not dest:
        return None
    return conn.execute(
        """
        SELECT id, hs_code, origin_country, dest_country, duty_rate_pct,
               effective_date, source, notes
        FROM tariff_rates
        WHERE lower(origin_country) = lower(?)
          AND lower(dest_country) = lower(?)
          AND (hs_code = ? OR ? LIKE hs_code || '%')
        ORDER BY LENGTH(hs_code) DESC,
                 COALESCE(effective_date, '') DESC,
                 id DESC
        LIMIT 1
        """,
        ((origin or "").strip(), (dest or "").strip(), clean_code, clean_code),
    ).fetchone()


def init_global_trade_db(force=False):
    global _TRADE_SCHEMA_READY

    if _TRADE_SCHEMA_READY and not force:
        return

    init_tms_db()
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS hs_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL,
                chapter TEXT,
                section TEXT
            );

            CREATE TABLE IF NOT EXISTS tariff_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hs_code TEXT NOT NULL,
                origin_country TEXT NOT NULL,
                dest_country TEXT NOT NULL,
                duty_rate_pct REAL,
                effective_date TEXT,
                source TEXT,
                notes TEXT,
                FOREIGN KEY (hs_code) REFERENCES hs_codes(code)
            );

            CREATE TABLE IF NOT EXISTS trade_compliance_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shipment_ref TEXT NOT NULL,
                hs_code TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('clear', 'review', 'blocked')),
                flags_json TEXT NOT NULL DEFAULT '[]',
                checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_hs_codes_lookup ON hs_codes(code, description);
            CREATE INDEX IF NOT EXISTS idx_tariff_rates_lookup
                ON tariff_rates(hs_code, origin_country, dest_country, effective_date);
            CREATE INDEX IF NOT EXISTS idx_trade_checks_checked_at
                ON trade_compliance_checks(checked_at DESC);
            """
        )
        conn.executemany(
            """
            INSERT INTO hs_codes (code, description, chapter, section)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                description = excluded.description,
                chapter = excluded.chapter,
                section = excluded.section
            """,
            HS_CODE_SEED,
        )
        for key in TRADE_SETTING_KEYS:
            conn.execute(
                "INSERT OR IGNORE INTO tms_settings (key, value) VALUES (?, ?)",
                (key, ""),
            )
        conn.commit()
        _TRADE_SCHEMA_READY = True
    finally:
        conn.close()


def search_hs_codes(query, limit=12):
    init_global_trade_db()
    search_text = (query or "").strip()
    if not search_text:
        return []

    clean_code = _normalize_hs_code(search_text)
    conn = get_db()
    try:
        if clean_code:
            rows = conn.execute(
                """
                SELECT id, code, description, chapter, section
                FROM hs_codes
                WHERE code LIKE ?
                   OR lower(description) LIKE ?
                ORDER BY CASE
                    WHEN code = ? THEN 0
                    WHEN code LIKE ? THEN 1
                    ELSE 2
                END,
                LENGTH(code),
                code
                LIMIT ?
                """,
                (
                    f"{clean_code}%",
                    f"%{search_text.lower()}%",
                    clean_code,
                    f"{clean_code}%",
                    limit,
                ),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, code, description, chapter, section
                FROM hs_codes
                WHERE lower(description) LIKE ?
                ORDER BY code
                LIMIT ?
                """,
                (f"%{search_text.lower()}%", limit),
            ).fetchall()
    finally:
        conn.close()

    return [dict(row) for row in rows]


def get_tariff_rate(hs_code, origin, dest):
    init_global_trade_db()
    clean_code = _normalize_hs_code(hs_code)
    conn = get_db()
    try:
        row = _get_tariff_rate_record(conn, clean_code, origin, dest)
    finally:
        conn.close()
    return dict(row) if row else None


def run_compliance_check(shipment_ref, hs_code, origin, dest):
    init_global_trade_db()

    clean_shipment_ref = (shipment_ref or "").strip()
    clean_hs_code = _normalize_hs_code(hs_code)
    clean_origin = (origin or "").strip()
    clean_dest = (dest or "").strip()
    checked_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    flags = []
    status = "clear"
    origin_key = _normalize_country(clean_origin)
    dest_key = _normalize_country(clean_dest)

    blocked_countries = []
    if origin_key in RESTRICTED_COUNTRY_ALIASES:
        blocked_countries.append(RESTRICTED_COUNTRY_ALIASES[origin_key])
    if dest_key in RESTRICTED_COUNTRY_ALIASES:
        blocked_countries.append(RESTRICTED_COUNTRY_ALIASES[dest_key])
    if blocked_countries:
        unique_blocked = sorted(set(blocked_countries))
        flags.append(
            {
                "code": "restricted_country",
                "message": "Restricted country match: {}.".format(", ".join(unique_blocked)),
            }
        )
        status = "blocked"

    conn = get_db()
    try:
        hs_record = _get_hs_record(conn, clean_hs_code)
        tariff_record = _get_tariff_rate_record(conn, clean_hs_code, clean_origin, clean_dest)

        if not hs_record:
            flags.append(
                {
                    "code": "hs_code_unrecognized",
                    "message": f"HS code {clean_hs_code or 'N/A'} is not in the local code library.",
                }
            )
            if status != "blocked":
                status = "review"

        if not tariff_record:
            flags.append(
                {
                    "code": "tariff_rate_missing",
                    "message": f"No tariff rate is stored for {clean_hs_code or 'N/A'} from {clean_origin or 'N/A'} to {clean_dest or 'N/A'}.",
                }
            )
            if status != "blocked":
                status = "review"

        conn.execute(
            """
            INSERT INTO trade_compliance_checks
                (shipment_ref, hs_code, origin, destination, status, flags_json, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_shipment_ref,
                clean_hs_code,
                clean_origin,
                clean_dest,
                status,
                json.dumps(flags),
                checked_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "shipment_ref": clean_shipment_ref,
        "hs_code": clean_hs_code,
        "origin": clean_origin,
        "destination": clean_dest,
        "status": status,
        "flags": flags,
        "checked_at": checked_at,
        "tariff_rate": dict(tariff_record) if tariff_record else None,
        "hs_match": dict(hs_record) if hs_record else None,
    }


def get_compliance_history(limit=25):
    init_global_trade_db()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT id, shipment_ref, hs_code, origin, destination, status, flags_json, checked_at
            FROM trade_compliance_checks
            ORDER BY checked_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    history = []
    for row in rows:
        item = dict(row)
        try:
            item["flags"] = json.loads(item.get("flags_json") or "[]")
        except json.JSONDecodeError:
            item["flags"] = []
        history.append(item)
    return history


def get_trade_settings():
    init_global_trade_db()
    conn = get_db()
    try:
        return _get_trade_settings(conn)
    finally:
        conn.close()
