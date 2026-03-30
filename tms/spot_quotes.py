from __future__ import annotations

import html
import secrets
from datetime import datetime
from typing import Any, Iterable, Mapping

from .notifications import send_email
from .tms_db import get_db


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _parse_optional_float(value: Any, label: str) -> float | None:
    raw_value = _normalize_text(value)
    if not raw_value:
        return None
    try:
        return float(raw_value.replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc


def _parse_date(value: Any, label: str) -> str | None:
    raw_value = _normalize_text(value)
    if not raw_value:
        return None
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must be in YYYY-MM-DD format.") from exc


def _parse_quote_id(value: Any) -> int:
    try:
        quote_id = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Spot quote id is invalid.") from exc
    if quote_id <= 0:
        raise ValueError("Spot quote id is invalid.")
    return quote_id


def _parse_response_id(value: Any) -> int:
    try:
        response_id = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Spot quote response id is invalid.") from exc
    if response_id <= 0:
        raise ValueError("Spot quote response id is invalid.")
    return response_id


def _normalize_email_list(carrier_emails: str | Iterable[str]) -> list[str]:
    if isinstance(carrier_emails, str):
        raw_items = carrier_emails.replace("\r", "\n").replace(";", "\n").replace(",", "\n").split("\n")
    else:
        raw_items = list(carrier_emails or [])

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_items:
        email = _normalize_text(item).lower()
        if not email or email in seen:
            continue
        cleaned.append(email)
        seen.add(email)
    return cleaned


def _generate_quote_ref(conn) -> str:
    while True:
        ref = f"SQ-{datetime.utcnow():%Y%m%d}-{secrets.token_hex(3).upper()}"
        existing = conn.execute(
            "SELECT 1 FROM spot_quotes WHERE ref = ? LIMIT 1",
            (ref,),
        ).fetchone()
        if not existing:
            return ref


def _spot_quote_email_subject(quote: Mapping[str, Any]) -> str:
    return f"Spot quote request {quote['ref']} | {quote['origin']} -> {quote['destination']}"


def _spot_quote_request_body(quote: Mapping[str, Any]) -> str:
    notes = _normalize_text(quote.get("notes"))
    weight_lbs = quote.get("weight_lbs")
    weight_display = f"{float(weight_lbs):,.0f} lbs" if weight_lbs is not None else "-"
    notes_block = (
        f"<p><strong>Notes:</strong><br>{html.escape(notes)}</p>"
        if notes
        else ""
    )
    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;color:#e5e7eb;">
      <p>Please reply with your best rate for the shipment below.</p>
      <ul>
        <li><strong>Reference:</strong> {html.escape(_normalize_text(quote.get("ref")) or "-")}</li>
        <li><strong>Origin:</strong> {html.escape(_normalize_text(quote.get("origin")) or "-")}</li>
        <li><strong>Destination:</strong> {html.escape(_normalize_text(quote.get("destination")) or "-")}</li>
        <li><strong>Equipment:</strong> {html.escape(_normalize_text(quote.get("equipment_type")) or "-")}</li>
        <li><strong>Weight:</strong> {html.escape(weight_display)}</li>
        <li><strong>Pickup Date:</strong> {html.escape(_normalize_text(quote.get("pickup_date")) or "-")}</li>
        <li><strong>Delivery Date:</strong> {html.escape(_normalize_text(quote.get("delivery_date")) or "-")}</li>
      </ul>
      {notes_block}
      <p>Include your 20ft and 40ft rates, transit time, validity date, and any notes in your reply.</p>
    </div>
    """.strip()


def _awarded_quote_body(quote: Mapping[str, Any], response: Mapping[str, Any]) -> str:
    rate_20ft = response.get("rate_20ft")
    rate_40ft = response.get("rate_40ft")
    rate_lines: list[str] = []
    if rate_20ft is not None:
        rate_lines.append(f"<li><strong>20ft Rate:</strong> ${float(rate_20ft):,.2f}</li>")
    if rate_40ft is not None:
        rate_lines.append(f"<li><strong>40ft Rate:</strong> ${float(rate_40ft):,.2f}</li>")
    rate_markup = "".join(rate_lines) or "<li><strong>Rate:</strong> See awarded quote in TMS.</li>"

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;color:#e5e7eb;">
      <p>Your spot quote has been awarded.</p>
      <ul>
        <li><strong>Reference:</strong> {html.escape(_normalize_text(quote.get("ref")) or "-")}</li>
        <li><strong>Origin:</strong> {html.escape(_normalize_text(quote.get("origin")) or "-")}</li>
        <li><strong>Destination:</strong> {html.escape(_normalize_text(quote.get("destination")) or "-")}</li>
        <li><strong>Equipment:</strong> {html.escape(_normalize_text(quote.get("equipment_type")) or "-")}</li>
        {rate_markup}
        <li><strong>Transit Days:</strong> {html.escape(_normalize_text(response.get("transit_days")) or "-")}</li>
        <li><strong>Validity Date:</strong> {html.escape(_normalize_text(response.get("validity_date")) or "-")}</li>
      </ul>
      <p>Please coordinate next steps with the operations team.</p>
    </div>
    """.strip()


def create_quote(form_data: Mapping[str, Any]) -> int:
    origin = _normalize_text(form_data.get("origin"))
    destination = _normalize_text(form_data.get("destination"))
    equipment_type = _normalize_text(form_data.get("equipment_type"))
    pickup_date = _parse_date(form_data.get("pickup_date"), "Pickup date")
    delivery_date = _parse_date(form_data.get("delivery_date"), "Delivery date")
    weight_lbs = _parse_optional_float(form_data.get("weight_lbs"), "Weight (lbs)")
    notes = _normalize_text(form_data.get("notes"))

    if not origin:
        raise ValueError("Origin is required.")
    if not destination:
        raise ValueError("Destination is required.")
    if not equipment_type:
        raise ValueError("Equipment type is required.")
    if pickup_date and delivery_date and delivery_date < pickup_date:
        raise ValueError("Delivery date cannot be earlier than pickup date.")

    conn = get_db()
    try:
        ref = _normalize_text(form_data.get("ref")).upper() or _generate_quote_ref(conn)
        cursor = conn.execute(
            """
            INSERT INTO spot_quotes
                (ref, origin, destination, weight_lbs, equipment_type, pickup_date, delivery_date, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                ref,
                origin,
                destination,
                weight_lbs,
                equipment_type,
                pickup_date,
                delivery_date,
                notes or None,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def blast_carriers(quote_id: int, carrier_emails: str | Iterable[str]) -> dict[str, int]:
    safe_quote_id = _parse_quote_id(quote_id)
    cleaned_emails = _normalize_email_list(carrier_emails)
    if not cleaned_emails:
        raise ValueError("Enter at least one carrier email.")

    detail = get_quote_detail(safe_quote_id)
    if not detail:
        raise LookupError("Spot quote not found.")

    quote = detail["quote"]
    if quote["status"] != "open":
        raise ValueError("Only open spot quotes can be blasted to carriers.")

    subject = _spot_quote_email_subject(quote)
    body_html = _spot_quote_request_body(quote)

    attempted = 0
    sent = 0
    for carrier_email in cleaned_emails:
        attempted += 1
        if send_email(carrier_email, subject, body_html, "spot_quote_request"):
            sent += 1

    return {"attempted": attempted, "sent": sent}


def get_quotes() -> list[dict[str, Any]]:
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                sq.*,
                COUNT(sqr.id) AS response_count,
                COALESCE(SUM(CASE WHEN sqr.status = 'submitted' THEN 1 ELSE 0 END), 0) AS submitted_count,
                COALESCE(SUM(CASE WHEN sqr.status = 'awarded' THEN 1 ELSE 0 END), 0) AS awarded_count
            FROM spot_quotes sq
            LEFT JOIN spot_quote_responses sqr ON sqr.quote_id = sq.id
            GROUP BY sq.id
            ORDER BY
                CASE sq.status
                    WHEN 'open' THEN 0
                    WHEN 'awarded' THEN 1
                    ELSE 2
                END,
                COALESCE(sq.pickup_date, '9999-12-31') ASC,
                datetime(sq.created_at) DESC,
                sq.id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_quote_detail(quote_id: int) -> dict[str, Any] | None:
    safe_quote_id = _parse_quote_id(quote_id)
    conn = get_db()
    try:
        quote_row = conn.execute(
            """
            SELECT
                sq.*,
                COUNT(sqr.id) AS response_count,
                COALESCE(SUM(CASE WHEN sqr.status = 'submitted' THEN 1 ELSE 0 END), 0) AS submitted_count,
                COALESCE(SUM(CASE WHEN sqr.status = 'awarded' THEN 1 ELSE 0 END), 0) AS awarded_count
            FROM spot_quotes sq
            LEFT JOIN spot_quote_responses sqr ON sqr.quote_id = sq.id
            WHERE sq.id = ?
            GROUP BY sq.id
            """,
            (safe_quote_id,),
        ).fetchone()
        if not quote_row:
            return None

        response_rows = conn.execute(
            """
            SELECT *
            FROM spot_quote_responses
            WHERE quote_id = ?
            ORDER BY
                CASE status
                    WHEN 'awarded' THEN 0
                    WHEN 'submitted' THEN 1
                    ELSE 2
                END,
                CASE
                    WHEN rate_20ft IS NULL AND rate_40ft IS NULL THEN 1
                    ELSE 0
                END,
                COALESCE(rate_20ft, rate_40ft, 999999999) ASC,
                datetime(received_at) DESC,
                id DESC
            """,
            (safe_quote_id,),
        ).fetchall()

        quote = dict(quote_row)
        responses = [dict(row) for row in response_rows]
        return {
            "quote": quote,
            "responses": responses,
            "awarded_response": next((response for response in responses if response["status"] == "awarded"), None),
        }
    finally:
        conn.close()


def award_quote(quote_id: int, response_id: int) -> dict[str, dict[str, Any]]:
    safe_quote_id = _parse_quote_id(quote_id)
    safe_response_id = _parse_response_id(response_id)

    conn = get_db()
    try:
        quote_row = conn.execute(
            "SELECT * FROM spot_quotes WHERE id = ?",
            (safe_quote_id,),
        ).fetchone()
        if not quote_row:
            raise LookupError("Spot quote not found.")

        response_row = conn.execute(
            "SELECT * FROM spot_quote_responses WHERE id = ? AND quote_id = ?",
            (safe_response_id, safe_quote_id),
        ).fetchone()
        if not response_row:
            raise LookupError("Spot quote response not found.")

        quote = dict(quote_row)
        response = dict(response_row)

        if quote["status"] != "open":
            raise ValueError("Only open spot quotes can be awarded.")
        if response["status"] != "submitted":
            raise ValueError("Only submitted responses can be awarded.")

        conn.execute(
            """
            UPDATE spot_quote_responses
            SET status = CASE WHEN id = ? THEN 'awarded' ELSE 'rejected' END
            WHERE quote_id = ?
            """,
            (safe_response_id, safe_quote_id),
        )
        conn.execute(
            """
            UPDATE spot_quotes
            SET status = 'awarded'
            WHERE id = ?
            """,
            (safe_quote_id,),
        )
        conn.commit()
    finally:
        conn.close()

    subject = f"Spot quote awarded {quote['ref']}"
    send_email(
        response.get("carrier_email") or "",
        subject,
        _awarded_quote_body(quote, response),
        "spot_quote_award",
    )

    updated_detail = get_quote_detail(safe_quote_id)
    if not updated_detail:
        raise LookupError("Spot quote not found after award.")
    return {
        "quote": updated_detail["quote"],
        "response": next(
            response_row
            for response_row in updated_detail["responses"]
            if int(response_row["id"]) == safe_response_id
        ),
    }


__all__ = [
    "award_quote",
    "blast_carriers",
    "create_quote",
    "get_quote_detail",
    "get_quotes",
]
