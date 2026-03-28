from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import html
import imaplib
import json
import logging
import os
import re
import smtplib
import sqlite3
import ssl
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_policy
from email.utils import format_datetime, formataddr, make_msgid, parseaddr
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import requests

try:
    from .tms_db import TMS_DB as DEFAULT_DB_PATH
except Exception:
    DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "tms.db")


log = logging.getLogger(__name__)

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE_DIR = MODULE_DIR.parent / "templates" / "tms"
DEFAULT_TRACKING_BASE_URL = "http://localhost:5000/tms/email"
OPEN_PIXEL_GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==")
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_MESSAGE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")
HREF_RE = re.compile(r"""href=(["'])(.*?)\1""", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
DEFAULT_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
DEFAULT_OUTLOOK_SCOPES = [
    "offline_access",
    "Mail.Send",
    "Mail.Read",
    "User.Read",
]


class EmailEngineError(RuntimeError):
    pass


class _SQLiteConnectionWrapper:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> sqlite3.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
        return False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_iso() -> str:
    return _utcnow().replace(microsecond=0).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_email(address: str | None) -> str:
    return parseaddr(address or "")[1].strip().lower()


def _text_from_html(body: str) -> str:
    if not body:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", body)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()


def _lookup(context: dict[str, Any], dotted_key: str) -> Any:
    value: Any = context
    for part in dotted_key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return ""
    return value


def _render_tokens(template_text: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = _lookup(context, match.group(1))
        return "" if value is None else str(value)

    return PLACEHOLDER_RE.sub(replace, template_text or "")


def _smtp_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class EmailEngine:
    def __init__(
        self,
        db_path: str | os.PathLike[str] | None = None,
        template_dir: str | os.PathLike[str] | None = None,
        tracking_base_url: str = DEFAULT_TRACKING_BASE_URL,
        poll_seconds: int = 30,
    ) -> None:
        self.db_path = str(Path(db_path or DEFAULT_DB_PATH))
        self.template_dir = Path(template_dir or DEFAULT_TEMPLATE_DIR)
        self.tracking_base_url = tracking_base_url.rstrip("/")
        self.poll_seconds = max(5, int(poll_seconds))
        self._scheduler_lock = threading.Lock()
        self._scheduler_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()
        self.set_setting("tracking_base_url", self.tracking_base_url)

    def _connect(self) -> _SQLiteConnectionWrapper:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return _SQLiteConnectionWrapper(conn)

    @contextmanager
    def _db(self):
        with self._connect() as conn:
            yield conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS email_provider_configs (
                    provider TEXT PRIMARY KEY,
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_engine_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_templates (
                    template_name TEXT PRIMARY KEY,
                    subject_template TEXT NOT NULL,
                    html_template TEXT NOT NULL,
                    text_template TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    to_email TEXT NOT NULL,
                    from_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    html_body TEXT DEFAULT '',
                    text_body TEXT DEFAULT '',
                    template_name TEXT DEFAULT '',
                    tracking_id TEXT UNIQUE,
                    provider_message_id TEXT DEFAULT '',
                    provider_thread_id TEXT DEFAULT '',
                    provider_conversation_id TEXT DEFAULT '',
                    internet_message_id TEXT DEFAULT '',
                    last_error TEXT DEFAULT '',
                    open_count INTEGER DEFAULT 0,
                    click_count INTEGER DEFAULT 0,
                    reply_count INTEGER DEFAULT 0,
                    last_opened_at TEXT DEFAULT '',
                    last_clicked_at TEXT DEFAULT '',
                    last_replied_at TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}',
                    sent_at TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    tracking_id TEXT DEFAULT '',
                    event_type TEXT NOT NULL,
                    event_value TEXT DEFAULT '',
                    source_url TEXT DEFAULT '',
                    event_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (message_id) REFERENCES email_messages(id)
                );

                CREATE TABLE IF NOT EXISTS email_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    to_email TEXT NOT NULL,
                    template_name TEXT DEFAULT '',
                    subject TEXT DEFAULT '',
                    html_body TEXT DEFAULT '',
                    text_body TEXT DEFAULT '',
                    context_json TEXT DEFAULT '{}',
                    metadata_json TEXT DEFAULT '{}',
                    reply_to TEXT DEFAULT '',
                    track_opens INTEGER DEFAULT 1,
                    track_clicks INTEGER DEFAULT 1,
                    scheduled_for TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    last_error TEXT DEFAULT '',
                    sent_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (sent_message_id) REFERENCES email_messages(id)
                );

                CREATE TABLE IF NOT EXISTS email_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    provider_message_id TEXT NOT NULL,
                    source_message_id INTEGER,
                    reply_from TEXT DEFAULT '',
                    subject TEXT DEFAULT '',
                    body_preview TEXT DEFAULT '',
                    received_at TEXT DEFAULT '',
                    raw_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(provider, provider_message_id),
                    FOREIGN KEY (source_message_id) REFERENCES email_messages(id)
                );

                CREATE INDEX IF NOT EXISTS idx_email_messages_tracking_id ON email_messages(tracking_id);
                CREATE INDEX IF NOT EXISTS idx_email_messages_provider_thread ON email_messages(provider, provider_thread_id);
                CREATE INDEX IF NOT EXISTS idx_email_messages_provider_conv ON email_messages(provider, provider_conversation_id);
                CREATE INDEX IF NOT EXISTS idx_email_messages_internet_id ON email_messages(internet_message_id);
                CREATE INDEX IF NOT EXISTS idx_email_schedules_due ON email_schedules(status, scheduled_for);
                """
            )
            conn.commit()

    def set_setting(self, key: str, value: str) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_engine_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, value, now),
            )
            conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM email_engine_settings WHERE key=?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def save_provider_config(self, provider: str, config: dict[str, Any]) -> dict[str, Any]:
        provider = provider.strip().lower()
        payload = dict(config)
        payload["provider"] = provider
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_provider_configs (provider, config_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    config_json=excluded.config_json,
                    updated_at=excluded.updated_at
                """,
                (provider, _json_dumps(payload), now),
            )
            conn.commit()
        return payload

    def get_provider_config(self, provider: str, required: bool = True) -> dict[str, Any]:
        provider = provider.strip().lower()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT config_json FROM email_provider_configs WHERE provider=?",
                (provider,),
            ).fetchone()
        if not row:
            if required:
                raise EmailEngineError(f"No provider config saved for '{provider}'.")
            return {}
        return _json_loads(row["config_json"])

    def list_provider_configs(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT provider FROM email_provider_configs ORDER BY provider"
            ).fetchall()
        return [row["provider"] for row in rows]

    @staticmethod
    def build_gmail_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> str:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or DEFAULT_GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{GMAIL_AUTH_URL}?{urlencode(params)}"

    @staticmethod
    def build_outlook_authorization_url(
        client_id: str,
        redirect_uri: str,
        state: str,
        tenant: str = "common",
        scopes: list[str] | None = None,
    ) -> str:
        auth_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or DEFAULT_OUTLOOK_SCOPES),
            "response_mode": "query",
            "state": state,
        }
        return f"{auth_url}?{urlencode(params)}"

    def exchange_gmail_code(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        from_email: str,
        from_name: str = "",
        scopes: list[str] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        response = requests.post(
            GMAIL_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        token_data = response.json()
        config = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token_data.get("refresh_token", ""),
            "access_token": token_data.get("access_token", ""),
            "token_expiry": self._token_expiry(token_data.get("expires_in")),
            "token_uri": GMAIL_TOKEN_URL,
            "auth_uri": GMAIL_AUTH_URL,
            "scopes": scopes or DEFAULT_GMAIL_SCOPES,
            "from_email": from_email,
            "from_name": from_name,
            "redirect_uri": redirect_uri,
        }
        self.save_provider_config("gmail", config)
        return config

    def exchange_outlook_code(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        from_email: str,
        from_name: str = "",
        tenant: str = "common",
        scopes: list[str] | None = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        response = requests.post(
            token_url,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": " ".join(scopes or DEFAULT_OUTLOOK_SCOPES),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        token_data = response.json()
        config = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token_data.get("refresh_token", ""),
            "access_token": token_data.get("access_token", ""),
            "token_expiry": self._token_expiry(token_data.get("expires_in")),
            "token_uri": token_url,
            "tenant": tenant,
            "scopes": scopes or DEFAULT_OUTLOOK_SCOPES,
            "from_email": from_email,
            "from_name": from_name,
            "redirect_uri": redirect_uri,
        }
        self.save_provider_config("outlook", config)
        return config

    def connect_gmail(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        from_email: str,
        from_name: str = "",
        redirect_uri: str = "",
        scopes: list[str] | None = None,
        access_token: str = "",
        token_expiry: str = "",
    ) -> dict[str, Any]:
        return self.save_provider_config(
            "gmail",
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "from_email": from_email,
                "from_name": from_name,
                "redirect_uri": redirect_uri,
                "scopes": scopes or DEFAULT_GMAIL_SCOPES,
                "access_token": access_token,
                "token_expiry": token_expiry,
                "token_uri": GMAIL_TOKEN_URL,
                "auth_uri": GMAIL_AUTH_URL,
            },
        )

    def connect_outlook(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        from_email: str,
        from_name: str = "",
        tenant: str = "common",
        redirect_uri: str = "",
        scopes: list[str] | None = None,
        access_token: str = "",
        token_expiry: str = "",
    ) -> dict[str, Any]:
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        return self.save_provider_config(
            "outlook",
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "from_email": from_email,
                "from_name": from_name,
                "tenant": tenant,
                "redirect_uri": redirect_uri,
                "scopes": scopes or DEFAULT_OUTLOOK_SCOPES,
                "access_token": access_token,
                "token_expiry": token_expiry,
                "token_uri": token_url,
            },
        )

    def connect_smtp(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str = "",
        use_tls: bool = True,
        use_ssl: bool = False,
        timeout: int = 30,
        reply_to: str = "",
        imap_host: str = "",
        imap_port: int = 993,
        imap_username: str = "",
        imap_password: str = "",
        imap_ssl: bool = True,
    ) -> dict[str, Any]:
        return self.save_provider_config(
            "smtp",
            {
                "host": host,
                "port": int(port),
                "username": username,
                "password": password,
                "from_email": from_email,
                "from_name": from_name,
                "use_tls": bool(use_tls),
                "use_ssl": bool(use_ssl),
                "timeout": int(timeout),
                "reply_to": reply_to,
                "imap_host": imap_host,
                "imap_port": int(imap_port),
                "imap_username": imap_username,
                "imap_password": imap_password,
                "imap_ssl": bool(imap_ssl),
            },
        )

    def save_template(
        self,
        template_name: str,
        subject_template: str,
        html_template: str,
        text_template: str = "",
    ) -> None:
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_templates (
                    template_name, subject_template, html_template, text_template, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(template_name) DO UPDATE SET
                    subject_template=excluded.subject_template,
                    html_template=excluded.html_template,
                    text_template=excluded.text_template,
                    updated_at=excluded.updated_at
                """,
                (template_name, subject_template, html_template, text_template, now),
            )
            conn.commit()

    def get_template(self, template_name: str) -> dict[str, str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT subject_template, html_template, text_template
                FROM email_templates
                WHERE template_name=?
                """,
                (template_name,),
            ).fetchone()
        if row:
            return {
                "subject": row["subject_template"],
                "html": row["html_template"],
                "text": row["text_template"],
            }

        html_path = self.template_dir / f"{template_name}.html"
        subject_path = self.template_dir / f"{template_name}.subject.txt"
        text_path = self.template_dir / f"{template_name}.txt"
        if not html_path.exists():
            raise EmailEngineError(f"Template '{template_name}' was not found.")
        subject_template = subject_path.read_text(encoding="utf-8").strip() if subject_path.exists() else ""
        text_template = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        return {
            "subject": subject_template,
            "html": html_path.read_text(encoding="utf-8"),
            "text": text_template,
        }

    def list_templates(self) -> list[str]:
        template_names: set[str] = set()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT template_name FROM email_templates ORDER BY template_name"
            ).fetchall()
        template_names.update(row["template_name"] for row in rows)
        template_names.update(path.stem for path in self.template_dir.glob("*.html"))
        return sorted(template_names)

    def render_template(
        self,
        template_name: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        template = self.get_template(template_name)
        template_context = context or {}
        rendered = {
            "subject": _render_tokens(template.get("subject", ""), template_context),
            "html": _render_tokens(template.get("html", ""), template_context),
            "text": _render_tokens(template.get("text", ""), template_context),
        }
        if not rendered["text"] and rendered["html"]:
            rendered["text"] = _text_from_html(rendered["html"])
        return rendered

    def load_user_config(self, config_path: str | os.PathLike[str]) -> dict[str, Any]:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        providers = data.get("providers", {})
        if "tracking_base_url" in data:
            self.tracking_base_url = str(data["tracking_base_url"]).rstrip("/")
            self.set_setting("tracking_base_url", self.tracking_base_url)
        for name, provider_config in providers.items():
            self.save_provider_config(name, provider_config)
        for name, template in data.get("templates", {}).items():
            self.save_template(
                name,
                template.get("subject", ""),
                template.get("html", ""),
                template.get("text", ""),
            )
        return data

    def build_open_url(self, tracking_id: str) -> str:
        base = self.get_setting("tracking_base_url", self.tracking_base_url).rstrip("/")
        return f"{base}/open/{tracking_id}.gif"

    def build_click_url(self, tracking_id: str, destination_url: str) -> str:
        base = self.get_setting("tracking_base_url", self.tracking_base_url).rstrip("/")
        return f"{base}/click/{tracking_id}?url={quote(destination_url, safe='')}"

    def instrument_html(
        self,
        html_body: str,
        tracking_id: str,
        track_open: bool = True,
        track_clicks: bool = True,
    ) -> str:
        instrumented = html_body or ""
        if track_clicks:
            instrumented = self._rewrite_links(instrumented, tracking_id)
        if track_open:
            pixel = (
                f'<img src="{html.escape(self.build_open_url(tracking_id), quote=True)}" '
                'width="1" height="1" alt="" '
                'style="display:block;border:0;outline:none;text-decoration:none;" />'
            )
            if "</body>" in instrumented.lower():
                instrumented = re.sub(
                    r"(?i)</body>",
                    pixel + "</body>",
                    instrumented,
                    count=1,
                )
            else:
                instrumented = instrumented + pixel
        return instrumented

    def _rewrite_links(self, html_body: str, tracking_id: str) -> str:
        def replace(match: re.Match[str]) -> str:
            quote_char = match.group(1)
            href = match.group(2)
            lowered = href.lower()
            if not lowered.startswith(("http://", "https://")):
                return match.group(0)
            if f"/click/{tracking_id}" in lowered:
                return match.group(0)
            tracked_url = html.escape(self.build_click_url(tracking_id, href), quote=True)
            return f"href={quote_char}{tracked_url}{quote_char}"

        return HREF_RE.sub(replace, html_body)

    def schedule_email(
        self,
        *,
        provider: str,
        to_email: str,
        scheduled_for: datetime | str,
        template_name: str = "",
        subject: str = "",
        html_body: str = "",
        text_body: str = "",
        context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        reply_to: str = "",
        track_opens: bool = True,
        track_clicks: bool = True,
    ) -> int:
        run_at = _parse_dt(scheduled_for)
        if not run_at:
            raise EmailEngineError("scheduled_for must be an ISO timestamp or datetime.")
        now = _utcnow_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO email_schedules (
                    provider, to_email, template_name, subject, html_body, text_body,
                    context_json, metadata_json, reply_to, track_opens, track_clicks,
                    scheduled_for, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    provider.lower(),
                    to_email,
                    template_name,
                    subject,
                    html_body,
                    text_body,
                    _json_dumps(context),
                    _json_dumps(metadata),
                    reply_to,
                    1 if track_opens else 0,
                    1 if track_clicks else 0,
                    run_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def process_due_scheduled(self, limit: int = 25) -> list[dict[str, Any]]:
        now = _utcnow_iso()
        sent_rows: list[dict[str, Any]] = []
        with self._scheduler_lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM email_schedules
                    WHERE status='queued' AND scheduled_for <= ?
                    ORDER BY scheduled_for ASC, id ASC
                    LIMIT ?
                    """,
                    (now, limit),
                ).fetchall()
            for row in rows:
                try:
                    result = self.send_message(
                        provider=row["provider"],
                        to_email=row["to_email"],
                        template_name=row["template_name"],
                        subject=row["subject"],
                        html_body=row["html_body"],
                        text_body=row["text_body"],
                        template_context=_json_loads(row["context_json"]),
                        metadata=_json_loads(row["metadata_json"]),
                        reply_to=row["reply_to"],
                        track_open=bool(row["track_opens"]),
                        track_clicks=bool(row["track_clicks"]),
                    )
                    sent_rows.append(result)
                    with self._connect() as conn:
                        conn.execute(
                            """
                            UPDATE email_schedules
                            SET status='sent',
                                sent_message_id=?,
                                last_error='',
                                updated_at=?
                            WHERE id=?
                            """,
                            (result["id"], _utcnow_iso(), row["id"]),
                        )
                        conn.commit()
                except Exception as exc:
                    log.exception("Scheduled email %s failed", row["id"])
                    with self._connect() as conn:
                        conn.execute(
                            """
                            UPDATE email_schedules
                            SET status='failed',
                                last_error=?,
                                updated_at=?
                            WHERE id=?
                            """,
                            (str(exc), _utcnow_iso(), row["id"]),
                        )
                        conn.commit()
        return sent_rows

    def start_scheduler(self) -> None:
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            return
        self._stop_event.clear()

        def run() -> None:
            while not self._stop_event.is_set():
                try:
                    self.process_due_scheduled()
                except Exception:
                    log.exception("Scheduler loop failed")
                self._stop_event.wait(self.poll_seconds)

        self._scheduler_thread = threading.Thread(
            target=run,
            name="tms-email-scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()

    def stop_scheduler(self) -> None:
        self._stop_event.set()
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=2)

    def send_message(
        self,
        *,
        provider: str,
        to_email: str,
        subject: str = "",
        html_body: str = "",
        text_body: str = "",
        template_name: str = "",
        template_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        reply_to: str = "",
        track_open: bool = True,
        track_clicks: bool = True,
    ) -> dict[str, Any]:
        provider_name = provider.strip().lower()
        config = self.get_provider_config(provider_name)
        context = template_context or {}
        meta = metadata or {}
        if template_name:
            rendered = self.render_template(template_name, context)
            subject = subject or rendered["subject"]
            html_body = html_body or rendered["html"]
            text_body = text_body or rendered["text"]
        if not subject:
            raise EmailEngineError("Email subject is required.")
        if not html_body and not text_body:
            raise EmailEngineError("Either html_body or text_body is required.")

        tracking_id = uuid.uuid4().hex
        final_html = self.instrument_html(html_body, tracking_id, track_open, track_clicks) if html_body else ""
        final_text = text_body or _text_from_html(final_html or html_body)
        payload = {
            "provider": provider_name,
            "to_email": to_email,
            "from_email": config.get("from_email", ""),
            "from_name": config.get("from_name", ""),
            "subject": subject,
            "html_body": final_html,
            "text_body": final_text,
            "reply_to": reply_to or config.get("reply_to", ""),
            "tracking_id": tracking_id,
            "metadata": meta,
        }

        try:
            if provider_name == "gmail":
                provider_result = self._send_gmail(config, payload)
            elif provider_name == "outlook":
                provider_result = self._send_outlook(config, payload)
            elif provider_name == "smtp":
                provider_result = self._send_smtp(config, payload)
            else:
                raise EmailEngineError(f"Unsupported provider '{provider_name}'.")
        except Exception as exc:
            message_row = self._insert_message(
                provider=provider_name,
                status="failed",
                to_email=to_email,
                from_email=config.get("from_email", ""),
                subject=subject,
                html_body=final_html,
                text_body=final_text,
                template_name=template_name,
                tracking_id=tracking_id,
                provider_message_id="",
                provider_thread_id="",
                provider_conversation_id="",
                internet_message_id="",
                last_error=str(exc),
                metadata=meta,
                sent_at="",
            )
            self._record_event(
                message_id=message_row["id"],
                tracking_id=tracking_id,
                event_type="send_failed",
                event_value=str(exc),
                source_url="",
                event_json={"provider": provider_name},
            )
            raise

        sent_at = _utcnow_iso()
        message_row = self._insert_message(
            provider=provider_name,
            status="sent",
            to_email=to_email,
            from_email=config.get("from_email", ""),
            subject=subject,
            html_body=final_html,
            text_body=final_text,
            template_name=template_name,
            tracking_id=tracking_id,
            provider_message_id=provider_result.get("provider_message_id", ""),
            provider_thread_id=provider_result.get("provider_thread_id", ""),
            provider_conversation_id=provider_result.get("provider_conversation_id", ""),
            internet_message_id=provider_result.get("internet_message_id", ""),
            last_error="",
            metadata=meta,
            sent_at=sent_at,
        )
        self._record_event(
            message_id=message_row["id"],
            tracking_id=tracking_id,
            event_type="sent",
            event_value=provider_result.get("provider_message_id", ""),
            source_url=provider_result.get("source_url", ""),
            event_json=provider_result,
        )
        return message_row

    def _insert_message(
        self,
        *,
        provider: str,
        status: str,
        to_email: str,
        from_email: str,
        subject: str,
        html_body: str,
        text_body: str,
        template_name: str,
        tracking_id: str,
        provider_message_id: str,
        provider_thread_id: str,
        provider_conversation_id: str,
        internet_message_id: str,
        last_error: str,
        metadata: dict[str, Any],
        sent_at: str,
    ) -> dict[str, Any]:
        now = _utcnow_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO email_messages (
                    provider, status, to_email, from_email, subject, html_body, text_body,
                    template_name, tracking_id, provider_message_id, provider_thread_id,
                    provider_conversation_id, internet_message_id, last_error, metadata_json,
                    sent_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    status,
                    to_email,
                    from_email,
                    subject,
                    html_body,
                    text_body,
                    template_name,
                    tracking_id,
                    provider_message_id,
                    provider_thread_id,
                    provider_conversation_id,
                    internet_message_id,
                    last_error,
                    _json_dumps(metadata),
                    sent_at,
                    now,
                    now,
                ),
            )
            message_id = cursor.lastrowid
            conn.commit()
        return self.get_message(int(message_id))

    def get_message(self, message_id: int) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM email_messages WHERE id=?",
                (message_id,),
            ).fetchone()
        if not row:
            raise EmailEngineError(f"Message {message_id} was not found.")
        return dict(row)

    def get_message_by_tracking_id(self, tracking_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM email_messages WHERE tracking_id=?",
                (tracking_id,),
            ).fetchone()
        return dict(row) if row else None

    def _record_event(
        self,
        *,
        message_id: int | None,
        tracking_id: str,
        event_type: str,
        event_value: str,
        source_url: str,
        event_json: dict[str, Any] | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_events (
                    message_id, tracking_id, event_type, event_value, source_url, event_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    tracking_id,
                    event_type,
                    event_value,
                    source_url,
                    _json_dumps(event_json),
                    _utcnow_iso(),
                ),
            )
            conn.commit()

    def record_open(
        self,
        tracking_id: str,
        *,
        source_url: str = "",
        remote_addr: str = "",
        user_agent: str = "",
    ) -> bytes:
        message = self.get_message_by_tracking_id(tracking_id)
        if message:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE email_messages
                    SET open_count=open_count + 1,
                        last_opened_at=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (_utcnow_iso(), _utcnow_iso(), message["id"]),
                )
                conn.commit()
            self._record_event(
                message_id=message["id"],
                tracking_id=tracking_id,
                event_type="opened",
                event_value="pixel_loaded",
                source_url=source_url or self.build_open_url(tracking_id),
                event_json={"remote_addr": remote_addr, "user_agent": user_agent},
            )
        return OPEN_PIXEL_GIF

    def record_click(
        self,
        tracking_id: str,
        destination_url: str,
        *,
        source_url: str = "",
        remote_addr: str = "",
        user_agent: str = "",
    ) -> str:
        message = self.get_message_by_tracking_id(tracking_id)
        if message:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE email_messages
                    SET click_count=click_count + 1,
                        last_clicked_at=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (_utcnow_iso(), _utcnow_iso(), message["id"]),
                )
                conn.commit()
            self._record_event(
                message_id=message["id"],
                tracking_id=tracking_id,
                event_type="clicked",
                event_value=destination_url,
                source_url=source_url or self.build_click_url(tracking_id, destination_url),
                event_json={"destination_url": destination_url, "remote_addr": remote_addr, "user_agent": user_agent},
            )
        return destination_url

    def sync_replies(
        self,
        provider: str | None = None,
        since: datetime | str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        providers = [provider.lower()] if provider else self.list_provider_configs()
        all_replies: list[dict[str, Any]] = []
        for provider_name in providers:
            since_dt = _parse_dt(since) if since else self._get_reply_cursor(provider_name)
            if provider_name == "gmail":
                replies = self._fetch_gmail_replies(self.get_provider_config("gmail"), since_dt, limit)
            elif provider_name == "outlook":
                replies = self._fetch_outlook_replies(self.get_provider_config("outlook"), since_dt, limit)
            elif provider_name == "smtp":
                replies = self._fetch_smtp_replies(self.get_provider_config("smtp"), since_dt, limit)
            else:
                continue
            all_replies.extend(replies)
            self._set_reply_cursor(provider_name, _utcnow())
        return all_replies

    def _get_reply_cursor(self, provider: str) -> datetime:
        stored = self.get_setting(f"reply_cursor:{provider}", "")
        parsed = _parse_dt(stored)
        return parsed or (_utcnow() - timedelta(days=7))

    def _set_reply_cursor(self, provider: str, value: datetime) -> None:
        self.set_setting(f"reply_cursor:{provider}", value.replace(microsecond=0).isoformat())

    def _token_expiry(self, expires_in: Any) -> str:
        try:
            seconds = int(expires_in or 0)
        except (TypeError, ValueError):
            seconds = 0
        if seconds <= 0:
            return ""
        return (_utcnow() + timedelta(seconds=seconds - 60)).replace(microsecond=0).isoformat()

    def _ensure_gmail_token(self, config: dict[str, Any]) -> str:
        expiry = _parse_dt(config.get("token_expiry"))
        access_token = config.get("access_token", "")
        if access_token and expiry and expiry > _utcnow():
            return access_token
        response = requests.post(
            config.get("token_uri", GMAIL_TOKEN_URL),
            data={
                "client_id": config.get("client_id", ""),
                "client_secret": config.get("client_secret", ""),
                "refresh_token": config.get("refresh_token", ""),
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        config["access_token"] = token_data["access_token"]
        config["token_expiry"] = self._token_expiry(token_data.get("expires_in"))
        if token_data.get("refresh_token"):
            config["refresh_token"] = token_data["refresh_token"]
        self.save_provider_config("gmail", config)
        return config["access_token"]

    def _ensure_outlook_token(self, config: dict[str, Any]) -> str:
        expiry = _parse_dt(config.get("token_expiry"))
        access_token = config.get("access_token", "")
        if access_token and expiry and expiry > _utcnow():
            return access_token
        response = requests.post(
            config["token_uri"],
            data={
                "client_id": config.get("client_id", ""),
                "client_secret": config.get("client_secret", ""),
                "refresh_token": config.get("refresh_token", ""),
                "grant_type": "refresh_token",
                "scope": " ".join(config.get("scopes", DEFAULT_OUTLOOK_SCOPES)),
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        config["access_token"] = token_data["access_token"]
        config["token_expiry"] = self._token_expiry(token_data.get("expires_in"))
        if token_data.get("refresh_token"):
            config["refresh_token"] = token_data["refresh_token"]
        self.save_provider_config("outlook", config)
        return config["access_token"]

    def _build_mime_message(self, payload: dict[str, Any]) -> tuple[EmailMessage, str]:
        message = EmailMessage()
        from_address = payload["from_email"]
        from_name = payload.get("from_name", "")
        reply_to = payload.get("reply_to", "")
        message_id = make_msgid(domain=from_address.split("@", 1)[1] if "@" in from_address else None)
        message["To"] = payload["to_email"]
        message["From"] = formataddr((from_name, from_address)) if from_name else from_address
        message["Subject"] = payload["subject"]
        message["Date"] = format_datetime(_utcnow())
        message["Message-ID"] = message_id
        if reply_to:
            message["Reply-To"] = reply_to
        message["X-TMS-Tracking-ID"] = payload["tracking_id"]
        if payload.get("text_body"):
            message.set_content(payload["text_body"])
        else:
            message.set_content(_text_from_html(payload.get("html_body", "")))
        if payload.get("html_body"):
            message.add_alternative(payload["html_body"], subtype="html")
        return message, message_id

    def _send_gmail(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        token = self._ensure_gmail_token(config)
        message, message_id = self._build_mime_message(payload)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = requests.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw_message},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "provider_message_id": data.get("id", ""),
            "provider_thread_id": data.get("threadId", ""),
            "provider_conversation_id": "",
            "internet_message_id": message_id,
            "source_url": GMAIL_SEND_URL,
        }

    def _send_outlook(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        token = self._ensure_outlook_token(config)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        message_payload: dict[str, Any] = {
            "subject": payload["subject"],
            "body": {
                "contentType": "HTML" if payload.get("html_body") else "Text",
                "content": payload.get("html_body") or payload.get("text_body", ""),
            },
            "toRecipients": [
                {"emailAddress": {"address": payload["to_email"]}},
            ],
            "internetMessageHeaders": [
                {"name": "x-tms-tracking-id", "value": payload["tracking_id"]},
            ],
        }
        if payload.get("reply_to"):
            message_payload["replyTo"] = [
                {"emailAddress": {"address": payload["reply_to"]}},
            ]
        draft_response = requests.post(
            f"{GRAPH_BASE_URL}/me/messages",
            headers=headers,
            json=message_payload,
            timeout=30,
        )
        draft_response.raise_for_status()
        draft = draft_response.json()
        send_response = requests.post(
            f"{GRAPH_BASE_URL}/me/messages/{draft['id']}/send",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        send_response.raise_for_status()
        return {
            "provider_message_id": draft.get("id", ""),
            "provider_thread_id": "",
            "provider_conversation_id": draft.get("conversationId", ""),
            "internet_message_id": draft.get("internetMessageId", ""),
            "source_url": f"{GRAPH_BASE_URL}/me/messages/{draft.get('id', '')}/send",
        }

    def _send_smtp(self, config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        message, message_id = self._build_mime_message(payload)
        host = config.get("host", "")
        port = int(config.get("port", 0))
        timeout = int(config.get("timeout", 30))
        username = config.get("username", "")
        password = config.get("password", "")

        if _smtp_bool(config.get("use_ssl")):
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            smtp = smtplib.SMTP(host, port, timeout=timeout)
        try:
            smtp.ehlo()
            if _smtp_bool(config.get("use_tls"), default=True) and not _smtp_bool(config.get("use_ssl")):
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
        return {
            "provider_message_id": message_id.strip("<>"),
            "provider_thread_id": "",
            "provider_conversation_id": "",
            "internet_message_id": message_id,
            "source_url": f"smtp://{host}:{port}",
        }

    def _fetch_gmail_replies(
        self,
        config: dict[str, Any],
        since: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        token = self._ensure_gmail_token(config)
        headers = {"Authorization": f"Bearer {token}"}
        list_response = requests.get(
            GMAIL_LIST_URL,
            headers=headers,
            params={"labelIds": "INBOX", "maxResults": limit, "q": f"after:{int(since.timestamp())}"},
            timeout=30,
        )
        list_response.raise_for_status()
        message_refs = list_response.json().get("messages", [])
        replies: list[dict[str, Any]] = []
        for ref in message_refs:
            message_id = ref.get("id")
            if not message_id:
                continue
            detail_response = requests.get(
                GMAIL_MESSAGE_URL.format(message_id=message_id),
                headers=headers,
                params=[
                    ("format", "metadata"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "Subject"),
                    ("metadataHeaders", "Date"),
                    ("metadataHeaders", "Message-ID"),
                    ("metadataHeaders", "In-Reply-To"),
                ],
                timeout=30,
            )
            detail_response.raise_for_status()
            detail = detail_response.json()
            header_map = {
                item.get("name", ""): item.get("value", "")
                for item in detail.get("payload", {}).get("headers", [])
            }
            sender = _normalize_email(header_map.get("From"))
            if sender == _normalize_email(config.get("from_email")):
                continue
            candidate = self._find_reply_parent(
                provider="gmail",
                provider_thread_id=detail.get("threadId", ""),
                provider_conversation_id="",
                internet_message_id=header_map.get("In-Reply-To", ""),
            )
            if not candidate:
                continue
            reply_row = self._store_reply(
                provider="gmail",
                provider_message_id=detail.get("id", ""),
                source_message_id=candidate["id"],
                reply_from=sender,
                subject=header_map.get("Subject", ""),
                body_preview="",
                received_at=header_map.get("Date", ""),
                raw_json=detail,
            )
            if reply_row:
                replies.append(reply_row)
        return replies

    def _fetch_outlook_replies(
        self,
        config: dict[str, Any],
        since: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        token = self._ensure_outlook_token(config)
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "$top": limit,
            "$select": "id,conversationId,subject,from,receivedDateTime,bodyPreview,internetMessageId",
            "$filter": f"receivedDateTime ge {since.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        }
        response = requests.get(
            f"{GRAPH_BASE_URL}/me/mailFolders/inbox/messages",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        replies: list[dict[str, Any]] = []
        for item in response.json().get("value", []):
            sender = _normalize_email(
                item.get("from", {}).get("emailAddress", {}).get("address", "")
            )
            if sender == _normalize_email(config.get("from_email")):
                continue
            candidate = self._find_reply_parent(
                provider="outlook",
                provider_thread_id="",
                provider_conversation_id=item.get("conversationId", ""),
                internet_message_id="",
            )
            if not candidate:
                continue
            reply_row = self._store_reply(
                provider="outlook",
                provider_message_id=item.get("id", ""),
                source_message_id=candidate["id"],
                reply_from=sender,
                subject=item.get("subject", ""),
                body_preview=item.get("bodyPreview", ""),
                received_at=item.get("receivedDateTime", ""),
                raw_json=item,
            )
            if reply_row:
                replies.append(reply_row)
        return replies

    def _fetch_smtp_replies(
        self,
        config: dict[str, Any],
        since: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        imap_host = config.get("imap_host", "")
        if not imap_host:
            return []

        imap_port = int(config.get("imap_port", 993))
        username = config.get("imap_username") or config.get("username", "")
        password = config.get("imap_password") or config.get("password", "")
        if _smtp_bool(config.get("imap_ssl"), default=True):
            mailbox = imaplib.IMAP4_SSL(imap_host, imap_port)
        else:
            mailbox = imaplib.IMAP4(imap_host, imap_port)
        replies: list[dict[str, Any]] = []
        try:
            mailbox.login(username, password)
            mailbox.select("INBOX")
            search_date = since.astimezone(timezone.utc).strftime("%d-%b-%Y")
            status, data = mailbox.search(None, "SINCE", search_date)
            if status != "OK":
                return []
            message_ids = data[0].split()[-limit:]
            parser = BytesParser(policy=email_policy)
            for message_id in reversed(message_ids):
                fetch_status, message_data = mailbox.fetch(
                    message_id,
                    "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID IN-REPLY-TO)])",
                )
                if fetch_status != "OK" or not message_data or not message_data[0]:
                    continue
                raw_headers = message_data[0][1]
                parsed = parser.parsebytes(raw_headers)
                sender = _normalize_email(parsed.get("From", ""))
                if sender == _normalize_email(config.get("from_email")):
                    continue
                candidate = self._find_reply_parent(
                    provider="smtp",
                    provider_thread_id="",
                    provider_conversation_id="",
                    internet_message_id=parsed.get("In-Reply-To", ""),
                )
                if not candidate:
                    continue
                reply_row = self._store_reply(
                    provider="smtp",
                    provider_message_id=str(message_id, "utf-8", errors="ignore"),
                    source_message_id=candidate["id"],
                    reply_from=sender,
                    subject=parsed.get("Subject", ""),
                    body_preview="",
                    received_at=parsed.get("Date", ""),
                    raw_json={"message_id": parsed.get("Message-ID", "")},
                )
                if reply_row:
                    replies.append(reply_row)
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass
        return replies

    def _find_reply_parent(
        self,
        *,
        provider: str,
        provider_thread_id: str,
        provider_conversation_id: str,
        internet_message_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            if provider == "gmail" and provider_thread_id:
                row = conn.execute(
                    """
                    SELECT * FROM email_messages
                    WHERE provider='gmail' AND provider_thread_id=?
                    ORDER BY sent_at DESC, id DESC
                    LIMIT 1
                    """,
                    (provider_thread_id,),
                ).fetchone()
                if row:
                    return dict(row)
            if provider == "outlook" and provider_conversation_id:
                row = conn.execute(
                    """
                    SELECT * FROM email_messages
                    WHERE provider='outlook' AND provider_conversation_id=?
                    ORDER BY sent_at DESC, id DESC
                    LIMIT 1
                    """,
                    (provider_conversation_id,),
                ).fetchone()
                if row:
                    return dict(row)
            if internet_message_id:
                row = conn.execute(
                    """
                    SELECT * FROM email_messages
                    WHERE internet_message_id=?
                    ORDER BY sent_at DESC, id DESC
                    LIMIT 1
                    """,
                    (internet_message_id,),
                ).fetchone()
                if row:
                    return dict(row)
        return None

    def _store_reply(
        self,
        *,
        provider: str,
        provider_message_id: str,
        source_message_id: int,
        reply_from: str,
        subject: str,
        body_preview: str,
        received_at: str,
        raw_json: dict[str, Any],
    ) -> dict[str, Any] | None:
        now = _utcnow_iso()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM email_replies
                WHERE provider=? AND provider_message_id=?
                """,
                (provider, provider_message_id),
            ).fetchone()
            if existing:
                return None
            cursor = conn.execute(
                """
                INSERT INTO email_replies (
                    provider, provider_message_id, source_message_id, reply_from,
                    subject, body_preview, received_at, raw_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    provider_message_id,
                    source_message_id,
                    reply_from,
                    subject,
                    body_preview,
                    received_at,
                    _json_dumps(raw_json),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE email_messages
                SET reply_count=reply_count + 1,
                    last_replied_at=?,
                    updated_at=?
                WHERE id=?
                """,
                (now, now, source_message_id),
            )
            conn.commit()
            reply_id = int(cursor.lastrowid)
        self._record_event(
            message_id=source_message_id,
            tracking_id="",
            event_type="replied",
            event_value=reply_from,
            source_url="",
            event_json={"provider": provider, "provider_message_id": provider_message_id},
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM email_replies WHERE id=?",
                (reply_id,),
            ).fetchone()
        return dict(row) if row else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TMS email automation engine")
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help="Path to the TMS SQLite database",
    )
    parser.add_argument(
        "--templates",
        default=str(DEFAULT_TEMPLATE_DIR),
        help="Directory with HTML email templates",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create email engine tables")

    seed_parser = subparsers.add_parser("seed-config", help="Load providers/templates from user_config.json")
    seed_parser.add_argument("--config", required=True, help="Path to user_config.json")

    send_parser = subparsers.add_parser("send-test", help="Send a single email")
    send_parser.add_argument("--provider", required=True, choices=["gmail", "outlook", "smtp"])
    send_parser.add_argument("--to", required=True)
    send_parser.add_argument("--template", default="basic_outreach")
    send_parser.add_argument("--subject", default="")
    send_parser.add_argument("--context", default="{}")
    send_parser.add_argument("--html-file", default="")
    send_parser.add_argument("--reply-to", default="")

    scheduler_parser = subparsers.add_parser("run-scheduler", help="Run the background scheduler loop")
    scheduler_parser.add_argument("--poll-seconds", type=int, default=30)

    replies_parser = subparsers.add_parser("sync-replies", help="Pull replies from connected providers")
    replies_parser.add_argument("--provider", choices=["gmail", "outlook", "smtp"])
    replies_parser.add_argument("--limit", type=int, default=50)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    engine = EmailEngine(db_path=args.db, template_dir=args.templates, poll_seconds=getattr(args, "poll_seconds", 30))

    if args.command == "init-db":
        engine.init_db()
        print(json.dumps({"db_path": engine.db_path, "status": "ready"}, indent=2))
        return 0

    if args.command == "seed-config":
        loaded = engine.load_user_config(args.config)
        print(json.dumps({"loaded_keys": sorted(loaded.keys())}, indent=2))
        return 0

    if args.command == "send-test":
        context = json.loads(args.context)
        html_body = Path(args.html_file).read_text(encoding="utf-8") if args.html_file else ""
        message = engine.send_message(
            provider=args.provider,
            to_email=args.to,
            subject=args.subject,
            html_body=html_body,
            template_name="" if html_body else args.template,
            template_context=context,
            reply_to=args.reply_to,
        )
        print(json.dumps(message, indent=2))
        return 0

    if args.command == "run-scheduler":
        engine.poll_seconds = max(5, int(args.poll_seconds))
        engine.start_scheduler()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.stop_scheduler()
            return 0

    if args.command == "sync-replies":
        replies = engine.sync_replies(provider=args.provider, limit=args.limit)
        print(json.dumps(replies, indent=2))
        return 0

    parser.error("Unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
