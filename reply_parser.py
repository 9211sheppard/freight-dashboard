"""
reply_parser.py — Polls pricing@flashcargoglobal.com inbox via Graph API,
detects intro email replies, parses LANES:/LINES: format, stores to DB.
"""

import json
import logging
import re
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta

from config import GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, EMAIL_FROM
from database import get_db

log = logging.getLogger(__name__)

# Slug → label (mirrors intro_mailer._LANE_SLUG)
_SLUG_LABEL = {
    "usa-canada":    "USA / Canada",
    "europe":        "Europe",
    "middle-east":   "Middle East",
    "south-america": "South America",
    "far-east":      "Far East / Asia Pacific",
    "africa":        "Africa",
    "australia":     "Australia / Oceania",
    "mexico":        "Mexico / Central America",
    "all":           "All Destinations",
}

# Letter → carrier name (must match _CARRIER_OPTIONS order in intro_mailer)
_LETTER_TO_CARRIER = {
    "A": "Maersk",
    "B": "MSC",
    "C": "CMA CGM",
    "D": "Hapag-Lloyd",
    "E": "COSCO",
    "F": "ONE",
    "G": "Evergreen",
    "H": "Yang Ming",
    "I": "ZIM",
    "J": "PIL",
    "K": "Arkas",
    "L": "Other",
}


def _get_token():
    url  = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     GRAPH_CLIENT_ID,
        "client_secret": GRAPH_CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req  = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["access_token"]


def _graph_get(token, path):
    url = f"https://graph.microsoft.com/v1.0{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        log.error(f"Graph GET {path} → {e.code}: {e.read()[:200]}")
        return None


_ALL_LANE_LABELS = list(_SLUG_LABEL.values())

_CARRIER_NAMES = list(_LETTER_TO_CARRIER.values())  # ordered A-L


def _parse_lanes_from_reply(body_text: str, lane_labels: list) -> list:
    """
    Extract lane selections from reply body.
    Handles:
      - Numbered format:  Lanes: 1,3,5  (primary — matches new email format)
      - Checkbox format:  [ ] USA / Canada  (fallback for old emails)
      - "all" keyword
    Returns list of lane label strings.
    """
    # ── Numbered format (primary) ─────────────────────────────────────────────
    pattern = re.search(r"lanes?\s*[:\-]\s*([^\n\r]+)", body_text, re.IGNORECASE)
    if pattern:
        raw = pattern.group(1).strip()
        if re.search(r"\ball\b", raw, re.IGNORECASE):
            return lane_labels[:]
        nums = re.findall(r"\d+", raw)
        if nums:
            result = []
            for n in nums:
                idx = int(n) - 1
                if 0 <= idx < len(lane_labels):
                    result.append(lane_labels[idx])
            return result

    # ── Checkbox format fallback ([ ] Label) ──────────────────────────────────
    checked = re.findall(r"\[\s*\]\s*(.+?)(?:\n|$)", body_text)
    result = []
    for item in checked:
        item = item.strip()
        if re.search(r"\ball\b", item, re.IGNORECASE):
            return lane_labels[:]
        for lbl in lane_labels:
            if lbl.lower() == item.lower():
                if lbl not in result:
                    result.append(lbl)
                break
    return result


def _parse_carriers_from_reply(body_text: str) -> list:
    """
    Extract carrier selections from reply body.
    Handles:
      - Lettered format:  Lines: A,C,F  (primary — matches new email format)
      - Checkbox format:  [ ] Maersk  (fallback for old emails)
      - Carrier name matching
    Returns list of carrier name strings.
    """
    # ── Lettered format (primary) ─────────────────────────────────────────────
    pattern = re.search(r"lines?\s*[:\-]\s*([^\n\r]+)", body_text, re.IGNORECASE)
    if pattern:
        raw = pattern.group(1).strip()
        result = []
        letters = re.findall(r"\b([A-La-l])\b", raw)
        for l in letters:
            carrier = _LETTER_TO_CARRIER.get(l.upper())
            if carrier and carrier not in result:
                result.append(carrier)
        if result:
            return result
        # Try carrier names inline
        for carrier in _CARRIER_NAMES:
            if re.search(re.escape(carrier), raw, re.IGNORECASE):
                if carrier not in result:
                    result.append(carrier)
        if result:
            return result

    # ── Checkbox format fallback ──────────────────────────────────────────────
    checked = re.findall(r"\[\s*\]\s*(.+?)(?:\n|$)", body_text)
    result = []
    for item in checked:
        item = item.strip()
        for carrier in _CARRIER_NAMES:
            if carrier.lower() == item.lower():
                if carrier not in result:
                    result.append(carrier)
                break
    return result


def _get_lane_labels_for_contact(contact_id: int) -> list:
    """Retrieve the lane list that was sent to this contact (from intro_outreach country)."""
    from intro_mailer import _dedupe_lane_labels
    from contact_engine import get_lanes_for_country

    conn  = get_db()
    row   = conn.execute(
        "SELECT country FROM intro_outreach WHERE contact_id=? ORDER BY id DESC LIMIT 1",
        (contact_id,)
    ).fetchone()
    conn.close()

    if not row:
        return []
    country = row[0] or ""
    regions = get_lanes_for_country(country)
    return _dedupe_lane_labels(regions)


def _strip_html(html: str) -> str:
    """Very lightweight HTML stripper for parsing reply body."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z]+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _find_contact_by_email(sender_email: str):
    """Find contact row by email address."""
    conn = get_db()
    row  = conn.execute(
        "SELECT id, country FROM contacts WHERE LOWER(email)=? LIMIT 1",
        (sender_email.lower().strip(),)
    ).fetchone()
    conn.close()
    return row  # (id, country) or None


def _record_reply(contact_id: int, lanes: list, carriers: list, raw_body: str):
    """Store parsed reply into intro_outreach and contact_profiles."""
    conn = get_db()

    # Update intro_outreach
    conn.execute(
        """UPDATE intro_outreach
           SET reply_received=1,
               lanes_confirmed=?,
               carriers_confirmed=?,
               status='replied',
               notes=?
           WHERE contact_id=?
             AND status IN ('sent','replied')""",
        (
            ", ".join(lanes),
            ", ".join(carriers),
            raw_body[:500],
            contact_id,
        )
    )

    # Update contact_profiles
    try:
        import contact_engine as _ce
        _ce.update_profile(
            contact_id,
            confirmed_lanes=json.dumps(lanes),
            preferred_carriers=json.dumps(carriers),
        )
    except Exception as e:
        log.warning(f"profile update failed for {contact_id}: {e}")

    conn.commit()
    conn.close()
    log.info(f"[reply_parser] contact {contact_id} → lanes={lanes} carriers={carriers}")


def poll_inbox(lookback_hours: int = 48) -> dict:
    """
    Poll pricing@flashcargoglobal.com inbox for intro email replies.
    Parse LANES:/LINES: from body, store results.

    Returns { "processed": int, "skipped": int, "errors": int }
    """
    stats = {"processed": 0, "skipped": 0, "errors": 0}

    try:
        token = _get_token()
    except Exception as e:
        log.error(f"[reply_parser] token error: {e}")
        stats["errors"] += 1
        return stats

    # Fetch recent messages in inbox
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    mailbox = EMAIL_FROM.replace("@", "%40")  # URL encode for path
    path = (
        f"/users/{EMAIL_FROM}/mailFolders/inbox/messages"
        f"?$filter=receivedDateTime ge {since}"
        f"&$select=id,subject,from,body,conversationId,receivedDateTime"
        f"&$top=50"
        f"&$orderby=receivedDateTime desc"
    )

    data = _graph_get(token, path)
    if not data:
        stats["errors"] += 1
        return stats

    messages = data.get("value", [])
    log.info(f"[reply_parser] {len(messages)} messages fetched from inbox")

    # Load known conversation IDs from intro_outreach
    conn = get_db()
    # Check if conversation_id column exists; add if missing
    from database import _get_existing_columns
    cols = _get_existing_columns(conn, "intro_outreach")
    if "conversation_id" not in cols:
        conn.execute("ALTER TABLE intro_outreach ADD COLUMN conversation_id TEXT DEFAULT ''")
        conn.commit()
    sent_convs = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT conversation_id, contact_id FROM intro_outreach WHERE conversation_id != ''"
        ).fetchall()
        if r[0]
    }
    conn.close()

    for msg in messages:
        try:
            subject      = msg.get("subject", "")
            conv_id      = msg.get("conversationId", "")
            sender_email = (
                msg.get("from", {})
                   .get("emailAddress", {})
                   .get("address", "")
                   .lower()
                   .strip()
            )
            body_html = msg.get("body", {}).get("content", "")
            body_text = _strip_html(body_html)

            # ── Handle web selection page submissions ─────────────────────────
            # Subject format: SELECTION|<token>|{"lanes":[...],"carriers":[...]}
            if subject.startswith("SELECTION|"):
                parts = subject.split("|", 2)
                if len(parts) == 3:
                    _, sel_token, sel_json = parts
                    try:
                        sel_data     = json.loads(sel_json)
                        sel_lanes    = sel_data.get("lanes", [])
                        sel_carriers = sel_data.get("carriers", [])
                    except Exception:
                        stats["skipped"] += 1
                        continue
                    conn = get_db()
                    row = conn.execute(
                        "SELECT id, contact_id FROM intro_outreach WHERE click_token=?",
                        (sel_token,)
                    ).fetchone()
                    if row:
                        outreach_id   = row[0]
                        contact_id_s  = row[1]
                        conn.execute(
                            """UPDATE intro_outreach
                               SET lane_clicks=?, lanes_confirmed=?,
                                   carrier_clicks=?, carriers_confirmed=?,
                                   reply_received=1, status='replied'
                               WHERE id=?""",
                            (
                                json.dumps(sel_lanes),    ", ".join(sel_lanes),
                                json.dumps(sel_carriers), ", ".join(sel_carriers),
                                outreach_id,
                            ),
                        )
                        conn.commit()
                        if contact_id_s:
                            try:
                                import contact_engine as _ce
                                _ce.update_profile(
                                    contact_id_s,
                                    confirmed_lanes=json.dumps(sel_lanes),
                                    preferred_carriers=json.dumps(sel_carriers),
                                )
                            except Exception:
                                pass
                        stats["processed"] += 1
                    conn.close()
                stats["skipped"] += 1
                continue

            # ── Handle Azure Function click records ───────────────────────────
            # Subject format: CLICK_RECORD|<token>|LANE|USA / Canada
            if subject.startswith("CLICK_RECORD|"):
                parts = subject.split("|")
                if len(parts) == 4:
                    _, click_token, category, label = parts
                    conn = get_db()
                    row = conn.execute(
                        "SELECT id, contact_id, lane_clicks, carrier_clicks FROM intro_outreach WHERE click_token=?",
                        (click_token,)
                    ).fetchone()
                    if row:
                        outreach_id    = row[0]
                        contact_id_clk = row[1]
                        lane_clicks    = json.loads(row[2] or "[]")
                        carrier_clicks = json.loads(row[3] or "[]")
                        if category == "LANE":
                            if label == "All Destinations":
                                lane_clicks = list(_SLUG_LABEL.values())
                            elif label not in lane_clicks:
                                lane_clicks.append(label)
                            conn.execute(
                                "UPDATE intro_outreach SET lane_clicks=?,lanes_confirmed=?,reply_received=1 WHERE id=?",
                                (json.dumps(lane_clicks), ", ".join(lane_clicks), outreach_id)
                            )
                        else:
                            if label not in carrier_clicks:
                                carrier_clicks.append(label)
                            conn.execute(
                                "UPDATE intro_outreach SET carrier_clicks=?,carriers_confirmed=?,reply_received=1 WHERE id=?",
                                (json.dumps(carrier_clicks), ", ".join(carrier_clicks), outreach_id)
                            )
                        conn.commit()
                        if contact_id_clk:
                            try:
                                import contact_engine as _ce
                                if category == "LANE":
                                    _ce.update_profile(contact_id_clk, confirmed_lanes=json.dumps(lane_clicks))
                                else:
                                    _ce.update_profile(contact_id_clk, preferred_carriers=json.dumps(carrier_clicks))
                            except Exception:
                                pass
                        stats["processed"] += 1
                    conn.close()
                stats["skipped"] += 1  # don't process as normal reply
                continue

            # Skip our own outgoing copies (non-CLICK_RECORD)
            if sender_email == EMAIL_FROM.lower():
                stats["skipped"] += 1
                continue

            # Match by conversation thread OR sender email
            contact_id = sent_convs.get(conv_id)

            if not contact_id:
                contact_row = _find_contact_by_email(sender_email)
                if contact_row:
                    contact_id = contact_row[0]

            if not contact_id:
                log.debug(f"[reply_parser] no contact match for {sender_email}")
                stats["skipped"] += 1
                continue

            # Check if already processed
            conn = get_db()
            already = conn.execute(
                "SELECT reply_received FROM intro_outreach WHERE contact_id=? ORDER BY id DESC LIMIT 1",
                (contact_id,)
            ).fetchone()
            conn.close()
            if already and already[0] == 1:
                stats["skipped"] += 1
                continue

            # Parse lanes and carriers
            lane_labels = _get_lane_labels_for_contact(contact_id)
            lanes    = _parse_lanes_from_reply(body_text, lane_labels)
            carriers = _parse_carriers_from_reply(body_text)

            if not lanes and not carriers:
                log.debug(f"[reply_parser] no LANES/LINES found in reply from {sender_email}")
                stats["skipped"] += 1
                continue

            _record_reply(contact_id, lanes, carriers, body_text)
            stats["processed"] += 1

        except Exception as e:
            log.error(f"[reply_parser] error processing message: {e}")
            stats["errors"] += 1

    return stats
