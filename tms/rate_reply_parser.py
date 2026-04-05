"""
Rate Reply Parser
=================
Parses inbound carrier email replies from email_replies, extracts
rate_20ft / rate_40ft / rate_40hc / transit_days / validity, matches
each reply to the correct tender_response, writes the rates, and sets
contacts.verified_score = 100 when a carrier confirms rates.

Public API
----------
process_pending_replies() -> list[dict]   # call from scheduler
get_gap_report()           -> dict        # pending tenders grouped by carrier/region
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── DB helpers ────────────────────────────────────────────────────────────────

def _tms_db_path() -> str:
    from .tms_db import get_db as _get_tms_db   # lazy import avoids circular
    conn = _get_tms_db()
    path = conn.execute("PRAGMA database_list").fetchone()
    conn.close()
    return path["file"] if path else ""


def _contact_db_path() -> str:
    """Path to the main contacts.db (separate from tms.db)."""
    import os
    return (
        os.environ.get("TMS_CONTACTS_DB_PATH")
        or os.environ.get("CONTACT_DB_PATH")
        or str(Path(__file__).resolve().parents[1] / "data" / "contacts.db")
    )


def _tms_conn() -> sqlite3.Connection:
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    return conn


def _email_engine_db_path() -> str:
    import os
    from pathlib import Path as P
    return (
        os.environ.get("EMAIL_ENGINE_DB_PATH")
        or os.environ.get("TMS_CONTACTS_DB_PATH")
        or str(P(__file__).resolve().parents[1] / "data" / "email_engine.db")
    )


def _email_conn() -> sqlite3.Connection | None:
    path = _email_engine_db_path()
    if not Path(path).exists():
        return None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# ── Rate extraction ───────────────────────────────────────────────────────────

# Matches: $1,250 / USD 1250 / 1,250 USD / 1250.00
_MONEY_RE = re.compile(
    r"(?:USD\s*|US\$\s*|\$\s*)"
    r"([\d,]+(?:\.\d{1,2})?)"
    r"(?:\s*(?:USD))?",
    re.IGNORECASE,
)

# Matches: 20ft / 20' / 20-ft / 20GP / 20HC / 40ft / 40HC / 45HC etc.
_CONTAINER_RE = re.compile(
    r"\b(20|40|45)\s*(?:ft|'|foot|feet|-ft)?\s*"
    r"(?:GP|HC|HQ|DC|OT|FR|RF|NOR)?\b",
    re.IGNORECASE,
)

# Validity patterns: "valid until March 31", "validity: 2026-03-31", "expires 31/03/26"
_VALIDITY_RE = re.compile(
    r"(?:valid(?:ity)?(?:\s+(?:until|through|to))?|expires?(?:\s+on)?)"
    r"\s*[:\-]?\s*"
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}"
    r"|\d{4}[\/\-]\d{2}[\/\-]\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

# Transit: "14 days" / "ETA: 21 days" / "transit time: 28 days"
_TRANSIT_RE = re.compile(
    r"(?:transit(?:\s+time)?|eta|etd|days?\s+transit|sailing\s+time)"
    r"\s*[:\-]?\s*(\d+)\s*(?:days?|d\b)",
    re.IGNORECASE,
)

# Fallback: plain "14 days" anywhere in text
_DAYS_RE = re.compile(r"\b(\d+)\s*days?\b", re.IGNORECASE)


def _parse_rates_from_text(text: str) -> dict[str, Any]:
    """
    Return dict with keys:
      rate_20ft, rate_40ft, rate_40hc, transit_days, valid_until, raw_amounts
    All monetary values are floats (None if not found).
    """
    result: dict[str, Any] = {
        "rate_20ft": None,
        "rate_40ft": None,
        "rate_40hc": None,
        "transit_days": None,
        "valid_until": None,
        "raw_amounts": [],
        "confidence": "low",
    }

    # --- Extract all dollar amounts and their positions ---
    amounts: list[tuple[int, float]] = []
    for m in _MONEY_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", ""))
            amounts.append((m.start(), val))
            result["raw_amounts"].append(val)
        except ValueError:
            pass

    # --- Try to pair amounts with container sizes ---
    container_positions: list[tuple[int, str]] = []
    for m in _CONTAINER_RE.finditer(text):
        size = m.group(1)
        label_upper = m.group(0).upper()
        if "HC" in label_upper or "HQ" in label_upper:
            container_positions.append((m.start(), f"{size}hc"))
        else:
            container_positions.append((m.start(), f"{size}ft"))

    # Match each container mention to the nearest money amount within 80 chars
    for cpos, ctype in container_positions:
        best_dist = 9999
        best_val = None
        for apos, aval in amounts:
            dist = abs(cpos - apos)
            if dist < best_dist and dist <= 80:
                best_dist = dist
                best_val = aval
        if best_val is not None:
            key = f"rate_{ctype}"
            if key in result and result[key] is None:
                result[key] = best_val

    # --- If only one amount found and no containers matched, assign to 20ft ---
    if len(amounts) == 1 and result["rate_20ft"] is None:
        result["rate_20ft"] = amounts[0][1]

    # --- Two amounts, no containers: first=20ft, second=40ft ---
    if len(amounts) == 2 and result["rate_20ft"] is None and result["rate_40ft"] is None:
        result["rate_20ft"] = amounts[0][1]
        result["rate_40ft"] = amounts[1][1]

    # --- Transit days ---
    m = _TRANSIT_RE.search(text)
    if m:
        result["transit_days"] = int(m.group(1))
    elif not result["transit_days"]:
        m = _DAYS_RE.search(text)
        if m:
            result["transit_days"] = int(m.group(1))

    # --- Validity ---
    m = _VALIDITY_RE.search(text)
    if m:
        result["valid_until"] = m.group(1).strip()

    # --- Confidence ---
    filled = sum(1 for k in ("rate_20ft", "rate_40ft") if result[k] is not None)
    if filled >= 2:
        result["confidence"] = "high"
    elif filled == 1:
        result["confidence"] = "medium"

    return result


# ── Schema: rate_reply_parse_log ──────────────────────────────────────────────

_CREATE_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS rate_reply_parse_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    email_reply_id      INTEGER NOT NULL,
    source_message_id   INTEGER,
    tender_response_id  INTEGER,
    carrier_email       TEXT DEFAULT '',
    rate_20ft           REAL,
    rate_40ft           REAL,
    rate_40hc           REAL,
    transit_days        INTEGER,
    valid_until         TEXT DEFAULT '',
    confidence          TEXT DEFAULT 'low',
    parse_status        TEXT DEFAULT 'parsed',
    gap_flags           TEXT DEFAULT '',
    created_at          TEXT NOT NULL
);
"""


def _ensure_log_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_LOG_TABLE)
    conn.commit()


def _already_parsed(conn: sqlite3.Connection, reply_id: int) -> bool:
    row = conn.execute(
        "SELECT id FROM rate_reply_parse_log WHERE email_reply_id = ?",
        (reply_id,),
    ).fetchone()
    return row is not None


def _log_parse(conn: sqlite3.Connection, entry: dict[str, Any]) -> int:
    cur = conn.execute(
        """
        INSERT INTO rate_reply_parse_log
            (email_reply_id, source_message_id, tender_response_id,
             carrier_email, rate_20ft, rate_40ft, rate_40hc, transit_days,
             valid_until, confidence, parse_status, gap_flags, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            entry.get("email_reply_id"),
            entry.get("source_message_id"),
            entry.get("tender_response_id"),
            entry.get("carrier_email", ""),
            entry.get("rate_20ft"),
            entry.get("rate_40ft"),
            entry.get("rate_40hc"),
            entry.get("transit_days"),
            entry.get("valid_until", ""),
            entry.get("confidence", "low"),
            entry.get("parse_status", "parsed"),
            entry.get("gap_flags", ""),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


# ── Tender response matching ──────────────────────────────────────────────────

def _find_tender_response(
    conn: sqlite3.Connection,
    carrier_email: str,
    source_message_id: int | None,
) -> dict[str, Any] | None:
    """
    Strategy: carrier email → tms_carriers.id → latest Pending tender_response.
    """
    if not carrier_email:
        return None
    row = conn.execute(
        """
        SELECT tr.id, tr.tender_id, tr.carrier_id, tr.token, tr.response_status,
               tc.name AS carrier_name, tc.contact_email,
               s.shipment_ref, s.origin_port, s.destination_port,
               s.mode, s.etd
        FROM tender_responses tr
        JOIN tenders t    ON t.id  = tr.tender_id
        JOIN shipments s  ON s.id  = t.shipment_id
        JOIN tms_carriers tc ON tc.id = tr.carrier_id
        WHERE LOWER(tc.contact_email) = LOWER(?)
          AND tr.response_status = 'Pending'
        ORDER BY tr.created_at DESC
        LIMIT 1
        """,
        (carrier_email,),
    ).fetchone()
    return dict(row) if row else None


# ── Contact score update ──────────────────────────────────────────────────────

def _set_contact_score_100(carrier_email: str) -> None:
    """
    Set verified_score=100 in the main contacts DB for this carrier email.
    Only updates if score < 100 (never downgrades).
    """
    db_path = _contact_db_path()
    if not Path(db_path).exists():
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            UPDATE contacts
            SET verified_score = 100,
                verified_status = 'verified',
                verified_date = ?
            WHERE LOWER(email) = LOWER(?)
              AND COALESCE(verified_score, 0) < 100
            """,
            (datetime.now(timezone.utc).date().isoformat(), carrier_email),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Write rates to tender_response ───────────────────────────────────────────

def _apply_rates(
    conn: sqlite3.Connection,
    response_id: int,
    parsed: dict[str, Any],
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    for col in ("rate_20ft", "rate_40ft", "rate_40hc", "transit_days"):
        if parsed.get(col) is not None:
            fields.append(f"{col} = ?")
            values.append(parsed[col])
    if not fields:
        return
    fields.append("response_status = 'Submitted'")
    fields.append("submitted_at = CURRENT_TIMESTAMP")
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(response_id)
    conn.execute(
        f"UPDATE tender_responses SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()


# ── Gap flags ─────────────────────────────────────────────────────────────────

def _build_gap_flags(parsed: dict[str, Any]) -> str:
    missing = []
    if parsed.get("rate_20ft") is None:
        missing.append("rate_20ft")
    if parsed.get("rate_40ft") is None:
        missing.append("rate_40ft")
    if parsed.get("valid_until") is None:
        missing.append("valid_until")
    return ",".join(missing)


# ── Main processor ────────────────────────────────────────────────────────────

def process_pending_replies() -> list[dict[str, Any]]:
    """
    Read unprocessed email replies whose source message is a rate request,
    parse rates, update tender_responses, log results, set score=100.

    Returns list of result dicts for each reply processed.
    """
    email_db = _email_conn()
    if email_db is None:
        return []

    tms_db = _tms_conn()
    _ensure_log_table(tms_db)

    results: list[dict[str, Any]] = []

    try:
        # Get unprocessed replies linked to rate-request outbound messages
        rows = email_db.execute(
            """
            SELECT er.id          AS reply_id,
                   er.source_message_id,
                   er.reply_from,
                   er.body_preview,
                   er.subject,
                   er.received_at,
                   em.template_name,
                   em.to_email
            FROM email_replies er
            LEFT JOIN email_messages em ON em.id = er.source_message_id
            WHERE (em.template_name IN ('monthly_rate_request','rate_request_monthly',
                                        'rate_request_follow_up')
                   OR em.template_name IS NULL)
            ORDER BY er.received_at DESC
            LIMIT 200
            """,
        ).fetchall()
    except Exception:
        email_db.close()
        tms_db.close()
        return []

    for row in rows:
        reply_id = row["reply_id"]
        if _already_parsed(tms_db, reply_id):
            continue

        carrier_email = (row["reply_from"] or row["to_email"] or "").strip().lower()
        body = row["body_preview"] or ""

        parsed = _parse_rates_from_text(body)
        gap_flags = _build_gap_flags(parsed)

        tender_resp = _find_tender_response(
            tms_db, carrier_email, row["source_message_id"]
        )

        response_id = tender_resp["id"] if tender_resp else None
        parse_status = "parsed" if parsed["rate_20ft"] or parsed["rate_40ft"] else "no_rates"

        if response_id and (parsed["rate_20ft"] or parsed["rate_40ft"]):
            _apply_rates(tms_db, response_id, parsed)
            _set_contact_score_100(carrier_email)
            parse_status = "applied"

        log_id = _log_parse(
            tms_db,
            {
                "email_reply_id": reply_id,
                "source_message_id": row["source_message_id"],
                "tender_response_id": response_id,
                "carrier_email": carrier_email,
                **{k: parsed[k] for k in ("rate_20ft","rate_40ft","rate_40hc","transit_days","valid_until","confidence")},
                "parse_status": parse_status,
                "gap_flags": gap_flags,
            },
        )

        results.append(
            {
                "log_id": log_id,
                "reply_id": reply_id,
                "carrier_email": carrier_email,
                "tender_response_id": response_id,
                "parse_status": parse_status,
                "confidence": parsed["confidence"],
                "gap_flags": gap_flags,
                "rate_20ft": parsed["rate_20ft"],
                "rate_40ft": parsed["rate_40ft"],
            }
        )

    email_db.close()
    tms_db.close()
    return results


# ── Gap report ────────────────────────────────────────────────────────────────

def get_gap_report() -> dict[str, Any]:
    """
    Returns:
      pending_responses   - carrier tender_responses still Pending past deadline
      incomplete_parses   - rate_reply_parse_log rows with gap_flags non-empty
      carrier_gap_summary - per-carrier count of gaps
      region_gap_summary  - per origin_port count of gaps
    """
    tms_db = _tms_conn()
    _ensure_log_table(tms_db)

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    pending = tms_db.execute(
        """
        SELECT tr.id, tr.response_status, tr.created_at,
               tc.name AS carrier_name, tc.contact_email,
               s.shipment_ref, s.origin_port, s.destination_port,
               t.deadline_at
        FROM tender_responses tr
        JOIN tenders t    ON t.id  = tr.tender_id
        JOIN shipments s  ON s.id  = t.shipment_id
        JOIN tms_carriers tc ON tc.id = tr.carrier_id
        WHERE tr.response_status = 'Pending'
          AND t.deadline_at < ?
        ORDER BY t.deadline_at DESC
        LIMIT 200
        """,
        (now_iso,),
    ).fetchall()

    incomplete = tms_db.execute(
        """
        SELECT * FROM rate_reply_parse_log
        WHERE gap_flags != '' AND parse_status != 'no_rates'
        ORDER BY created_at DESC
        LIMIT 200
        """,
    ).fetchall()

    # Carrier summary
    carrier_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    for r in pending:
        cname = r["carrier_name"] or r["contact_email"] or "Unknown"
        carrier_counts[cname] = carrier_counts.get(cname, 0) + 1
        origin = r["origin_port"] or "Unknown"
        region_counts[origin] = region_counts.get(origin, 0) + 1

    tms_db.close()
    return {
        "pending_responses": [dict(r) for r in pending],
        "incomplete_parses": [dict(r) for r in incomplete],
        "carrier_gap_summary": sorted(carrier_counts.items(), key=lambda x: -x[1]),
        "region_gap_summary": sorted(region_counts.items(), key=lambda x: -x[1]),
        "total_pending": len(pending),
        "total_incomplete": len(incomplete),
    }


def get_parse_log(limit: int = 100) -> list[dict[str, Any]]:
    tms_db = _tms_conn()
    _ensure_log_table(tms_db)
    rows = tms_db.execute(
        "SELECT * FROM rate_reply_parse_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    tms_db.close()
    return [dict(r) for r in rows]
