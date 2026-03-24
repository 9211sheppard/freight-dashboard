"""
intro_mailer.py — First-contact intro email for freight agent outreach
Primed for trust, personalized by country, one-click lane/carrier selection.
Every email is psychologically unique — book techniques woven into every element.
"""

import json
import logging
import random
import secrets
import time
from datetime import datetime, timezone, date

from database import get_db
from mailer import send_email, SIGNATURE, signature_for, _display_name_for_country, _from_address_for_name
from contact_engine import (
    get_lanes_for_country, get_psych_elements, get_country_motto,
    record_send_analytics,
)

log = logging.getLogger(__name__)

# ── Public tunnel base URL (used in one-click tracking links) ─────────────────
# Update this whenever the Cloudflare tunnel URL changes.
TRACKING_BASE = "https://go.flashcargoglobal.com"

# ── Lane display labels ───────────────────────────────────────────────────────
_LANE_LABELS = {
    "USA":           "USA / Canada",
    "Canada":        "USA / Canada",
    "Europe":        "Europe",
    "Middle East":   "Middle East",
    "Far East":      "Far East / Asia Pacific",
    "South America": "South America",
    "Africa":        "Africa",
    "Australia":     "Australia / Oceania",
    "Mexico":        "Mexico / Central America",
}

_LANE_ORDER = [
    "USA / Canada",
    "Europe",
    "Middle East",
    "South America",
    "Far East / Asia Pacific",
    "Africa",
    "Australia / Oceania",
    "Mexico / Central America",
]

# Slug map: display label → URL slug (no spaces or slashes)
_LANE_SLUG = {
    "USA / Canada":              "usa-canada",
    "Europe":                    "europe",
    "Middle East":               "middle-east",
    "South America":             "south-america",
    "Far East / Asia Pacific":   "far-east",
    "Africa":                    "africa",
    "Australia / Oceania":       "australia",
    "Mexico / Central America":  "mexico",
    "All destinations":          "all",
}

# Major shipping lines offered as one-click options
_CARRIER_OPTIONS = [
    "Maersk", "MSC", "CMA CGM", "Hapag-Lloyd",
    "COSCO", "ONE", "Evergreen", "Yang Ming",
    "ZIM", "PIL", "Arkas", "Other",
]

_CARRIER_SLUG = {c: c.lower().replace(" ", "-").replace("/", "-") for c in _CARRIER_OPTIONS}


def _dedupe_lane_labels(regions: list) -> list:
    seen = set()
    labels = []
    for r in regions:
        label = _LANE_LABELS.get(r, r)
        if label not in seen:
            seen.add(label)
            labels.append(label)

    def sort_key(lbl):
        try:
            return _LANE_ORDER.index(lbl)
        except ValueError:
            return 999

    return sorted(labels, key=sort_key)


def _mailto_btn(label: str, mailto_url: str, color: str = "#1a73e8") -> str:
    """Styled button that opens a pre-filled reply — no browser, no popup."""
    return (
        f'<a href="{mailto_url}" '
        f'style="display:inline-block;background:{color};color:#ffffff;'
        f'padding:9px 18px;border-radius:5px;text-decoration:none;'
        f'font-size:14px;font-weight:600;margin:4px 6px 4px 0;'
        f'font-family:Arial,sans-serif;letter-spacing:0.2px;">'
        f'{label}</a>'
    )


def _generate_token() -> str:
    return secrets.token_urlsafe(16)


def build_intro_email(contact: dict, token: str = "") -> tuple:
    """
    Build the intro email — numbered lanes, lettered carriers, human tone.
    Each email is UNIQUE: subject, opener, context, CTA, footer, and psych
    elements all vary per contact using a deterministic seed.

    INTRO-SAFE psych elements only (stage-enforced):
    - Social proof (Influence — Cialdini)
    - Make-it-easy language (Atomic Habits)
    - Make-them-important line (How to Win Friends)
    - Cultural motto (country trust signal)
    - Opening hook (neutral/flattery only — no accusation audit)
    BANNED at intro stage: calibrated questions, labels, scarcity, win-win.

    Returns (subject, body_html).
    """
    import urllib.parse

    contact_id   = contact.get("id") or 0
    country      = (contact.get("country") or "").strip()
    city         = (contact.get("city") or "").strip()
    company_name = (contact.get("company_name") or "").strip()
    contact_name = (contact.get("contact_name") or "").strip()
    email        = (contact.get("email") or "").strip()

    first_name    = contact_name.split()[0] if contact_name else ""
    greeting_name = first_name or company_name or "there"

    location_str = f"{city}, {country}" if city and country else (city or country or "your region")
    from_label   = country if country else "your region"

    regions     = get_lanes_for_country(country)
    lane_labels = _dedupe_lane_labels(regions)

    sender_name_full = _display_name_for_country(country, contact_id, contact_first_name=first_name)
    sender_first = sender_name_full.split("|")[0].split()[0].strip()

    # ── Psychological elements (book-driven, INTRO stage only) ───────────────
    # email_stage="intro" enforces: social_proof + make_easy only.
    # calibrated_q, labels, scarcity, win-win are all None at this stage.
    psych = get_psych_elements(contact, "unknown", 0, email_stage="intro")

    # ── Per-contact RNG for unique variation ──────────────────────────────────
    _seed = hash(f"{contact_id}-{email}-{date.today().isoformat()}")
    _rng = random.Random(_seed)

    # ── Subject line variations ───────────────────────────────────────────────
    # Mix of standard subjects + psych-hook-driven subjects for maximum variety
    _loc = city or country or "your region"
    _SUBJECTS = [
        # Standard
        f"Quick question \u2014 {_loc} origin freight | Flash Cargo Global",
        f"Partnership inquiry \u2014 freight from {_loc} | Flash Cargo Global",
        f"Freight from {_loc} \u2014 looking for the right partner",
        f"{sender_first} here \u2014 quick question about {_loc} freight",
        f"Ocean freight from {_loc} \u2014 60 seconds of your time?",
        f"Connecting with agents in {_loc} | Flash Cargo Global",
        f"Cargo from {_loc} \u2014 are you the right fit?",
        # Psych-hook driven (Atomic Habits: make it obvious)
        f"One click \u2014 {_loc} freight partnership | Flash Cargo",
        f"30 seconds \u2014 freight from {_loc} | Flash Cargo Global",
        # Win Friends: genuine interest
        f"Your expertise in {_loc} \u2014 quick question | Flash Cargo",
        f"Impressed by your {_loc} operation | Flash Cargo Global",
        # (calibrated questions banned from intro — moved to engaged stage)
        # Think & Grow Rich: definiteness
        f"Looking for one great partner in {_loc} | Flash Cargo",
        f"We chose your company in {_loc} \u2014 here\u2019s why",
    ]
    subject = _rng.choice(_SUBJECTS)

    # ── Opening paragraph variations ──────────────────────────────────────────
    _OPENERS = [
        f"I\u2019m {sender_first} from <strong>Flash Cargo Global</strong> \u2014 we move ocean and air freight worldwide, and over-the-road across North America.",
        f"My name is {sender_first}, I work with <strong>Flash Cargo Global</strong>. We handle ocean, air, and over-the-road freight across the globe.",
        f"I\u2019m {sender_first} with <strong>Flash Cargo Global</strong> \u2014 we specialize in ocean and air freight, plus trucking across North America.",
        f"{sender_first} here, reaching out from <strong>Flash Cargo Global</strong>. We\u2019re an ocean, air, and OTR freight forwarder with global reach.",
        f"This is {sender_first} from <strong>Flash Cargo Global</strong>. We move cargo by ocean, air, and truck worldwide.",
        f"Hi \u2014 I\u2019m {sender_first} at <strong>Flash Cargo Global</strong>. We\u2019re a freight forwarder covering ocean, air, and road shipments globally.",
    ]

    # ── Context paragraph variations ──────────────────────────────────────────
    _CONTEXTS = [
        f"We came across your company while looking for partners in {location_str}. We have customers moving cargo from your region and want the right local agent on file before anything heads your way.",
        f"Your company stood out as we searched for reliable agents in {location_str}. We regularly move freight from your area and need a trusted partner on the ground.",
        f"We\u2019re building our agent network in {location_str} and your company came up. We have active cargo flows from your region and want to make sure we\u2019re working with the best local team.",
        f"We\u2019ve been expanding in {location_str} and noticed your operation. We route cargo from your market regularly and are looking for the right local partner.",
        f"While sourcing local partners in {location_str}, we found your company. We move freight from your region often and want a reliable agent to work with.",
        f"We handle cargo moving out of {location_str} regularly and are looking for an agent who knows the local market inside out. Your company caught our attention.",
        # 7 Habits: think win-win
        f"We\u2019re looking for a true partner in {location_str} \u2014 not a vendor, but someone who grows when we grow. Your company fits that profile.",
        # Think & Grow Rich: mastermind
        f"We\u2019re assembling a network of top agents worldwide \u2014 and {location_str} is a key piece. Your company came up as a strong candidate.",
    ]

    # ── CTA variations ────────────────────────────────────────────────────────
    _CTAS = [
        "Two quick questions \u2014 one click below and you\u2019re done:",
        "Just two things we\u2019d like to know \u2014 takes under a minute:",
        "We\u2019d love to know two things \u2014 click below to answer in seconds:",
        "Two quick questions for you \u2014 answer with one click:",
        "Here\u2019s what we\u2019d like to know \u2014 takes 30 seconds:",
        # Atomic Habits: make it easy
        "No forms, no calls \u2014 just two clicks and you\u2019re done:",
        "Easiest partnership response you\u2019ll ever make \u2014 two quick picks:",
    ]

    # ── Button label variations ───────────────────────────────────────────────
    _BTN_LABELS = [
        "Select My Coverage \u2192",
        "Choose My Lanes & Carriers \u2192",
        "Click to Respond \u2192",
        "Answer in One Click \u2192",
        "Pick My Routes \u2192",
        "Get Started \u2192",
        "Yes, I\u2019m Interested \u2192",
    ]

    # ── Footer variations ─────────────────────────────────────────────────────
    _FOOTERS = [
        "Once we hear back we\u2019ll add you to our next rate request and only send cargo for the lanes and carriers you selected.",
        "As soon as we get your response, we\u2019ll include you in upcoming rate rounds \u2014 only for the routes you chose.",
        "Reply and we\u2019ll start routing relevant cargo inquiries your way \u2014 strictly for the lanes you pick.",
        "After you respond, we\u2019ll match you with cargo on your selected lanes and carriers only.",
        "Once confirmed, we\u2019ll send rate requests tailored to the exact lanes and carriers you selected.",
        # Atomic Habits: make it satisfying
        "You\u2019ll receive your first rate request within days of responding \u2014 real cargo, real volume.",
        "Once you\u2019re in, cargo inquiries start flowing your way automatically. No extra steps.",
    ]

    # ── Instruction line variations ───────────────────────────────────────────
    _INSTRUCTIONS = [
        "Hit the button \u2014 click the lanes and carriers that apply, then confirm.<br>Takes under a minute, no login required.",
        "Tap the button below, select what applies, and confirm.<br>Under 60 seconds, no account needed.",
        "Click the button, pick your lanes and carriers, and you\u2019re done.<br>Quick and easy \u2014 no signup required.",
        "Use the button to select your coverage \u2014 just pick and confirm.<br>Takes less than a minute.",
    ]

    # ── Pick variations ───────────────────────────────────────────────────────
    opener_html  = _rng.choice(_OPENERS)
    context_html = _rng.choice(_CONTEXTS)
    cta_html     = _rng.choice(_CTAS)
    btn_label    = _rng.choice(_BTN_LABELS)
    footer_html  = _rng.choice(_FOOTERS)
    instr_html   = _rng.choice(_INSTRUCTIONS)

    # ── Numbered lane rows for visual reference ───────────────────────────────
    carrier_letters = "ABCDEFGHIJKL"
    lane_rows_html = "".join(
        f'<tr><td style="font-family:Arial,sans-serif;font-size:13px;color:#1a73e8;font-weight:700;'
        f'padding:3px 10px 3px 0;white-space:nowrap;">{i+1}</td>'
        f'<td style="font-family:Arial,sans-serif;font-size:13px;color:#222;padding:3px 0;">{lbl}</td></tr>'
        for i, lbl in enumerate(lane_labels)
    )

    # ── Lettered carrier list (single column for readability) ──────────────────────
    carrier_rows_html = ""
    for i, c in enumerate(_CARRIER_OPTIONS):
        letter = carrier_letters[i]
        carrier_rows_html += (
            f'<tr><td style="font-family:Arial,sans-serif;font-size:13px;color:#1a73e8;'
            f'font-weight:700;padding:3px 10px 3px 0;white-space:nowrap;">{letter}</td>'
            f'<td style="font-family:Arial,sans-serif;font-size:13px;color:#222;'
            f'padding:3px 0;">{c}</td></tr>'
        )

    # ── Selection page URL (Azure Function) ──────────────────────────────────
    lanes_param = urllib.parse.quote(",".join(lane_labels), safe="")
    selection_url = (
        f"{TRACKING_BASE}/api/respond"
        f"?token={token}"
        f"&country={urllib.parse.quote(country, safe='')}"
        f"&lanes={lanes_param}"
    )

    # ── Build ONE psych line — pick the single best element for this email ──
    # INTRO STAGE ONLY: social proof + make-them-important.
    # win_win_line, calibrated_q, labels, scarcity are all None from get_psych_elements.
    _PSYCH_POOL = []
    if psych.get("social_proof"):
        _PSYCH_POOL.append(psych["social_proof"])
    if psych.get("make_easy_line"):
        _PSYCH_POOL.append(psych["make_easy_line"])
    _IMPORTANT_LINES = [
        f"Your expertise in {from_label} is exactly what sets great agents apart.",
        f"We\u2019re selective about who we work with \u2014 your company stood out in {from_label}.",
        f"Your local knowledge in {from_label} is something we can\u2019t replicate from the US side.",
    ]
    _PSYCH_POOL.append(_rng.choice(_IMPORTANT_LINES))

    psych_line = _rng.choice(_PSYCH_POOL) if _PSYCH_POOL else ""

    # Motto — always in the footer as a subtle cultural touch
    motto_html = ""
    if psych.get("motto_line"):
        motto_html = f"""
<p style="font-family:Arial,sans-serif;font-size:12px;color:#888;margin:16px 0 4px;font-style:italic;">
{psych['motto_line']}
</p>"""

    # ── Assemble body — consistent structure, varied content ─────────────────
    # Structure: greeting → opener → context → psych line → CTA → selection → footer
    body_html = f"""
<p style="font-family:Arial,sans-serif;font-size:15px;color:#222;margin:0 0 16px;">Hi {greeting_name},</p>

<p style="font-family:Arial,sans-serif;font-size:15px;color:#222;margin:0 0 16px;">
{opener_html}
</p>

<p style="font-family:Arial,sans-serif;font-size:15px;color:#222;margin:0 0 16px;">
{context_html}
</p>

<p style="font-family:Arial,sans-serif;font-size:15px;color:#222;margin:0 0 16px;">
{psych_line}
</p>

<p style="font-family:Arial,sans-serif;font-size:15px;color:#222;margin:0 0 12px;">
{cta_html}
</p>

<div style="background:#f7f9ff;border-left:3px solid #1a73e8;padding:14px 18px;margin:0 0 18px;border-radius:0 6px 6px 0;">

  <p style="font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:#111;margin:0 0 8px;">
    1 \u2014 Which destinations can you quote FROM {from_label}?
  </p>
  <table style="border-collapse:collapse;margin:0 0 4px 4px;">
    {lane_rows_html}
  </table>

  <p style="font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:#111;margin:16px 0 8px;">
    2 \u2014 Which shipping lines do you work with?
  </p>
  <table style="border-collapse:collapse;margin:0 0 4px 4px;">
    {carrier_rows_html}
  </table>

</div>

<p style="font-family:Arial,sans-serif;font-size:13px;color:#555;margin:0 0 14px;">
{instr_html}
</p>

<div style="margin:0 0 20px;">
{_mailto_btn(btn_label, selection_url, color="#1a1a2e")}
</div>

<p style="font-family:Arial,sans-serif;font-size:12px;color:#999;margin:0 0 6px;">
{footer_html}
</p>

{motto_html}

{signature_for(sender_name_full)}
"""
    return subject, body_html


def send_intro(contact: dict, test_mode: bool = False) -> bool:
    country     = (contact.get("country") or "").strip()
    contact_id  = contact.get("id")
    contact_name = (contact.get("contact_name") or "").strip()
    contact_first = contact_name.split()[0] if contact_name else None
    sender_name = _display_name_for_country(country, contact_id, contact_first_name=contact_first)
    email       = (contact.get("email") or "").strip()

    if not email:
        log.warning(f"send_intro: no email for contact id={contact_id}")
        return False

    token = _generate_token()

    # ── 5-Agent Email Inspection: build, inspect, retry up to 3 times ─────
    try:
        from email_inspectors import inspect_and_retry, init_inspection_log_db
        try:
            init_inspection_log_db()
        except Exception:
            pass
        subj, html, inspection = inspect_and_retry(
            lambda c, **kw: build_intro_email(c, token=token),
            contact, email_type="intro", max_attempts=3,
        )
        if subj is None:
            log.warning(f"send_intro: all inspections failed for {email} -- skipping")
            return False
        subject, body_html = subj, html
    except ImportError:
        # Fallback: no inspection if module missing
        subject, body_html = build_intro_email(contact, token=token)
    except Exception as exc:
        log.error(f"send_intro inspection error for {email}: {exc}")
        subject, body_html = build_intro_email(contact, token=token)

    try:
        from_addr = _from_address_for_name(sender_name)
        send_email(
            to_address=email,
            subject=subject,
            body_html=body_html,
            from_address=from_addr,
            display_name=sender_name,
            reply_to="pricing@flashcargoglobal.com",
        )
        sent_ok = True
    except Exception as exc:
        log.error(f"send_intro failed for {email}: {exc}")
        sent_ok = False

    if not test_mode and contact_id:
        try:
            conn = get_db()
            conn.execute(
                """
                INSERT INTO intro_outreach
                    (contact_id, email, sender_name, country, sent_at, status, click_token)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    contact_id,
                    email,
                    sender_name,
                    country,
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "sent" if sent_ok else "failed",
                    token,
                ),
            )
            conn.commit()
            conn.close()
        except Exception as db_exc:
            log.error(f"send_intro DB log failed for contact {contact_id}: {db_exc}")

        # ── Record send analytics for timezone-aware optimization ─────────
        if sent_ok:
            try:
                record_send_analytics(contact_id, "intro", country)
            except Exception as analytics_exc:
                log.error(f"send_intro analytics failed for contact {contact_id}: {analytics_exc}")

    return sent_ok


def record_click(token: str, selection: str) -> dict:
    """
    Record a one-click lane or carrier selection from the email button.

    selection examples: 'usa-canada', 'europe', 'carrier-maersk', 'all'

    Returns dict with contact info for the thank-you page.
    """
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT id, contact_id, lane_clicks, carrier_clicks, country FROM intro_outreach WHERE click_token = ?",
            (token,)
        ).fetchone()

        if not row:
            conn.close()
            return {"ok": False, "message": "Link not recognised."}

        outreach_id   = row[0]
        contact_id    = row[1]
        lane_clicks   = json.loads(row[2] or "[]")
        carrier_clicks = json.loads(row[3] or "[]")
        country       = row[4]

        is_carrier = selection.startswith("carrier-")

        if is_carrier:
            carrier_name = selection[len("carrier-"):].replace("-", " ").title()
            if carrier_name not in carrier_clicks:
                carrier_clicks.append(carrier_name)
            conn.execute(
                "UPDATE intro_outreach SET carrier_clicks=?, reply_received=1 WHERE id=?",
                (json.dumps(carrier_clicks), outreach_id)
            )
        elif selection == "all":
            # Mark every lane
            all_lanes = list(_LANE_SLUG.keys())
            all_lanes = [l for l in all_lanes if l != "All destinations"]
            lane_clicks = all_lanes
            conn.execute(
                "UPDATE intro_outreach SET lane_clicks=?, lanes_confirmed=?, reply_received=1 WHERE id=?",
                (json.dumps(lane_clicks), ", ".join(lane_clicks), outreach_id)
            )
        else:
            # Reverse slug to label
            slug_to_label = {v: k for k, v in _LANE_SLUG.items()}
            label = slug_to_label.get(selection, selection.replace("-", " ").title())
            if label not in lane_clicks:
                lane_clicks.append(label)
            conn.execute(
                "UPDATE intro_outreach SET lane_clicks=?, lanes_confirmed=?, reply_received=1 WHERE id=?",
                (json.dumps(lane_clicks), ", ".join(lane_clicks), outreach_id)
            )

        # Also update contact_profiles if we have a contact_id
        if contact_id:
            try:
                import contact_engine as _ce
                if is_carrier:
                    _ce.update_profile(contact_id, preferred_carriers=json.dumps(carrier_clicks))
                else:
                    _ce.update_profile(contact_id, confirmed_lanes=json.dumps(lane_clicks))
            except Exception:
                pass

        conn.commit()
        conn.close()
        return {"ok": True, "selection": selection, "country": country}

    except Exception as exc:
        log.error(f"record_click error token={token} sel={selection}: {exc}")
        return {"ok": False, "message": str(exc)}


def send_intro_batch(contacts: list, delay_seconds: int = 30) -> dict:
    results = {"sent": 0, "failed": 0, "total": len(contacts)}
    for i, contact in enumerate(contacts):
        ok = send_intro(contact)
        if ok:
            results["sent"] += 1
        else:
            results["failed"] += 1
        if i < len(contacts) - 1 and delay_seconds > 0:
            time.sleep(delay_seconds)
    log.info(f"[intro_batch] Done. Sent: {results['sent']}, Failed: {results['failed']}")
    return results


def get_intro_stats() -> dict:
    try:
        conn = get_db()
        total_sent = conn.execute(
            "SELECT COUNT(*) FROM intro_outreach WHERE status != 'failed'"
        ).fetchone()[0]
        replied = conn.execute(
            "SELECT COUNT(*) FROM intro_outreach WHERE reply_received = 1"
        ).fetchone()[0]
        bounced = conn.execute(
            "SELECT COUNT(*) FROM intro_outreach WHERE status = 'bounced'"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM intro_outreach WHERE status = 'sent' AND reply_received = 0"
        ).fetchone()[0]
        conn.close()
        return {"total_sent": total_sent, "replied": replied, "bounced": bounced, "pending": pending}
    except Exception as exc:
        log.error(f"get_intro_stats error: {exc}")
        return {"total_sent": 0, "replied": 0, "bounced": 0, "pending": 0}


def test_intro_send(test_emails: list, contact_name: str = "Mehmet Yilmaz"):
    """Send intro test emails using a fake Turkey/Istanbul contact."""
    fake_base = {
        "id":           None,
        "contact_name": contact_name,
        "company_name": "Test Logistics Co",
        "country":      "Turkey",
        "city":         "Istanbul",
    }
    results = []
    for addr in test_emails:
        contact = dict(fake_base)
        contact["email"] = addr
        ok = send_intro(contact, test_mode=True)
        results.append({"email": addr, "sent": ok})
        if len(test_emails) > 1:
            time.sleep(5)
    return results
