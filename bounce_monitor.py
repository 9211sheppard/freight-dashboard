"""
bounce_monitor.py -- Detect bounced/undeliverable emails via Microsoft Graph API.

Scans the pricing@ inbox for bounce notifications (from postmaster@ or
mailer-daemon@, or with subject Undeliverable), extracts the original
recipient, and records it in the bounced_emails table.

Contacts whose emails bounce are flagged so future sends are skipped.
"""

import json
import logging
import re
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from config import (
    EMAIL_FROM, GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
)
from database import get_db

log = logging.getLogger(__name__)


def _get_graph_token():
    url = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token"
    body = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     GRAPH_CLIENT_ID,
        "client_secret": GRAPH_CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def _graph_get(endpoint, token):
    url = f"https://graph.microsoft.com/v1.0{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_RECIPIENT_PATTERNS = [
    re.compile(r"couldn[\u2019']t\s+be\s+delivered\s+to\s+<?([^\s<>]+@[^\s<>]+)>?", re.I),
    re.compile(r"delivery.*?failed.*?:\s*<?([^\s<>]+@[^\s<>]+)>?", re.I),
    re.compile(r"message\s+to\s+<?([^\s<>]+@[^\s<>]+)>?\s+was\s+undeliverable", re.I),
    re.compile(r"(?:failed|undeliverable).*?recipients?.*?[\n\r]+\s*<?([^\s<>]+@[^\s<>]+)>?", re.I),
    re.compile(r"Final-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)", re.I),
    re.compile(r"Original-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)", re.I),
    re.compile(r"Remote\s+Server\s+returned.*?<([^\s<>]+@[^\s<>]+)>", re.I),
    re.compile(r"\bto\s+<?([^\s<>]+@[^\s<>]+)>?", re.I),
]

_IGNORE_ADDRESSES = {
    (EMAIL_FROM or "").lower(),
    "postmaster@outlook.com",
    "postmaster@microsoft.com",
    "mailer-daemon@googlemail.com",
    "mailer-daemon@outlook.com",
    "noreply@microsoft.com",
}


def _extract_bounced_email(body, subject=""):
    combined = f"{subject}\n{body}"
    for pattern in _RECIPIENT_PATTERNS:
        m = pattern.search(combined)
        if m:
            candidate = m.group(1).lower().strip().rstrip(".")
            if candidate not in _IGNORE_ADDRESSES and "@" in candidate:
                return candidate
    all_emails = _EMAIL_RE.findall(body)
    for em in all_emails:
        em_lower = em.lower().strip().rstrip(".")
        if (em_lower not in _IGNORE_ADDRESSES
                and not em_lower.startswith("postmaster@")
                and not em_lower.startswith("mailer-daemon@")):
            return em_lower
    return None


def _extract_bounce_reason(body):
    # Strip HTML tags for cleaner extraction
    body = re.sub(r'<[^>]+>', ' ', body)
    patterns = [
        re.compile(r"(550\s+[^\n]{5,80})", re.I),
        re.compile(r"(553\s+[^\n]{5,80})", re.I),
        re.compile(r"(mailbox\s+(?:not\s+found|unavailable|full)[^\n]{0,60})", re.I),
        re.compile(r"(user\s+(?:unknown|not\s+found|rejected)[^\n]{0,60})", re.I),
        re.compile(r"(address\s+rejected[^\n]{0,60})", re.I),
        re.compile(r"(no such user[^\n]{0,60})", re.I),
        re.compile(r"(recipient\s+rejected[^\n]{0,60})", re.I),
    ]
    for p in patterns:
        m = p.search(body)
        if m:
            return m.group(1).strip()[:200]
    return "Undeliverable"


def init_bounced_emails_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bounced_emails (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email       TEXT NOT NULL,
            contact_id  INTEGER,
            bounce_reason TEXT DEFAULT '',
            detected_at TEXT DEFAULT '',
            UNIQUE(email)
        )
    """)
    conn.commit()
    conn.close()


def is_bounced(email):
    if not email:
        return False
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM bounced_emails WHERE email = ?",
        (email.lower().strip(),)
    ).fetchone()
    conn.close()
    return row is not None


def record_bounce(email, reason="", contact_id=None):
    email = email.lower().strip()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO bounced_emails (email, contact_id, bounce_reason, detected_at)
               VALUES (?, ?, ?, ?)""",
            (email, contact_id, reason, now),
        )
        conn.commit()
    except Exception as exc:
        log.error(f"record_bounce error: {exc}")
    finally:
        conn.close()


def _flag_contact(email, reason):
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        note = f"Email bounced ({now}): {reason}"
        conn.execute(
            """UPDATE contacts
               SET verified_status = 'flagged',
                   verify_notes = CASE
                       WHEN verify_notes = '' THEN ?
                       ELSE verify_notes || char(10) || ?
                   END
               WHERE LOWER(email) = ?""",
            (note, note, email.lower().strip()),
        )
        row = conn.execute(
            "SELECT id FROM contacts WHERE LOWER(email) = ?",
            (email.lower().strip(),)
        ).fetchone()
        contact_id = row["id"] if row else None
        conn.commit()
        conn.close()
        return contact_id
    except Exception as exc:
        log.error(f"_flag_contact error for {email}: {exc}")
        conn.close()
        return None


def fetch_bounce_messages(top=50):
    token = _get_graph_token()
    mailbox = EMAIL_FROM
    results = []
    filter_queries = [
        f"/users/{mailbox}/messages?$search=%22subject:Undeliverable%20OR%20from:postmaster%20OR%20from:mailer-daemon%22&$top={top}&$select=id,subject,receivedDateTime,bodyPreview,body,from",
        f"/users/{mailbox}/messages?$search=%22subject:delivery%20failure%20OR%20subject:returned%20mail%22&$top={top}&$select=id,subject,receivedDateTime,bodyPreview,body,from",
    ]
    for endpoint in filter_queries:
        try:
            data = _graph_get(endpoint, token)
            for msg in data.get("value", []):
                results.append({
                    "message_id": msg.get("id", ""),
                    "subject":    msg.get("subject", ""),
                    "received":   msg.get("receivedDateTime", ""),
                    "body_preview": msg.get("bodyPreview", ""),
                    "body":       msg.get("body", {}).get("content", ""),
                    "from_addr":  msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                })
        except Exception as exc:
            log.warning(f"fetch_bounce_messages query error: {exc}")
    seen = set()
    unique = []
    for m in results:
        if m["message_id"] not in seen:
            seen.add(m["message_id"])
            unique.append(m)
    return unique


def check_bounces():
    log.info("[bounce_monitor] Scanning inbox for bounces...")
    messages = fetch_bounce_messages(top=50)
    log.info(f"[bounce_monitor] Found {len(messages)} bounce candidate messages")
    new_bounces = []
    for msg in messages:
        body = msg.get("body", "") or msg.get("body_preview", "")
        subject = msg.get("subject", "")
        bounced_email = _extract_bounced_email(body, subject)
        if not bounced_email:
            continue
        if is_bounced(bounced_email):
            continue
        reason = _extract_bounce_reason(body)
        contact_id = _flag_contact(bounced_email, reason)
        record_bounce(bounced_email, reason=reason, contact_id=contact_id)
        new_bounces.append({
            "email":     bounced_email,
            "reason":    reason,
            "detected":  msg.get("received", ""),
            "contact_id": contact_id,
        })
        log.info(f"[bounce_monitor] NEW bounce: {bounced_email} -- {reason}")
    return {
        "checked":        len(messages),
        "new_bounces":    len(new_bounces),
        "bounced_emails": new_bounces,
    }


def get_all_bounces():
    conn = get_db()
    rows = conn.execute(
        """SELECT b.email, b.bounce_reason, b.detected_at, b.contact_id,
                  c.company_name, c.contact_name, c.country
           FROM bounced_emails b
           LEFT JOIN contacts c ON b.contact_id = c.id
           ORDER BY b.detected_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=" * 50)
    print("  Bounce Monitor -- Manual Scan")
    print("=" * 50)
    init_bounced_emails_db()
    result = check_bounces()
    print(f"\nMessages checked : {result['checked']}")
    print(f"New bounces found: {result['new_bounces']}")
    for b in result["bounced_emails"]:
        print(f"  - {b['email']}  (reason: {b['reason']}, contact_id: {b['contact_id']})")
    print(f"\n--- All recorded bounces ---")
    for b in get_all_bounces():
        company = b.get("company_name", "") or ""
        print(f"  {b['email']:40s}  {company:30s}  {b['bounce_reason']}")
