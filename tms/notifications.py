"""Template-driven notification helpers for TMS email events."""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import smtplib
import sqlite3
import threading
from datetime import date, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import current_app, has_app_context
from itsdangerous import URLSafeTimedSerializer

from . import tms_db

try:
    from .email_engine import EmailEngine
except Exception:
    EmailEngine = None


MODULE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = MODULE_DIR / "email_templates"
TOKEN_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")
HTML_TAG_RE = re.compile(r"<[^>]+>")

SCHEDULER_LOCK = threading.Lock()
SCHEDULER_THREAD: threading.Thread | None = None
SCHEDULER_STOP = threading.Event()
SCHEDULER_POLL_SECONDS = max(300, int(os.environ.get("TMS_NOTIFICATION_POLL_SECONDS", "900")))

ACCEPTED_SAFETY_RATINGS = {"Satisfactory", "Conditional"}
ACCEPTED_AUTH_KEYWORDS = ("authorized", "active")
REJECTED_AUTH_KEYWORDS = ("not authorized", "revoked", "inactive", "out of service")
ACCEPTED_INSURANCE_KEYWORDS = ("on file", "active", "insured")
REJECTED_INSURANCE_KEYWORDS = ("cancel", "expired", "inactive", "lapsed")

SUBJECT_TEMPLATES = {
    "shipment_created": "Shipment {{shipment_ref}} confirmed",
    "status_in_transit": "Shipment {{shipment_ref}} is in transit",
    "status_delivered": "Shipment {{shipment_ref}} delivered",
    "pod_received": "POD received for {{shipment_ref}}",
    "invoice_generated": "Invoice {{invoice_number}} for {{shipment_ref}}",
    "monthly_rate_request": "Rate request: {{shipment_ref}} | {{lane_label}}",
    "rate_request_follow_up": "Reminder: rate request for {{shipment_ref}}",
}
PUBLIC_TRACKING_TOKEN_SALT = "customer-tracking-link"


def _db_path() -> str:
    if has_app_context():
        configured = current_app.config.get("DATABASE_PATH") or current_app.config.get("TMS_DB_PATH")
        if configured:
            return str(configured)
    return str(getattr(tms_db, "TMS_DB", MODULE_DIR / "tms.db"))


def get_db() -> sqlite3.Connection:
    db_path = Path(_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_notification_tables() -> None:
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT DEFAULT '',
                body_preview TEXT DEFAULT '',
                status TEXT DEFAULT 'Queued',
                error TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS notification_campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_type TEXT NOT NULL,
                campaign_key TEXT NOT NULL,
                details_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(campaign_type, campaign_key)
            );

            CREATE TABLE IF NOT EXISTS scheduled_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_type TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                payload_json TEXT DEFAULT '{}',
                scheduled_for TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'Queued',
                error TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP DEFAULT NULL,
                UNIQUE(notification_type, entity_key)
            );

            CREATE INDEX IF NOT EXISTS idx_notification_log_created_at
                ON notification_log(created_at DESC, id DESC);
            CREATE INDEX IF NOT EXISTS idx_notification_campaigns_lookup
                ON notification_campaigns(campaign_type, campaign_key);
            CREATE INDEX IF NOT EXISTS idx_scheduled_notifications_due
                ON scheduled_notifications(status, scheduled_for, id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _utcnow() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _sql_datetime(value: datetime | None = None) -> str:
    return (value or _utcnow()).strftime("%Y-%m-%d %H:%M:%S")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(raw[: len(fmt)], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.date()
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw[: len(fmt)], fmt).date()
        except ValueError:
            continue
    return None


def _format_display_datetime(value: Any) -> str:
    parsed = _parse_datetime(value)
    return parsed.strftime("%b %d, %Y %I:%M %p UTC") if parsed else "-"


def _format_display_date(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.strftime("%b %d, %Y") if parsed else "-"


def _format_currency(amount: Any, currency: str = "USD") -> str:
    try:
        numeric = float(amount or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    return f"{(currency or 'USD').upper()} {numeric:,.2f}"


def _normalize_email(address: str | None) -> str:
    return (address or "").strip().lower()


def _dedupe_emails(addresses: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for address in addresses:
        clean = _normalize_email(address)
        if not clean or clean in seen:
            continue
        deduped.append(clean)
        seen.add(clean)
    return deduped


def _preview_text(body_html: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", body_html or "")
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()[:200]


def _log_notification(event_type: str, recipient: str, subject: str, body_html: str, status: str) -> int:
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO notification_log (event_type, recipient, subject, body_preview, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, recipient or "[no-recipient]", subject, _preview_text(body_html), status),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def _update_notification_status(log_id: int, status: str, error: str = "") -> None:
    conn = get_db()
    try:
        conn.execute(
            """
            UPDATE notification_log
            SET status = ?, error = ?, sent_at = CASE WHEN ? = 'Sent' THEN CURRENT_TIMESTAMP ELSE sent_at END
            WHERE id = ?
            """,
            (status, error, status, log_id),
        )
        conn.commit()
    finally:
        conn.close()


def _record_skipped_notification(event_type: str, subject: str, reason: str, recipient: str = "") -> bool:
    log_id = _log_notification(event_type, recipient or "[no-recipient]", subject, "", "Skipped")
    _update_notification_status(log_id, "Skipped", reason)
    return False


def _db_email_settings() -> dict[str, Any]:
    """Pull SMTP/IMAP settings stored in tms_settings DB (lowest priority)."""
    try:
        from .tms_db import get_email_settings
        return get_email_settings(include_secrets=True)
    except Exception:
        return {}


def get_smtp_config() -> dict[str, Any]:
    db_cfg = _db_email_settings()

    def from_app_or_env(app_key: str, env_key: str, db_key: str = "", default: Any = "") -> Any:
        if has_app_context():
            value = current_app.config.get(app_key)
            if value not in (None, ""):
                return value
        env_val = os.environ.get(env_key)
        if env_val not in (None, ""):
            return env_val
        if db_key and db_cfg.get(db_key) not in (None, ""):
            return db_cfg[db_key]
        return default

    return {
        "host":      from_app_or_env("SMTP_HOST", "SMTP_HOST", "smtp_host"),
        "port":      int(from_app_or_env("SMTP_PORT", "SMTP_PORT", "smtp_port", 587)),
        "user":      from_app_or_env("SMTP_USER", "SMTP_USER", "smtp_user"),
        "password":  from_app_or_env("SMTP_PASS", "SMTP_PASS", "smtp_pass"),
        "from":      from_app_or_env("SMTP_FROM", "SMTP_FROM", "smtp_from")
                     or from_app_or_env("SMTP_USER", "SMTP_USER", "smtp_user"),
        "from_name": from_app_or_env("SMTP_FROM_NAME", "SMTP_FROM_NAME", "smtp_from_name"),
        "use_tls":   str(from_app_or_env("SMTP_USE_TLS", "SMTP_USE_TLS", "smtp_use_tls", "true")).strip().lower()
                     not in {"0", "false", "no", "off"},
        "use_ssl":   str(from_app_or_env("SMTP_USE_SSL", "SMTP_USE_SSL", "smtp_use_ssl", "false")).strip().lower()
                     in {"1", "true", "yes", "on"},
    }


def get_imap_config() -> dict[str, Any]:
    """Return IMAP settings from DB → env fallback."""
    db_cfg = _db_email_settings()

    def pick(db_key: str, env_key: str, default: Any = "") -> Any:
        if db_cfg.get(db_key) not in (None, ""):
            return db_cfg[db_key]
        return os.environ.get(env_key, default)

    return {
        "host":     pick("imap_host", "IMAP_HOST"),
        "port":     int(pick("imap_port", "IMAP_PORT", 993)),
        "user":     pick("imap_user", "IMAP_USER"),
        "password": pick("imap_pass", "IMAP_PASS"),
        "ssl":      str(pick("imap_ssl", "IMAP_SSL", "true")).strip().lower()
                    not in {"0", "false", "no", "off"},
    }


def _configured_email_engine_provider() -> str:
    if EmailEngine is None:
        return ""
    try:
        engine = EmailEngine(db_path=_db_path())
        providers = engine.list_provider_configs()
    except Exception:
        return ""
    return providers[0] if providers else ""


def smtp_configured() -> bool:
    cfg = get_smtp_config()
    if cfg["host"] and cfg["from"] and (cfg["password"] or cfg["user"]):
        return True
    return bool(_configured_email_engine_provider())


def _send_via_smtp(recipient: str, subject: str, body_html: str) -> None:
    cfg = get_smtp_config()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg["from_name"], cfg["from"])) if cfg["from_name"] else cfg["from"]
    msg["To"] = recipient
    msg.attach(MIMEText(_preview_text(body_html), "plain"))
    msg.attach(MIMEText(body_html, "html"))

    if cfg["use_ssl"]:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], [recipient], msg.as_string())
        return

    with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
        if cfg["use_tls"]:
            server.starttls()
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from"], [recipient], msg.as_string())


def _send_via_email_engine(recipient: str, subject: str, body_html: str) -> None:
    provider = _configured_email_engine_provider()
    if not provider or EmailEngine is None:
        raise RuntimeError("No email transport configured.")
    engine = EmailEngine(db_path=_db_path())
    engine.send_message(
        provider=provider,
        to_email=recipient,
        subject=subject,
        html_body=body_html,
        text_body=_preview_text(body_html),
    )


def send_email(to: str | list[str], subject: str, body_html: str, event_type: str = "general") -> bool:
    init_notification_tables()
    recipients = [to] if isinstance(to, str) else list(to or [])
    cleaned_recipients = _dedupe_emails(recipients)
    if not cleaned_recipients:
        return _record_skipped_notification(event_type, subject, "No recipient email was available.")

    transport_ready = smtp_configured()
    sent_any = False
    for recipient in cleaned_recipients:
        log_id = _log_notification(event_type, recipient, subject, body_html, "Queued" if transport_ready else "Skipped")
        if not transport_ready:
            _update_notification_status(log_id, "Skipped", "Email transport is not configured.")
            continue
        try:
            cfg = get_smtp_config()
            if cfg["host"] and cfg["from"] and (cfg["password"] or cfg["user"]):
                _send_via_smtp(recipient, subject, body_html)
            else:
                _send_via_email_engine(recipient, subject, body_html)
            _update_notification_status(log_id, "Sent")
            sent_any = True
        except Exception as exc:
            _update_notification_status(log_id, "Failed", str(exc))
    return sent_any


def _lookup(context: dict[str, Any], dotted_key: str) -> Any:
    value: Any = context
    for part in dotted_key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return ""
    return value


def _render_tokens(template_text: str, context: dict[str, Any], *, escape_values: bool) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _lookup(context, key)
        if value is None:
            return ""
        if key.endswith("_html"):
            return str(value)
        text = str(value)
        return html.escape(text, quote=True) if escape_values else text

    return TOKEN_RE.sub(replace, template_text or "")


def render_email(template_name: str, context: dict[str, Any]) -> tuple[str, str]:
    template_path = TEMPLATE_DIR / f"{template_name}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Missing email template: {template_path}")
    subject_template = SUBJECT_TEMPLATES[template_name]
    subject = _render_tokens(subject_template, context, escape_values=False).strip()
    body_html = _render_tokens(template_path.read_text(encoding="utf-8"), context, escape_values=True)
    return subject, body_html


def _setting_value(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    try:
        row = conn.execute("SELECT value FROM tms_settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    return (row["value"] if row else default) or default


def _company_name(conn: sqlite3.Connection) -> str:
    return _setting_value(conn, "company_name", "TMS Master")


def _base_url() -> str:
    if has_app_context():
        configured = current_app.config.get("BASE_URL")
        if configured:
            return str(configured).rstrip("/")
    return str(os.environ.get("BASE_URL") or "").rstrip("/")


def _absolute_url(path: str) -> str:
    base_url = _base_url()
    clean_path = str(path or "")
    if not base_url or not clean_path:
        return ""
    if not clean_path.startswith("/"):
        clean_path = f"/{clean_path}"
    return f"{base_url}{clean_path}"


def _lane_label(shipment: dict[str, Any]) -> str:
    origin = (shipment.get("origin_port") or "Origin TBD").strip()
    destination = (shipment.get("destination_port") or "Destination TBD").strip()
    return f"{origin} -> {destination}"


def _default_customer_name(shipment: dict[str, Any]) -> str:
    return (
        shipment.get("customer_name")
        or shipment.get("shipper_name")
        or shipment.get("consignee_name")
        or "Valued Customer"
    )


def _resolve_customer_contact(conn: sqlite3.Connection, shipment_ref: str) -> dict[str, str]:
    normalized_ref = (shipment_ref or "").strip()
    if not normalized_ref:
        return {}

    try:
        order_row = conn.execute(
            """
            SELECT customer_name, customer_email
            FROM customer_orders
            WHERE shipment_ref = ? AND COALESCE(TRIM(customer_email), '') <> ''
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (normalized_ref,),
        ).fetchone()
    except sqlite3.OperationalError:
        order_row = None
    if order_row:
        return {
            "name": order_row["customer_name"] or "",
            "email": order_row["customer_email"] or "",
        }

    try:
        portal_row = conn.execute(
            """
            SELECT customer_name, email
            FROM portal_tokens
            WHERE COALESCE(TRIM(email), '') <> ''
              AND shipment_refs LIKE ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (f'%"{normalized_ref}"%',),
        ).fetchone()
    except sqlite3.OperationalError:
        portal_row = None
    if portal_row:
        return {
            "name": portal_row["customer_name"] or "",
            "email": portal_row["email"] or "",
        }

    try:
        auto_invoice_row = conn.execute(
            """
            SELECT customer_name, customer_email
            FROM auto_invoices
            WHERE shipment_ref = ? AND COALESCE(TRIM(customer_email), '') <> ''
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (normalized_ref,),
        ).fetchone()
    except sqlite3.OperationalError:
        auto_invoice_row = None
    if auto_invoice_row:
        return {
            "name": auto_invoice_row["customer_name"] or "",
            "email": auto_invoice_row["customer_email"] or "",
        }

    return {}


def _load_shipment_context(conn: sqlite3.Connection, shipment_ref: str) -> dict[str, Any] | None:
    shipment_row = conn.execute(
        "SELECT * FROM shipments WHERE shipment_ref = ?",
        (shipment_ref,),
    ).fetchone()
    if not shipment_row:
        return None

    shipment = dict(shipment_row)
    customer = _resolve_customer_contact(conn, shipment_ref)

    try:
        pod_row = conn.execute(
            "SELECT * FROM pod_records WHERE shipment_ref = ? ORDER BY id DESC LIMIT 1",
            (shipment_ref,),
        ).fetchone()
    except sqlite3.OperationalError:
        pod_row = None

    pod = dict(pod_row) if pod_row else {}
    return {
        "company_name": _company_name(conn),
        "shipment_ref": shipment_ref,
        "customer_name": customer.get("name") or _default_customer_name(shipment),
        "customer_email": customer.get("email", ""),
        "status": shipment.get("status") or "Draft",
        "lane_label": _lane_label(shipment),
        "origin": shipment.get("origin_port") or "-",
        "destination": shipment.get("destination_port") or "-",
        "mode": shipment.get("mode") or "-",
        "carrier_name": shipment.get("carrier_name") or "Carrier pending",
        "cargo_description": shipment.get("cargo_description") or "Freight shipment",
        "equipment": shipment.get("containers") or shipment.get("mode") or "Equipment TBD",
        "etd": shipment.get("etd") or "-",
        "eta": shipment.get("eta") or "-",
        "etd_display": _format_display_date(shipment.get("etd")),
        "eta_display": _format_display_date(shipment.get("eta")),
        "freight_rate_display": _format_currency(shipment.get("freight_rate"), shipment.get("currency") or "USD"),
        "tracking_url": _public_tracking_url(shipment_ref),
        "shipment_url": _absolute_url(f"/tms/shipments/{shipment_ref}"),
        "invoice_url": _absolute_url(f"/tms/shipments/{shipment_ref}/invoice.pdf"),
        "pod_url": _absolute_url(f"/tms/shipments/{shipment_ref}/pod.pdf"),
        "billing_queue_url": _absolute_url("/tms/billing-queue"),
        "delivered_at_display": _format_display_datetime(pod.get("delivered_at")),
        "recipient_name": pod.get("recipient_name") or shipment.get("consignee_name") or "-",
        "pod_notes": pod.get("notes") or "",
        "current_year": str(_utcnow().year),
    }


def _dispatcher_email(explicit_value: str = "") -> str:
    if explicit_value.strip():
        return _normalize_email(explicit_value)
    if has_app_context():
        configured = current_app.config.get("TMS_DISPATCHER_EMAIL")
        if configured:
            return _normalize_email(configured)
    return _normalize_email(os.environ.get("TMS_DISPATCHER_EMAIL") or os.environ.get("DISPATCHER_EMAIL"))


def _accounting_email() -> str:
    if has_app_context():
        configured = current_app.config.get("TMS_ACCOUNTING_EMAIL")
        if configured:
            return _normalize_email(configured)
    return _normalize_email(os.environ.get("TMS_ACCOUNTING_EMAIL") or os.environ.get("ACCOUNTING_EMAIL"))


def _public_tracking_secret_key() -> str:
    if has_app_context():
        configured = current_app.config.get("SECRET_KEY")
        if configured:
            return str(configured)
    return str(os.environ.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY") or "")


def _public_tracking_url(shipment_ref: str) -> str:
    clean_ref = str(shipment_ref or "").strip().upper()
    if not clean_ref:
        return ""
    base_url = _base_url().rstrip("/")
    if not base_url:
        return ""
    secret_key = _public_tracking_secret_key()
    if not secret_key:
        return ""
    token = URLSafeTimedSerializer(secret_key, salt=PUBLIC_TRACKING_TOKEN_SALT).dumps(clean_ref)
    return f"{base_url}/track/{clean_ref}?token={quote(token, safe='')}"


def notify_shipment_created(shipment_ref: str, customer_email: str = "") -> bool:
    init_notification_tables()
    ensure_notification_scheduler()
    conn = get_db()
    try:
        context = _load_shipment_context(conn, shipment_ref)
    finally:
        conn.close()
    if not context:
        return _record_skipped_notification("shipment_created", f"Shipment {shipment_ref} confirmed", "Shipment was not found.")
    recipient = _normalize_email(customer_email) or context["customer_email"]
    if not recipient:
        return _record_skipped_notification("shipment_created", f"Shipment {shipment_ref} confirmed", "No customer email found.", context["shipment_ref"])
    subject, body = render_email("shipment_created", context)
    return send_email(recipient, subject, body, "shipment_created")


def notify_shipment_status_change(shipment_ref: str, new_status: str, customer_email: str = "") -> bool:
    normalized_status = (new_status or "").strip()
    template_name = {
        "In Transit": "status_in_transit",
        "Delivered": "status_delivered",
    }.get(normalized_status)
    if not template_name:
        return False

    init_notification_tables()
    ensure_notification_scheduler()
    conn = get_db()
    try:
        context = _load_shipment_context(conn, shipment_ref)
    finally:
        conn.close()
    if not context:
        return _record_skipped_notification("status_change", f"Shipment {shipment_ref} update", "Shipment was not found.")

    recipient = _normalize_email(customer_email) or context["customer_email"]
    if not recipient:
        return _record_skipped_notification("status_change", f"Shipment {shipment_ref} update", "No customer email found.", context["shipment_ref"])

    context["status"] = normalized_status
    subject, body = render_email(template_name, context)
    event_type = "status_in_transit" if normalized_status == "In Transit" else "status_delivered"
    return send_email(recipient, subject, body, event_type)


def notify_pod_received(shipment_ref: str, dispatcher_email: str = "") -> bool:
    init_notification_tables()
    ensure_notification_scheduler()
    conn = get_db()
    try:
        context = _load_shipment_context(conn, shipment_ref)
    finally:
        conn.close()
    if not context:
        return _record_skipped_notification("pod_received", f"POD received for {shipment_ref}", "Shipment was not found.")

    recipients = _dedupe_emails([_dispatcher_email(dispatcher_email), _accounting_email()])
    if not recipients:
        return _record_skipped_notification("pod_received", f"POD received for {shipment_ref}", "Dispatcher/accounting emails are not configured.", shipment_ref)

    subject, body = render_email("pod_received", context)
    return send_email(recipients, subject, body, "pod_received")


def notify_invoice_generated(
    *,
    invoice_id: int | None = None,
    invoice_number: str = "",
    shipment_ref: str = "",
    customer_email: str = "",
    amount: Any = 0,
    currency: str = "USD",
    customer_name: str = "",
    due_date: str = "",
    invoice_url: str = "",
) -> bool:
    init_notification_tables()
    ensure_notification_scheduler()

    normalized_invoice_number = (invoice_number or "").strip()
    normalized_shipment_ref = (shipment_ref or "").strip()
    normalized_customer_email = _normalize_email(customer_email)
    normalized_customer_name = (customer_name or "").strip()
    normalized_due_date = (due_date or "").strip()
    normalized_invoice_url = (invoice_url or "").strip()
    normalized_currency = (currency or "USD").upper()

    conn = get_db()
    try:
        context: dict[str, Any] = {
            "company_name": _company_name(conn),
            "invoice_number": normalized_invoice_number,
            "shipment_ref": normalized_shipment_ref,
            "customer_name": normalized_customer_name or "Valued Customer",
            "customer_email": normalized_customer_email,
            "amount_display": _format_currency(amount, normalized_currency),
            "due_date_display": _format_display_date(normalized_due_date),
            "invoice_url": normalized_invoice_url,
            "current_year": str(_utcnow().year),
        }

        if invoice_id:
            invoice_row = conn.execute(
                "SELECT * FROM customer_invoices WHERE id = ?",
                (invoice_id,),
            ).fetchone()
            if invoice_row:
                invoice = dict(invoice_row)
                normalized_shipment_ref = normalized_shipment_ref or invoice.get("shipment_ref", "")
                context.update(
                    {
                        "invoice_number": f"CINV-{int(invoice['id']):05d}",
                        "shipment_ref": normalized_shipment_ref,
                        "amount_display": _format_currency(invoice.get("amount"), invoice.get("currency") or "USD"),
                        "due_date_display": _format_display_date(invoice.get("due_date")),
                        "invoice_url": normalized_invoice_url or _absolute_url(f"/tms/invoices/{int(invoice['id'])}/pdf"),
                    }
                )
                shipment_context = _load_shipment_context(conn, normalized_shipment_ref) if normalized_shipment_ref else None
                if shipment_context:
                    context["customer_name"] = normalized_customer_name or shipment_context["customer_name"]
                    context["customer_email"] = normalized_customer_email or shipment_context["customer_email"]
        elif normalized_shipment_ref:
            shipment_context = _load_shipment_context(conn, normalized_shipment_ref)
            if shipment_context:
                context["customer_name"] = normalized_customer_name or shipment_context["customer_name"]
                context["customer_email"] = normalized_customer_email or shipment_context["customer_email"]
                context["invoice_url"] = normalized_invoice_url or shipment_context["invoice_url"]
    finally:
        conn.close()

    if not context["invoice_number"]:
        context["invoice_number"] = normalized_invoice_number or "Invoice"
    if not context["invoice_url"] and context["shipment_ref"]:
        context["invoice_url"] = _absolute_url(f"/tms/shipments/{context['shipment_ref']}/invoice.pdf")

    recipient = normalized_customer_email or context.get("customer_email", "")
    if not recipient:
        subject = _render_tokens(SUBJECT_TEMPLATES["invoice_generated"], context, escape_values=False)
        return _record_skipped_notification("invoice_generated", subject, "No customer email found.", context.get("shipment_ref", ""))

    subject, body = render_email("invoice_generated", context)
    return send_email(recipient, subject, body, "invoice_generated")


def notify_invoice_sent(invoice_number: str, customer_email: str, amount: float) -> bool:
    return notify_invoice_generated(
        invoice_number=invoice_number,
        customer_email=customer_email,
        amount=amount,
    )


def _campaign_exists(conn: sqlite3.Connection, campaign_type: str, campaign_key: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM notification_campaigns
        WHERE campaign_type = ? AND campaign_key = ?
        LIMIT 1
        """,
        (campaign_type, campaign_key),
    ).fetchone()
    return bool(row)


def _record_campaign(conn: sqlite3.Connection, campaign_type: str, campaign_key: str, details: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO notification_campaigns (campaign_type, campaign_key, details_json)
        VALUES (?, ?, ?)
        """,
        (campaign_type, campaign_key, json.dumps(details, sort_keys=True)),
    )


def _queue_scheduled_notification(
    conn: sqlite3.Connection,
    notification_type: str,
    entity_key: str,
    scheduled_for: datetime,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO scheduled_notifications
            (notification_type, entity_key, payload_json, scheduled_for, status)
        VALUES (?, ?, ?, ?, 'Queued')
        """,
        (notification_type, entity_key, json.dumps(payload, sort_keys=True), _sql_datetime(scheduled_for)),
    )


def _carrier_is_verified(carrier: dict[str, Any], today: date) -> bool:
    safety = (carrier.get("safety_rating") or "").strip()
    auth_status = (carrier.get("auth_status") or "").strip().lower()
    insurance_status = (carrier.get("insurance_status") or "").strip().lower()
    insurance_expires_at = _parse_date(carrier.get("insurance_expires_at"))

    if safety not in ACCEPTED_SAFETY_RATINGS:
        return False
    if not auth_status or any(term in auth_status for term in REJECTED_AUTH_KEYWORDS):
        return False
    if not any(term in auth_status for term in ACCEPTED_AUTH_KEYWORDS):
        return False
    if not insurance_status or any(term in insurance_status for term in REJECTED_INSURANCE_KEYWORDS):
        return False
    if not any(term in insurance_status for term in ACCEPTED_INSURANCE_KEYWORDS):
        return False
    if insurance_expires_at and insurance_expires_at < today:
        return False
    return True


def _verified_carriers(conn: sqlite3.Connection, today: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM tms_carriers
        WHERE active = 1
          AND COALESCE(TRIM(contact_email), '') <> ''
        ORDER BY name COLLATE NOCASE ASC
        """
    ).fetchall()
    return [dict(row) for row in rows if _carrier_is_verified(dict(row), today)]


def _next_month_shipments(conn: sqlite3.Connection, target_month: date) -> list[dict[str, Any]]:
    target_prefix = target_month.strftime("%Y-%m")
    rows = conn.execute(
        """
        SELECT *
        FROM shipments
        WHERE COALESCE(status, 'Draft') NOT IN ('Delivered', 'Cancelled')
          AND (
            (COALESCE(TRIM(etd), '') <> '' AND substr(etd, 1, 7) = ?)
            OR
            (COALESCE(TRIM(etd), '') = '' AND COALESCE(TRIM(eta), '') <> '' AND substr(eta, 1, 7) = ?)
          )
        ORDER BY COALESCE(NULLIF(etd, ''), NULLIF(eta, ''), created_at) ASC, shipment_ref ASC
        """,
        (target_prefix, target_prefix),
    ).fetchall()
    return [dict(row) for row in rows]


def _monthly_tender_notes(campaign_key: str) -> str:
    return f"[monthly-rate:{campaign_key}] Auto-created on the 26th for next-month lane pricing."


def _existing_monthly_tender(conn: sqlite3.Connection, shipment_id: int, campaign_key: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM tenders
        WHERE shipment_id = ?
          AND notes = ?
        LIMIT 1
        """,
        (shipment_id, _monthly_tender_notes(campaign_key)),
    ).fetchone()
    return bool(row)


def _generate_tender_token(conn: sqlite3.Connection) -> str:
    while True:
        token = secrets.token_urlsafe(18)
        row = conn.execute(
            "SELECT 1 FROM tender_responses WHERE token = ? LIMIT 1",
            (token,),
        ).fetchone()
        if not row:
            return token


def _rate_request_context(
    company_name: str,
    shipment: dict[str, Any],
    carrier: dict[str, Any],
    token: str,
    deadline_at: datetime,
    target_month: date,
) -> dict[str, Any]:
    quote_deadline = _sql_datetime(deadline_at)
    return {
        "company_name": company_name,
        "carrier_name": carrier.get("name") or "Carrier",
        "shipment_ref": shipment.get("shipment_ref") or "",
        "lane_label": _lane_label(shipment),
        "origin": shipment.get("origin_port") or "-",
        "destination": shipment.get("destination_port") or "-",
        "mode": shipment.get("mode") or "-",
        "equipment": shipment.get("containers") or shipment.get("mode") or "Equipment TBD",
        "cargo_description": shipment.get("cargo_description") or "Freight shipment",
        "pickup_window": _format_display_date(shipment.get("etd")),
        "delivery_window": _format_display_date(shipment.get("eta")),
        "target_month_label": target_month.strftime("%B %Y"),
        "quote_deadline": _format_display_datetime(quote_deadline),
        "response_url": _absolute_url(f"/tms/tender/{token}/respond"),
        "shipment_url": _absolute_url(f"/tms/shipments/{shipment.get('shipment_ref')}"),
        "current_year": str(_utcnow().year),
    }


def _create_monthly_tenders(
    conn: sqlite3.Connection,
    shipments: list[dict[str, Any]],
    carriers: list[dict[str, Any]],
    campaign_key: str,
    deadline_at: datetime,
) -> list[dict[str, Any]]:
    outbound_messages: list[dict[str, Any]] = []
    notes = _monthly_tender_notes(campaign_key)

    for shipment in shipments:
        shipment_id = int(shipment["id"])
        if _existing_monthly_tender(conn, shipment_id, campaign_key):
            continue

        cursor = conn.execute(
            """
            INSERT INTO tenders (shipment_id, deadline_at, notes, status, updated_at)
            VALUES (?, ?, ?, 'Open', CURRENT_TIMESTAMP)
            """,
            (shipment_id, _sql_datetime(deadline_at), notes),
        )
        tender_id = int(cursor.lastrowid)

        for carrier in carriers:
            token = _generate_tender_token(conn)
            response_cursor = conn.execute(
                """
                INSERT INTO tender_responses
                    (tender_id, carrier_id, token, response_status, updated_at)
                VALUES (?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
                """,
                (tender_id, int(carrier["id"]), token),
            )
            response_id = int(response_cursor.lastrowid)
            outbound_messages.append(
                {
                    "response_id": response_id,
                    "shipment": shipment,
                    "carrier": carrier,
                    "token": token,
                }
            )

        conn.execute(
            """
            INSERT INTO shipment_events (shipment_id, event_type, description)
            VALUES (?, 'Monthly Rate Request', ?)
            """,
            (
                shipment_id,
                f"Next-month rate request sent to {len(carriers)} verified carriers.",
            ),
        )

    return outbound_messages


def run_monthly_rate_request_cycle(reference_time: datetime | None = None) -> int:
    init_notification_tables()

    now = reference_time or _utcnow()
    if now.day != 26:
        return 0

    first_of_next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    campaign_key = first_of_next_month.strftime("%Y-%m")
    conn = get_db()
    try:
        if _campaign_exists(conn, "monthly_rate_request", campaign_key):
            return 0

        shipments = _next_month_shipments(conn, first_of_next_month.date())
        carriers = _verified_carriers(conn, now.date())
        if not shipments or not carriers:
            return 0

        deadline_at = now + timedelta(hours=48)
        company_name = _company_name(conn)
        outbound_messages = _create_monthly_tenders(
            conn,
            shipments,
            carriers,
            campaign_key,
            deadline_at,
        )
        details = {
            "target_month": campaign_key,
            "lane_count": len(shipments),
            "carrier_count": len(carriers),
            "email_count": len(outbound_messages),
        }
        _record_campaign(conn, "monthly_rate_request", campaign_key, details)

        for message in outbound_messages:
            _queue_scheduled_notification(
                conn,
                "rate_request_follow_up",
                str(message["response_id"]),
                now + timedelta(hours=24),
                {
                    "response_id": message["response_id"],
                    "shipment_ref": message["shipment"]["shipment_ref"],
                },
            )
        conn.commit()
    finally:
        conn.close()

    sent_count = 0
    for message in outbound_messages:
        context = _rate_request_context(
            company_name,
            message["shipment"],
            message["carrier"],
            message["token"],
            deadline_at,
            first_of_next_month.date(),
        )
        subject, body = render_email("monthly_rate_request", context)
        if send_email(message["carrier"]["contact_email"], subject, body, "rate_request_monthly"):
            sent_count += 1
    return sent_count


def _send_rate_request_follow_up(payload: dict[str, Any]) -> tuple[str, str]:
    response_id = int(payload.get("response_id") or 0)
    if response_id <= 0:
        return "Cancelled", "Tender response was not available."

    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT
                tr.id,
                tr.token,
                tr.response_status,
                t.deadline_at,
                s.shipment_ref,
                s.origin_port,
                s.destination_port,
                s.mode,
                s.containers,
                s.cargo_description,
                s.etd,
                s.eta,
                tc.name AS carrier_name,
                tc.contact_email
            FROM tender_responses tr
            JOIN tenders t ON t.id = tr.tender_id
            JOIN shipments s ON s.id = t.shipment_id
            JOIN tms_carriers tc ON tc.id = tr.carrier_id
            WHERE tr.id = ?
            """,
            (response_id,),
        ).fetchone()
        company_name = _company_name(conn)
    finally:
        conn.close()

    if not row:
        return "Cancelled", "Tender response no longer exists."

    response = dict(row)
    if response.get("response_status") != "Pending":
        return "Cancelled", "Rate response was already received."

    context = {
        "company_name": company_name,
        "carrier_name": response.get("carrier_name") or "Carrier",
        "shipment_ref": response.get("shipment_ref") or "",
        "lane_label": f"{response.get('origin_port') or '-'} -> {response.get('destination_port') or '-'}",
        "origin": response.get("origin_port") or "-",
        "destination": response.get("destination_port") or "-",
        "mode": response.get("mode") or "-",
        "equipment": response.get("containers") or response.get("mode") or "Equipment TBD",
        "cargo_description": response.get("cargo_description") or "Freight shipment",
        "pickup_window": _format_display_date(response.get("etd")),
        "delivery_window": _format_display_date(response.get("eta")),
        "quote_deadline": _format_display_datetime(response.get("deadline_at")),
        "response_url": _absolute_url(f"/tms/tender/{response.get('token')}/respond"),
        "shipment_url": _absolute_url(f"/tms/shipments/{response.get('shipment_ref')}"),
        "current_year": str(_utcnow().year),
    }
    subject, body = render_email("rate_request_follow_up", context)
    success = send_email(response.get("contact_email") or "", subject, body, "rate_request_follow_up")
    return ("Sent", "") if success else ("Failed", "Follow-up email could not be delivered.")


def process_due_scheduled_notifications(limit: int = 25) -> int:
    init_notification_tables()
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM scheduled_notifications
            WHERE status = 'Queued'
              AND scheduled_for <= ?
            ORDER BY scheduled_for ASC, id ASC
            LIMIT ?
            """,
            (_sql_datetime(), int(limit)),
        ).fetchall()
    finally:
        conn.close()

    processed = 0
    for row in rows:
        payload = json.loads(row["payload_json"] or "{}")
        if row["notification_type"] != "rate_request_follow_up":
            status, error = "Cancelled", "Unsupported scheduled notification."
        else:
            status, error = _send_rate_request_follow_up(payload)

        conn = get_db()
        try:
            conn.execute(
                """
                UPDATE scheduled_notifications
                SET status = ?, error = ?, sent_at = CASE WHEN ? = 'Sent' THEN CURRENT_TIMESTAMP ELSE sent_at END
                WHERE id = ?
                """,
                (status, error, status, int(row["id"])),
            )
            conn.commit()
        finally:
            conn.close()
        processed += 1
    return processed


def run_notification_jobs() -> None:
    process_due_scheduled_notifications()
    run_monthly_rate_request_cycle()
    try:
        from .rate_reply_parser import process_pending_replies
        process_pending_replies()
    except Exception:
        pass


def _notification_scheduler_enabled() -> bool:
    disabled = os.environ.get("TMS_DISABLE_NOTIFICATION_SCHEDULER", "").strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return False
    enabled = os.environ.get("TMS_ENABLE_NOTIFICATION_SCHEDULER", "").strip().lower()
    if enabled in {"1", "true", "yes", "on"}:
        return True
    if has_app_context():
        env_name = str(current_app.config.get("TMS_ENV", os.environ.get("TMS_ENV", "development")) or "").strip().lower()
    else:
        env_name = str(os.environ.get("TMS_ENV", "development") or "").strip().lower()
    return env_name != "production"


def ensure_notification_scheduler() -> None:
    if has_app_context() and current_app.config.get("TESTING"):
        return
    if not _notification_scheduler_enabled():
        return

    global SCHEDULER_THREAD
    with SCHEDULER_LOCK:
        if SCHEDULER_THREAD and SCHEDULER_THREAD.is_alive():
            return
        SCHEDULER_STOP.clear()

        def loop() -> None:
            while not SCHEDULER_STOP.is_set():
                try:
                    run_notification_jobs()
                except Exception:
                    pass
                try:
                    from .workflow_engine import run_scheduled_checks
                    run_scheduled_checks()
                except Exception:
                    pass
                SCHEDULER_STOP.wait(SCHEDULER_POLL_SECONDS)

        SCHEDULER_THREAD = threading.Thread(
            target=loop,
            name="tms-notification-scheduler",
            daemon=True,
        )
        SCHEDULER_THREAD.start()


def get_notification_log(limit: int = 50) -> list[dict[str, Any]]:
    init_notification_tables()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM notification_log ORDER BY created_at DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
