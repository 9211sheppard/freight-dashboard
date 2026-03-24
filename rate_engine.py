"""
rate_engine.py  —  Rate request, parsing, and gap-analysis logic.

All email sending is gated on EMAIL_USER being non-empty in config.py.
Rate parsing and storage work fully without SMTP credentials.
"""

import json
import re
import smtplib
import threading
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import calendar

from database import get_db

# ---------------------------------------------------------------------------
#  Country → region → lane group mapping
# ---------------------------------------------------------------------------

COUNTRY_LANE_GROUPS = {
    "india":        ["india_to_na"],
    "china":        ["china_to_na"],
    "vietnam":      ["vietnam_to_na", "vietnam_to_europe"],
    "uae":          ["middle_east_to_na"],
    "saudi arabia": ["middle_east_to_na"],
    "qatar":        ["middle_east_to_na"],
    "kuwait":       ["middle_east_to_na"],
    "bahrain":      ["middle_east_to_na"],
    "oman":         ["middle_east_to_na"],
    "jordan":       ["middle_east_to_na"],
    "egypt":        ["middle_east_to_na"],
    "germany":      ["europe_to_na"],
    "netherlands":  ["europe_to_na"],
    "belgium":      ["europe_to_na"],
    "france":       ["europe_to_na"],
    "italy":        ["europe_to_na"],
    "spain":        ["europe_to_na"],
    "poland":       ["europe_to_na"],
    "sweden":       ["europe_to_na"],
    "denmark":      ["europe_to_na"],
    "finland":      ["europe_to_na"],
    "norway":       ["europe_to_na"],
    "portugal":     ["europe_to_na"],
    "austria":      ["europe_to_na"],
    "switzerland":  ["europe_to_na"],
    "czech republic": ["europe_to_na"],
    "hungary":      ["europe_to_na"],
    "romania":      ["europe_to_na"],
    "greece":       ["europe_to_na"],
    "turkey":       ["europe_to_na"],
    "united kingdom": ["europe_to_na"],
    "uk":           ["europe_to_na"],
}

# Country → IANA timezone
COUNTRY_TIMEZONES = {
    "india":          "Asia/Kolkata",
    "china":          "Asia/Shanghai",
    "vietnam":        "Asia/Ho_Chi_Minh",
    "uae":            "Asia/Dubai",
    "saudi arabia":   "Asia/Riyadh",
    "qatar":          "Asia/Qatar",
    "kuwait":         "Asia/Kuwait",
    "bahrain":        "Asia/Bahrain",
    "oman":           "Asia/Muscat",
    "jordan":         "Asia/Amman",
    "egypt":          "Africa/Cairo",
    "germany":        "Europe/Berlin",
    "netherlands":    "Europe/Amsterdam",
    "belgium":        "Europe/Brussels",
    "france":         "Europe/Paris",
    "italy":          "Europe/Rome",
    "spain":          "Europe/Madrid",
    "poland":         "Europe/Warsaw",
    "sweden":         "Europe/Stockholm",
    "denmark":        "Europe/Copenhagen",
    "finland":        "Europe/Helsinki",
    "norway":         "Europe/Oslo",
    "portugal":       "Europe/Lisbon",
    "austria":        "Europe/Vienna",
    "switzerland":    "Europe/Zurich",
    "czech republic": "Europe/Prague",
    "hungary":        "Europe/Budapest",
    "romania":        "Europe/Bucharest",
    "greece":         "Europe/Athens",
    "turkey":         "Europe/Istanbul",
    "united kingdom": "Europe/London",
    "uk":             "Europe/London",
    "united states":  "America/New_York",
    "usa":            "America/New_York",
}

# Country → region label (for gap tracking)
COUNTRY_REGION = {
    "india":          "South Asia",
    "china":          "East Asia",
    "vietnam":        "Southeast Asia",
    "uae":            "Middle East",
    "saudi arabia":   "Middle East",
    "qatar":          "Middle East",
    "kuwait":         "Middle East",
    "bahrain":        "Middle East",
    "oman":           "Middle East",
    "jordan":         "Middle East",
    "egypt":          "Middle East",
    "germany":        "Europe",
    "netherlands":    "Europe",
    "belgium":        "Europe",
    "france":         "Europe",
    "italy":          "Europe",
    "spain":          "Europe",
    "poland":         "Europe",
    "sweden":         "Europe",
    "denmark":        "Europe",
    "finland":        "Europe",
    "norway":         "Europe",
    "portugal":       "Europe",
    "austria":        "Europe",
    "switzerland":    "Europe",
    "czech republic": "Europe",
    "hungary":        "Europe",
    "romania":        "Europe",
    "greece":         "Europe",
    "turkey":         "Europe",
    "united kingdom": "Europe",
    "uk":             "Europe",
}

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _country_key(country_str):
    return (country_str or "").strip().lower()


def _get_lane_groups_for_country(country):
    key = _country_key(country)
    if key in COUNTRY_LANE_GROUPS:
        return COUNTRY_LANE_GROUPS[key]
    for k, groups in COUNTRY_LANE_GROUPS.items():
        if k in key or key in k:
            return groups
    return []


def _get_lanes_for_groups(lane_groups):
    """Query the lanes table for distinct carrier+origin+destination combos."""
    if not lane_groups:
        return []
    conn = get_db()
    results = []
    for group in lane_groups:
        rows = conn.execute(
            """SELECT DISTINCT carrier, origin_name, destination_name, etd
               FROM lanes
               WHERE (LOWER(lane_key) LIKE LOWER(?) OR
                      LOWER(origin_name) LIKE LOWER(?) OR
                      LOWER(destination_name) LIKE LOWER(?))
                 AND lane_status = 'active'
               ORDER BY carrier, origin_name, destination_name""",
            (f"%{group}%", f"%{group}%", f"%{group}%"),
        ).fetchall()
        results.extend([dict(r) for r in rows])
    conn.close()
    seen = set()
    unique = []
    for r in results:
        key = (r["carrier"], r["origin_name"], r["destination_name"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _cycle_date_range(cycle):
    """Parse a cycle string like '2026-04-01_15' → (valid_from, valid_to)."""
    try:
        parts = cycle.split("_")
        base  = parts[0]
        day   = int(parts[1])
        dt_from = datetime.strptime(base, "%Y-%m-%d")
        dt_to   = dt_from.replace(day=day)
        return dt_from.strftime("%Y-%m-%d"), dt_to.strftime("%Y-%m-%d")
    except Exception:
        today = datetime.now()
        return today.strftime("%Y-%m-%d"), (today + timedelta(days=14)).strftime("%Y-%m-%d")


def _build_cycle_for_date(date):
    """Given a date, return the cycle string for the upcoming half-month."""
    day = date.day
    if day in (26, 27, 28, 29, 30, 31):
        if date.month == 12:
            next_month = date.replace(year=date.year + 1, month=1, day=1)
        else:
            next_month = date.replace(month=date.month + 1, day=1)
        return next_month.strftime("%Y-%m-01_15")
    elif day in (9, 10):
        last_day = calendar.monthrange(date.year, date.month)[1]
        return date.strftime(f"%Y-%m-16_{last_day}")
    else:
        if day <= 15:
            return date.strftime("%Y-%m-01_15")
        else:
            last_day = calendar.monthrange(date.year, date.month)[1]
            return date.strftime(f"%Y-%m-16_{last_day}")


def _last_day_of_month(year, month):
    return calendar.monthrange(year, month)[1]


# ---------------------------------------------------------------------------
#  NEW API: get_lanes_for_contact
# ---------------------------------------------------------------------------

def get_lanes_for_contact(contact):
    """Return relevant lanes from lanes DB based on contact's country.

    Returns list of lane dicts with: carrier, origin_name, destination_name, etd
    """
    country     = contact.get("country", "")
    lane_groups = _get_lane_groups_for_country(country)
    return _get_lanes_for_groups(lane_groups)


# ---------------------------------------------------------------------------
#  NEW API: build_email_body
# ---------------------------------------------------------------------------

def build_email_body(contact, lanes, cycle):
    """Generate the outreach email text.

    Returns {"subject": str, "body": str}
    """
    contact_name = contact.get("contact_name") or contact.get("company_name", "there")
    first_name   = contact_name.split()[0] if contact_name else "there"
    country      = contact.get("country", "")

    if hasattr(cycle, "get"):
        # cycle is a dict (rate_cycle row)
        valid_from = cycle.get("valid_from", "")
        valid_to   = cycle.get("valid_to",   "")
    else:
        # cycle is a string like "2026-04-01_15"
        valid_from, valid_to = _cycle_date_range(cycle)

    subject = f"Rate Request — {country} Origin to North America | {valid_from} to {valid_to}"

    if not lanes:
        body = (
            f"Dear {first_name},\n\n"
            f"We are collecting ocean freight rates for the period {valid_from} to {valid_to}.\n\n"
            f"Please provide your best FCL rates (20ft and 40ft) for all available lanes "
            f"originating from {country}.\n\n"
            f"Required information per lane:\n"
            f"- Carrier\n"
            f"- Rate 20ft (USD)\n"
            f"- Rate 40ft (USD)\n"
            f"- Validity dates\n\n"
            f"Thank you,\n[signature placeholder]"
        )
    else:
        by_carrier = {}
        for lane in lanes:
            c = lane.get("carrier") or lane.get("carrier_name") or "General"
            by_carrier.setdefault(c, []).append(lane)

        lane_lines = []
        for carrier, carrier_lanes in sorted(by_carrier.items()):
            lane_lines.append(f"\n  {carrier}:")
            for l in carrier_lanes:
                origin = l.get("origin_name") or l.get("origin", "")
                dest   = l.get("destination_name") or l.get("destination", "")
                lane_lines.append(f"    - {origin} → {dest}")

        lane_block = "\n".join(lane_lines)

        body = (
            f"Dear {first_name},\n\n"
            f"We are collecting ocean freight rates for the period {valid_from} to {valid_to}.\n\n"
            f"Please provide rates for the following lanes:\n"
            f"{lane_block}\n\n"
            f"Required information per lane:\n"
            f"- Carrier\n"
            f"- Rate 20ft (USD)\n"
            f"- Rate 40ft (USD)\n"
            f"- Validity dates\n\n"
            f"Thank you,\n[signature placeholder]"
        )

    return {"subject": subject, "body": body}


# ---------------------------------------------------------------------------
#  NEW API: parse_rate_reply
# ---------------------------------------------------------------------------

_CARRIER_NAMES = [
    "Maersk", "MSC", "CMA CGM", "CMA-CGM", "COSCO", "Hapag-Lloyd", "Hapag",
    "ONE", "Evergreen", "Yang Ming", "HMM", "OOCL", "PIL", "ZIM",
    "Wan Hai", "WanHai", "T.S. Lines", "TS Lines",
]

_CURRENCY_RE = re.compile(
    r"\b(USD|EUR|GBP|INR|CNY|RMB|SGD|AED|SAR|VND|JPY|KRW|HKD)\b", re.I
)
_DATE_RE = re.compile(
    r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)


def _normalise_date(s):
    s = s.strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m-%d-%Y", "%B %d %Y", "%b %d %Y",
                "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _extract_carrier(text):
    text_lower = text.lower()
    for name in _CARRIER_NAMES:
        if name.lower() in text_lower:
            return name
    return None


def _extract_port_pair(text, known_origins, known_destinations):
    found_origin = None
    found_dest   = None
    text_lower   = text.lower()
    for port in known_origins:
        if port.lower() in text_lower:
            found_origin = port
            break
    for port in known_destinations:
        if port.lower() in text_lower:
            found_dest = port
            break
    return found_origin, found_dest


def _extract_rates(text):
    rate_20 = None
    rate_40 = None
    lines = text.splitlines()
    for line in lines:
        line_l = line.lower()
        nums   = [float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", line)]
        if not nums:
            continue
        if "20" in line_l and rate_20 is None:
            rate_20 = nums[0]
        if "40" in line_l and rate_40 is None:
            rate_40 = nums[0] if len(nums) == 1 else nums[-1]
    if rate_20 is None and rate_40 is None:
        all_nums = [float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]
        if len(all_nums) >= 2:
            rate_20 = all_nums[0]
            rate_40 = all_nums[1]
    return rate_20, rate_40


def _match_etd_from_lanes(carrier, origin, destination):
    """Look up the closest upcoming ETD from the lanes table."""
    if not (carrier and origin and destination):
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    conn  = get_db()
    row   = conn.execute(
        """SELECT etd FROM lanes
           WHERE LOWER(carrier) = LOWER(?)
             AND LOWER(origin_name) = LOWER(?)
             AND LOWER(destination_name) = LOWER(?)
             AND etd >= ?
           ORDER BY etd ASC LIMIT 1""",
        (carrier, origin, destination, today),
    ).fetchone()
    conn.close()
    return row["etd"] if row else None


def parse_rate_reply(email_text, contact, cycle):
    """Smart parser for agent email replies.

    Args:
        email_text: raw email reply text
        contact: contact dict (must have id, country)
        cycle: rate_cycle dict or cycle string

    Returns:
        {
            "rates":      list of extracted rate dicts,
            "gap_flags":  list of missing field names,
            "extracted":  flat dict of parsed fields (for display),
            "quality_score": int 0-100,
        }
    """
    conn = get_db()
    origins      = [r[0] for r in conn.execute(
        "SELECT DISTINCT origin_name FROM lanes WHERE origin_name != ''"
    ).fetchall()]
    destinations = [r[0] for r in conn.execute(
        "SELECT DISTINCT destination_name FROM lanes WHERE destination_name != ''"
    ).fetchall()]
    conn.close()

    extracted = {}

    carrier = _extract_carrier(email_text)
    if carrier:
        extracted["carrier"] = carrier

    origin, destination = _extract_port_pair(email_text, origins, destinations)
    if origin:
        extracted["origin"] = origin
    if destination:
        extracted["destination"] = destination

    rate_20, rate_40 = _extract_rates(email_text)
    if rate_20 is not None:
        extracted["rate_20ft"] = rate_20
    if rate_40 is not None:
        extracted["rate_40ft"] = rate_40

    cur_match = _CURRENCY_RE.search(email_text)
    extracted["currency"] = cur_match.group(0).upper() if cur_match else "USD"

    dates = [_normalise_date(m) for m in _DATE_RE.findall(email_text)]
    dates = sorted(set(dates))
    if len(dates) >= 2:
        extracted["valid_from"] = dates[0]
        extracted["valid_to"]   = dates[-1]
    elif len(dates) == 1:
        extracted["valid_from"] = dates[0]

    # ETD match from lanes
    etd = _match_etd_from_lanes(
        extracted.get("carrier"),
        extracted.get("origin"),
        extracted.get("destination"),
    )
    if etd:
        extracted["etd_matched"] = etd

    # Gap detection
    required  = ["carrier", "origin", "destination", "rate_20ft", "rate_40ft", "valid_from", "valid_to"]
    gap_flags = [f for f in required if f not in extracted]

    quality_score = round((len(required) - len(gap_flags)) / len(required) * 100)

    # Build rate dict
    cycle_id = None
    if hasattr(cycle, "get"):
        cycle_id = cycle.get("id")

    rate_dict = {
        "cycle_id":    cycle_id,
        "contact_id":  contact.get("id"),
        "carrier":     extracted.get("carrier", ""),
        "origin":      extracted.get("origin", ""),
        "destination": extracted.get("destination", ""),
        "rate_20ft":   extracted.get("rate_20ft"),
        "rate_40ft":   extracted.get("rate_40ft"),
        "valid_from":  extracted.get("valid_from", ""),
        "valid_to":    extracted.get("valid_to", ""),
        "etd":         extracted.get("etd_matched", ""),
        "currency":    extracted.get("currency", "USD"),
        "received_at": datetime.now().isoformat(timespec="seconds"),
        "raw_text":    email_text[:1000],
    }

    return {
        "rates":         [rate_dict],
        "gap_flags":     gap_flags,
        "extracted":     extracted,
        "quality_score": quality_score,
    }


# ---------------------------------------------------------------------------
#  NEW API: record_gaps
# ---------------------------------------------------------------------------

def record_gaps(contact_id, region, gap_flags):
    """Upsert into rate_gaps table, incrementing occurrences per gap_field."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    conn    = get_db()
    for field in gap_flags:
        existing = conn.execute(
            "SELECT id, occurrences FROM rate_gaps WHERE contact_id=? AND gap_field=?",
            (contact_id, field),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE rate_gaps SET occurrences=?, last_seen=? WHERE id=?",
                (existing["occurrences"] + 1, now_iso, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO rate_gaps (contact_id, region, gap_field, occurrences, last_seen) VALUES (?,?,?,1,?)",
                (contact_id, region or "", field, now_iso),
            )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
#  NEW API: generate_cycle
# ---------------------------------------------------------------------------

def generate_cycle(month, year, cycle_num):
    """Create a rate_cycle record.

    cycle_num=1: valid 1-15, send_date=26th of prior month
    cycle_num=2: valid 16-last_day, send_date=9th of month

    Returns the newly created cycle dict.
    """
    if cycle_num == 1:
        valid_from = f"{year:04d}-{month:02d}-01"
        valid_to   = f"{year:04d}-{month:02d}-15"
        # send_date = 26th of previous month
        if month == 1:
            send_month = 12
            send_year  = year - 1
        else:
            send_month = month - 1
            send_year  = year
        send_date  = f"{send_year:04d}-{send_month:02d}-26"
        cycle_name = f"{year:04d}-{month:02d} Cycle 1 (1-15)"
    else:
        last_day   = _last_day_of_month(year, month)
        valid_from = f"{year:04d}-{month:02d}-16"
        valid_to   = f"{year:04d}-{month:02d}-{last_day:02d}"
        send_date  = f"{year:04d}-{month:02d}-09"
        cycle_name = f"{year:04d}-{month:02d} Cycle 2 (16-{last_day})"

    conn = get_db()
    cur  = conn.execute(
        """INSERT INTO rate_cycles (cycle_name, valid_from, valid_to, send_date, status)
           VALUES (?, ?, ?, ?, 'pending')""",
        (cycle_name, valid_from, valid_to, send_date),
    )
    cycle_id = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM rate_cycles WHERE id=?", (cycle_id,)).fetchone()
    conn.close()
    return dict(row)


# ---------------------------------------------------------------------------
#  NEW API: get_pending_reminders
# ---------------------------------------------------------------------------

def get_pending_reminders():
    """Return all outreach records where status='sent', sent >24 business hours ago,
    and no response yet."""
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
    conn   = get_db()
    rows   = conn.execute(
        """SELECT ro.*, c.country
           FROM rate_outreach ro
           LEFT JOIN contacts c ON c.id = ro.contact_id
           WHERE ro.status = 'sent'
             AND ro.sent_at <= ?
             AND (ro.responded_at IS NULL OR ro.responded_at = '')""",
        (cutoff,),
    ).fetchall()
    conn.close()
    pending = []
    for row in rows:
        r           = dict(row)
        local_hour  = _local_hour_for_country(r.get("contact_country") or r.get("country") or "")
        if 8 <= local_hour < 20:
            pending.append(r)
    return pending


# ---------------------------------------------------------------------------
#  NEW API: get_cycle_stats
# ---------------------------------------------------------------------------

def get_cycle_stats(cycle_id):
    """Return stats dict for a given cycle_id."""
    conn = get_db()

    total_sent = conn.execute(
        "SELECT COUNT(*) FROM rate_outreach WHERE cycle_id=? AND status != 'pending'",
        (cycle_id,),
    ).fetchone()[0]

    total_responded = conn.execute(
        "SELECT COUNT(*) FROM rate_outreach WHERE cycle_id=? AND status='responded'",
        (cycle_id,),
    ).fetchone()[0]

    total_no_response = conn.execute(
        "SELECT COUNT(*) FROM rate_outreach WHERE cycle_id=? AND status='no_response'",
        (cycle_id,),
    ).fetchone()[0]

    total_rates = conn.execute(
        "SELECT COUNT(*) FROM rates WHERE cycle_id=?",
        (cycle_id,),
    ).fetchone()[0]

    # Gaps by field
    gap_rows = conn.execute(
        """SELECT gap_field, SUM(occurrences) as cnt
           FROM rate_gaps rg
           JOIN rate_outreach ro ON ro.contact_id = rg.contact_id
           WHERE ro.cycle_id = ?
           GROUP BY gap_field ORDER BY cnt DESC""",
        (cycle_id,),
    ).fetchall()
    gaps_by_field = {r["gap_field"]: r["cnt"] for r in gap_rows}

    conn.close()

    return {
        "total_sent":          total_sent,
        "total_responded":     total_responded,
        "total_no_response":   total_no_response,
        "total_rates_collected": total_rates,
        "gaps_by_field":       gaps_by_field,
    }


# ---------------------------------------------------------------------------
#  Legacy helpers (keep for backward compat with old app.py routes)
# ---------------------------------------------------------------------------

def _local_hour_for_country(country):
    """Return the current hour in the contact's local timezone."""
    key     = _country_key(country)
    tz_name = COUNTRY_TIMEZONES.get(key, "UTC")
    try:
        import zoneinfo
        tz  = zoneinfo.ZoneInfo(tz_name)
        now = datetime.now(tz)
        return now.hour
    except Exception:
        try:
            import pytz
            tz  = pytz.timezone(tz_name)
            now = datetime.now(pytz.utc).astimezone(tz)
            return now.hour
        except Exception:
            return datetime.utcnow().hour


def build_request_email(contact):
    """Legacy: generate a personalised rate-request email for a single contact dict.

    Returns {"subject": str, "body": str, "lanes": list, "lane_groups": list, ...}
    """
    country     = contact.get("country", "")
    lane_groups = _get_lane_groups_for_country(country)
    lanes       = _get_lanes_for_groups(lane_groups)

    today      = datetime.now()
    cycle_str  = _build_cycle_for_date(today)
    valid_from, valid_to = _cycle_date_range(cycle_str)

    # Reuse new builder
    cycle_mock = {"valid_from": valid_from, "valid_to": valid_to}
    email_data = build_email_body(contact, lanes, cycle_mock)

    return {
        "subject":     email_data["subject"],
        "body":        email_data["body"],
        "lanes":       lanes,
        "lane_groups": lane_groups,
        "cycle":       cycle_str,
        "valid_from":  valid_from,
        "valid_to":    valid_to,
    }


def send_rate_requests(cycle):
    """Send rate request emails to all verified contacts for the given cycle.
    Uses Microsoft Graph API (no SMTP required).

    Returns {"sent": int, "skipped": int, "errors": list, "warning": str|None}
    """
    import mailer as _mailer
    from config import GRAPH_CLIENT_SECRET

    if not GRAPH_CLIENT_SECRET:
        return {
            "sent":    0,
            "skipped": 0,
            "errors":  [],
            "warning": "GRAPH_CLIENT_SECRET is not configured in config.py.",
        }

    conn     = get_db()
    contacts = conn.execute(
        "SELECT * FROM contacts WHERE verified_status = 'verified' AND "
        "email IS NOT NULL AND TRIM(email) != ''"
    ).fetchall()
    contacts = [dict(c) for c in contacts]
    conn.close()

    sent    = 0
    skipped = 0
    errors  = []
    now_iso = datetime.now().isoformat(timespec="seconds")

    for contact in contacts:
        try:
            email_data = build_request_email(contact)
        except Exception as exc:
            skipped += 1
            errors.append(f"{contact.get('company_name','?')}: build failed — {exc}")
            continue

        if not email_data["lanes"] and not email_data["lane_groups"]:
            skipped += 1
            continue

        lane_strings = [
            f"{l['carrier']} | {l['origin_name']} → {l['destination_name']}"
            for l in email_data["lanes"]
        ]

        try:
            _mailer.send_rate_request(contact, cycle, lanes=lane_strings)
        except Exception as exc:
            errors.append(f"{contact['email']}: send failed — {exc}")
            skipped += 1
            continue

        conn = get_db()
        conn.execute(
            """INSERT INTO rate_requests
               (contact_id, sent_at, cycle, lanes_requested, reminder_sent, responded)
               VALUES (?, ?, ?, ?, 0, 0)""",
            (
                contact["id"],
                now_iso,
                cycle,
                json.dumps([
                    {"carrier": l["carrier"], "origin": l["origin_name"],
                     "destination": l["destination_name"]}
                    for l in email_data["lanes"]
                ]),
            ),
        )
        conn.commit()
        conn.close()
        sent += 1

    return {"sent": sent, "skipped": skipped, "errors": errors, "warning": None}


def check_reminders():
    """Find contacts who received a request >24h ago and send reminders.
    Uses Microsoft Graph API (no SMTP required).

    Returns {"reminded": int, "skipped": int, "errors": list, "warning": str|None}
    """
    import mailer as _mailer
    from config import GRAPH_CLIENT_SECRET, EMAIL_FROM

    if not GRAPH_CLIENT_SECRET:
        return {
            "reminded": 0,
            "skipped":  0,
            "errors":   [],
            "warning":  "GRAPH_CLIENT_SECRET is not configured. Reminders require Graph API credentials.",
        }

    cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")

    conn    = get_db()
    pending = conn.execute(
        """SELECT rr.id, rr.contact_id, rr.sent_at, rr.cycle, rr.lanes_requested,
                  c.email, c.company_name, c.contact_name, c.country
           FROM rate_requests rr
           JOIN contacts c ON c.id = rr.contact_id
           WHERE rr.responded = 0
             AND rr.reminder_sent = 0
             AND rr.sent_at <= ?
             AND c.email IS NOT NULL AND TRIM(c.email) != ''""",
        (cutoff,),
    ).fetchall()
    pending = [dict(r) for r in pending]
    conn.close()

    reminded = 0
    skipped  = 0
    errors   = []

    if not pending:
        return {"reminded": 0, "skipped": 0, "errors": [], "warning": None}

    now_iso = datetime.now().isoformat(timespec="seconds")

    for req in pending:
        local_hour = _local_hour_for_country(req["country"])
        if not (8 <= local_hour < 20):
            skipped += 1
            continue

        contact_name = req.get("contact_name") or req.get("company_name", "there")
        first_name   = contact_name.split()[0] if contact_name else "there"
        valid_from, valid_to = _cycle_date_range(req["cycle"])
        lanes_requested = json.loads(req["lanes_requested"] or "[]")

        lane_items = "".join(
            f"<li>{l.get('carrier','')} — {l.get('origin','')} &rarr; {l.get('destination','')}</li>"
            for l in lanes_requested
        ) or "<li>(all available lanes)</li>"

        subject   = f"Reminder: Rate Request — {valid_from} to {valid_to}"
        from mailer import SIGNATURE as _SIG, _display_name_for_country as _dn
        sender_name = _dn(req.get("country", ""))
        body_html = f"""
<p>Dear {first_name},</p>
<p>This is a friendly reminder regarding our rate request sent on {req['sent_at'][:10]}.</p>
<p>We are still awaiting rates for the period <strong>{valid_from} to {valid_to}</strong>
for the following lanes:</p>
<ul>{lane_items}</ul>
<p>Please reply at your earliest convenience (business hours 8 AM–8 PM your local time).</p>
{_SIG}
"""

        try:
            _mailer.send_email(
                to_address=req["email"],
                subject=subject,
                body_html=body_html,
                display_name=sender_name,
                reply_to=EMAIL_FROM,
            )
        except Exception as exc:
            errors.append(f"{req['email']}: reminder failed — {exc}")
            skipped += 1
            continue

        conn = get_db()
        conn.execute(
            "UPDATE rate_requests SET reminder_sent = 1 WHERE id = ?",
            (req["id"],),
        )
        conn.commit()
        conn.close()
        reminded += 1

    return {"reminded": reminded, "skipped": skipped, "errors": errors, "warning": None}


def parse_rate_response(email_body, contact_id, cycle):
    """Legacy: Parse an email body for rate data, save to DB, return structured result.

    Returns {extracted, missing_fields, quality_score, rate_id, gap_id}
    """
    # Resolve contact
    conn    = get_db()
    contact = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
    conn.close()
    contact_dict = dict(contact) if contact else {"id": contact_id, "country": ""}

    # Use new parser
    result = parse_rate_reply(email_body, contact_dict, cycle)
    extracted     = result["extracted"]
    missing_fields = result["gap_flags"]
    quality_score = result["quality_score"]

    now_iso = datetime.now().isoformat(timespec="seconds")

    # Build cycle string for legacy compat
    cycle_str = cycle if isinstance(cycle, str) else _build_cycle_for_date(datetime.now())

    # Save to rates table (legacy columns)
    rate_id = None
    if extracted:
        conn = get_db()
        cur  = conn.execute(
            """INSERT INTO rates
               (contact_id, carrier, origin, destination,
                rate_20ft, rate_40ft, valid_from, valid_to,
                currency, source_email, parsed_at, verified, cycle,
                etd, received_at, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                contact_id,
                extracted.get("carrier", ""),
                extracted.get("origin", ""),
                extracted.get("destination", ""),
                extracted.get("rate_20ft"),
                extracted.get("rate_40ft"),
                extracted.get("valid_from", ""),
                extracted.get("valid_to", ""),
                extracted.get("currency", "USD"),
                email_body[:500],
                now_iso,
                cycle_str,
                extracted.get("etd_matched", ""),
                now_iso,
                email_body[:1000],
            ),
        )
        rate_id = cur.lastrowid
        conn.execute(
            """UPDATE rate_requests
               SET responded = 1, response_at = ?, response_quality = ?
               WHERE contact_id = ? AND cycle = ? AND responded = 0""",
            (now_iso, quality_score, contact_id, cycle_str),
        )
        conn.commit()
        conn.close()

    gap_id = None
    if missing_fields:
        # Record gaps using new upsert
        country = contact_dict.get("country", "")
        region  = COUNTRY_REGION.get(_country_key(country), country)
        record_gaps(contact_id, region, missing_fields)

        # Legacy: insert into rate_gaps
        conn   = get_db()
        cur    = conn.execute(
            """INSERT INTO rate_gaps (contact_id, region, gap_field, occurrences, last_seen)
               VALUES (?, ?, ?, 1, ?)""",
            (contact_id, region, json.dumps(missing_fields), now_iso),
        )
        gap_id = cur.lastrowid
        conn.commit()
        conn.close()

    return {
        "extracted":      extracted,
        "missing_fields": missing_fields,
        "quality_score":  quality_score,
        "rate_id":        rate_id,
        "gap_id":         gap_id,
    }


def gap_report():
    """Legacy: Analyse rate_gaps table.

    Returns {total_gaps, by_field, by_country, top_missing, by_contact}
    """
    conn = get_db()
    # Use new schema if gap_field column exists
    from database import _get_existing_columns
    gap_cols = _get_existing_columns(conn, "rate_gaps")

    if "gap_field" in gap_cols:
        gaps = conn.execute(
            """SELECT rg.gap_field, rg.occurrences, rg.contact_id, rg.region,
                      c.country, c.company_name
               FROM rate_gaps rg
               LEFT JOIN contacts c ON c.id = rg.contact_id
               ORDER BY rg.occurrences DESC"""
        ).fetchall()
        conn.close()

        by_field   = {}
        by_country = {}
        by_contact = {}
        total_gaps = 0

        for row in gaps:
            field   = row["gap_field"] or ""
            country = (row["country"] or row["region"] or "Unknown").strip()
            company = (row["company_name"] or "Unknown").strip()
            n       = row["occurrences"] or 1
            total_gaps += n

            by_field[field] = by_field.get(field, 0) + n
            if country not in by_country:
                by_country[country] = {}
            by_country[country][field] = by_country[country].get(field, 0) + n

            key = (row["contact_id"], company, country)
            if key not in by_contact:
                by_contact[key] = {"gap_count": 0, "quality_sum": 0, "quality_n": 0}
            by_contact[key]["gap_count"] += n

        top_missing = sorted(
            [{"field": f, "count": c,
              "pct": round(c / total_gaps * 100, 1) if total_gaps else 0}
             for f, c in by_field.items()],
            key=lambda x: x["count"], reverse=True,
        )

        contact_summary = [
            {
                "contact_id":   cid,
                "company_name": company,
                "country":      country,
                "gap_count":    data["gap_count"],
                "avg_quality":  0,
            }
            for (cid, company, country), data in by_contact.items()
        ]
        contact_summary.sort(key=lambda x: x["gap_count"], reverse=True)

    else:
        # Old schema fallback
        import json as _json
        gaps = conn.execute(
            """SELECT rg.missing_fields, rg.contact_id,
                      c.country, c.company_name
               FROM rate_gaps rg
               LEFT JOIN contacts c ON c.id = rg.contact_id"""
        ).fetchall()
        conn.close()

        by_field   = {}
        by_country = {}
        by_contact = {}
        total_gaps = len(gaps)

        for row in gaps:
            fields  = _json.loads(row["missing_fields"] or "[]")
            country = (row["country"] or "Unknown").strip()
            company = (row["company_name"] or "Unknown").strip()
            for f in fields:
                by_field[f] = by_field.get(f, 0) + 1
                if country not in by_country:
                    by_country[country] = {}
                by_country[country][f] = by_country[country].get(f, 0) + 1
            key = (row["contact_id"], company, country)
            if key not in by_contact:
                by_contact[key] = {"gap_count": 0}
            by_contact[key]["gap_count"] += 1

        top_missing = sorted(
            [{"field": f, "count": c,
              "pct": round(c / total_gaps * 100, 1) if total_gaps else 0}
             for f, c in by_field.items()],
            key=lambda x: x["count"], reverse=True,
        )
        contact_summary = [
            {"contact_id": cid, "company_name": company, "country": country,
             "gap_count": data["gap_count"], "avg_quality": 0}
            for (cid, company, country), data in by_contact.items()
        ]
        contact_summary.sort(key=lambda x: x["gap_count"], reverse=True)

    return {
        "total_gaps":  total_gaps,
        "by_field":    by_field,
        "by_country":  by_country,
        "top_missing": top_missing,
        "by_contact":  contact_summary,
    }


# ---------------------------------------------------------------------------
#  Scheduler helpers
# ---------------------------------------------------------------------------

def scheduled_send_26th():
    """Triggered on the 26th — sends requests for 1-15 of next month."""
    today = datetime.now()
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
    cycle = next_month.strftime("%Y-%m-01_15")
    return send_rate_requests(cycle)


def scheduled_send_9th():
    """Triggered on the 9th — sends requests for 16-31 of that month."""
    today    = datetime.now()
    last_day = _last_day_of_month(today.year, today.month)
    cycle    = today.strftime(f"%Y-%m-16_{last_day}")
    return send_rate_requests(cycle)


def start_scheduler(app_context_func):
    """Launch background threads for scheduled sends and reminder checks."""
    import time as _time

    def _reminder_loop():
        while True:
            _time.sleep(2 * 3600)
            try:
                app_context_func(check_reminders)
            except Exception as exc:
                print(f"[rate_engine] Reminder loop error: {exc}")

    def _send_loop():
        while True:
            _time.sleep(3600)
            try:
                today = datetime.now()
                if today.day == 26 and today.hour == 8:
                    app_context_func(scheduled_send_26th)
                elif today.day == 9 and today.hour == 8:
                    app_context_func(scheduled_send_9th)
            except Exception as exc:
                print(f"[rate_engine] Send loop error: {exc}")

    threading.Thread(target=_reminder_loop, daemon=True, name="rate-reminders").start()
    threading.Thread(target=_send_loop,     daemon=True, name="rate-scheduler").start()
    print("[rate_engine] Scheduler started (reminders every 2h, send checks every 1h).")
