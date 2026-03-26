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

# ── Local-language subject lines (20 high-priority countries) ─────────────
# Psychology rules: Win Friends (use name), Think & Grow Rich (specificity),
# Never Split (transparency). NO scarcity, NO fake social proof, NO pressure.
# Placeholders: {greeting_name}, {sender_first}, {_co}, {_loc}
_COUNTRY_SUBJECTS = {
    # ── Turkish ────────────────────────────────────────────────────────────
    "turkey": [
        "{greeting_name}, {_co} hakkında bir sorumuz var",
        "{sender_first} for {greeting_name} | {_loc} navlun",
        "{_co} — {_loc} kargo ortaklığı",
        "{greeting_name}, {_loc} hatlarınız hakkında",
        "{sender_first}, {_co} ile çalışmak istiyoruz",
    ],
    # ── German ─────────────────────────────────────────────────────────────
    "germany": [
        "{greeting_name}, Anfrage zu {_co} — Seefracht ab {_loc}",
        "{sender_first} for {greeting_name} | Fracht ab {_loc}",
        "{_co} — Partnerschaft für {_loc} Seefracht",
        "{greeting_name}, wir suchen einen Partner in {_loc}",
        "{sender_first} von Flash Cargo für {greeting_name} bei {_co}",
    ],
    # ── French ─────────────────────────────────────────────────────────────
    "france": [
        "{greeting_name}, question au sujet de {_co}",
        "{sender_first} for {greeting_name} | fret depuis {_loc}",
        "{_co} — partenariat fret depuis {_loc}",
        "{greeting_name}, vos lignes au départ de {_loc}",
        "{sender_first} de Flash Cargo pour {greeting_name} chez {_co}",
    ],
    # ── Brazilian Portuguese ───────────────────────────────────────────────
    "brazil": [
        "{greeting_name}, pergunta sobre a {_co}",
        "{sender_first} for {greeting_name} | frete de {_loc}",
        "{_co} — parceria de carga desde {_loc}",
        "{greeting_name}, sobre suas rotas de {_loc}",
        "{sender_first} da Flash Cargo para {greeting_name} na {_co}",
    ],
    # ── Japanese ───────────────────────────────────────────────────────────
    "japan": [
        "{greeting_name}様、{_co}について",
        "{sender_first} for {greeting_name}様 | {_loc}発の貨物",
        "{_co} — {_loc}からの海上輸送パートナーシップ",
        "{greeting_name}様、{_loc}の輸送ルートについて",
    ],
    # ── Chinese (Simplified) ──────────────────────────────────────────────
    "china": [
        "{greeting_name}，关于{_co}的合作咨询",
        "{sender_first} for {greeting_name} | {_loc}货运",
        "{_co} — {_loc}货运合作",
        "{greeting_name}，{_loc}航线咨询",
        "{sender_first}（Flash Cargo）致{greeting_name}（{_co}）",
    ],
    # ── Korean ─────────────────────────────────────────────────────────────
    "south korea": [
        "{greeting_name}님, {_co} 관련 문의드립니다",
        "{sender_first} for {greeting_name}님 | {_loc} 화물",
        "{_co} — {_loc} 해상 운송 파트너십",
        "{greeting_name}님, {_loc} 노선에 대해",
    ],
    # ── Hindi ──────────────────────────────────────────────────────────────
    "india": [
        "{greeting_name}, {_co} के बारे में एक प्रश्न",
        "{sender_first} for {greeting_name} | {_loc} माल ढुलाई",
        "{_co} — {_loc} कार्गो साझेदारी",
        "{greeting_name}, {_loc} से आपके मार्गों के बारे में",
    ],
    # ── Spanish (Spain) ───────────────────────────────────────────────────
    "spain": [
        "{greeting_name}, consulta sobre {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — colaboración de carga desde {_loc}",
        "{greeting_name}, sobre sus rutas desde {_loc}",
        "{sender_first} de Flash Cargo para {greeting_name} en {_co}",
    ],
    # ── Italian ────────────────────────────────────────────────────────────
    "italy": [
        "{greeting_name}, domanda su {_co}",
        "{sender_first} for {greeting_name} | trasporto da {_loc}",
        "{_co} — collaborazione cargo da {_loc}",
        "{greeting_name}, sulle vostre rotte da {_loc}",
        "{sender_first} di Flash Cargo per {greeting_name} presso {_co}",
    ],
    # ── Portuguese (Portugal) ─────────────────────────────────────────────
    "portugal": [
        "{greeting_name}, questão sobre a {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — parceria de carga desde {_loc}",
        "{greeting_name}, sobre as vossas rotas de {_loc}",
        "{sender_first} da Flash Cargo para {greeting_name} na {_co}",
    ],
    # ── Russian ────────────────────────────────────────────────────────────
    "russia": [
        "{greeting_name}, вопрос о {_co}",
        "{sender_first} for {greeting_name} | грузоперевозки из {_loc}",
        "{_co} — партнёрство по грузам из {_loc}",
        "{greeting_name}, о ваших маршрутах из {_loc}",
    ],
    # ── Mexican Spanish ───────────────────────────────────────────────────
    "mexico": [
        "{greeting_name}, consulta sobre {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — alianza de carga desde {_loc}",
        "{greeting_name}, sobre sus rutas desde {_loc}",
        "{sender_first} de Flash Cargo para {greeting_name} en {_co}",
    ],
    # ── Colombian Spanish ─────────────────────────────────────────────────
    "colombia": [
        "{greeting_name}, consulta sobre {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — alianza de carga desde {_loc}",
        "{greeting_name}, sobre sus rutas desde {_loc}",
    ],
    # ── Argentine Spanish ─────────────────────────────────────────────────
    "argentina": [
        "{greeting_name}, consulta sobre {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — alianza de carga desde {_loc}",
        "{greeting_name}, sobre sus rutas desde {_loc}",
    ],
    # ── Chilean Spanish ───────────────────────────────────────────────────
    "chile": [
        "{greeting_name}, consulta sobre {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — alianza de carga desde {_loc}",
        "{greeting_name}, sobre sus rutas desde {_loc}",
    ],
    # ── Peruvian Spanish ──────────────────────────────────────────────────
    "peru": [
        "{greeting_name}, consulta sobre {_co}",
        "{sender_first} for {greeting_name} | carga desde {_loc}",
        "{_co} — alianza de carga desde {_loc}",
        "{greeting_name}, sobre sus rutas desde {_loc}",
    ],
    # ── Arabic (Saudi Arabia) — RTL-safe subject ──────────────────────────
    "saudi arabia": [
        "{greeting_name}، استفسار عن {_co}",
        "{sender_first} for {greeting_name} | شحن من {_loc}",
        "{_co} — شراكة شحن من {_loc}",
        "{greeting_name}، بخصوص خطوطكم من {_loc}",
    ],
    # ── Arabic (UAE) ──────────────────────────────────────────────────────
    "uae": [
        "{greeting_name}، استفسار عن {_co}",
        "{sender_first} for {greeting_name} | شحن من {_loc}",
        "{_co} — شراكة شحن من {_loc}",
        "{greeting_name}، بخصوص خطوطكم من {_loc}",
    ],
    # ── Indonesian ─────────────────────────────────────────────────────────
    "indonesia": [
        "{greeting_name}, pertanyaan tentang {_co}",
        "{sender_first} for {greeting_name} | kargo dari {_loc}",
        "{_co} — kemitraan kargo dari {_loc}",
        "{greeting_name}, tentang rute Anda dari {_loc}",
        "{sender_first} dari Flash Cargo untuk {greeting_name} di {_co}",
    ],
}

# ── Local-language greetings (first line of email body) ──────────────────
# Culturally appropriate: formal where needed, correct honorifics for CJK.
_LOCAL_GREETINGS = {
    "turkey":       "Merhaba {name},",
    "germany":      "Hallo {name},",
    "france":       "Bonjour {name},",
    "brazil":       "Olá {name},",
    "japan":        "{name}様、",
    "china":        "{name}，您好，",
    "south korea":  "{name}님, 안녕하세요,",
    "india":        "नमस्ते {name},",
    "spain":        "Hola {name},",
    "italy":        "Buongiorno {name},",
    "portugal":     "Olá {name},",
    "russia":       "Здравствуйте, {name},",
    "mexico":       "Hola {name},",
    "colombia":     "Hola {name},",
    "argentina":    "Hola {name},",
    "chile":        "Hola {name},",
    "peru":         "Hola {name},",
    "saudi arabia": "{name}، مرحبًا",
    "uae":          "{name}، مرحبًا",
    "indonesia":    "Halo {name},",
}


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

    # Strip honorifics (Mr., Ms., Mrs., Dr., etc.) to get actual first name
    _honorifics = {"mr.", "ms.", "mrs.", "dr.", "mr", "ms", "mrs", "dr", "prof.", "prof"}
    name_parts = contact_name.split() if contact_name else []
    while name_parts and name_parts[0].lower().rstrip(".") in {h.rstrip(".") for h in _honorifics}:
        name_parts.pop(0)
    first_name    = name_parts[0] if name_parts else ""
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
    # Every subject must feel like it was written for THIS person at THIS company.
    # No generic "freight partnership" language. Use company name + city to stand out.
    _loc = city or country or "your region"
    _co = company_name or "your company"

    # Try local-language subjects first, fall back to English
    _country_lower = country.lower() if country else ""
    _local_subjects = _COUNTRY_SUBJECTS.get(_country_lower)
    if _local_subjects:
        _formatted_local = []
        for tpl in _local_subjects:
            try:
                _formatted_local.append(tpl.format(
                    greeting_name=greeting_name,
                    sender_first=sender_first,
                    _co=_co,
                    _loc=_loc,
                ))
            except (KeyError, IndexError):
                pass
        if _formatted_local:
            subject = _rng.choice(_formatted_local)
            # Skip the English pool
            _use_english_subject = False
        else:
            _use_english_subject = True
    else:
        _use_english_subject = True

    _SUBJECTS = [
        f"{greeting_name}, {_loc} freight",
        f"{_co}, quick question",
        f"{greeting_name}, {_loc} lanes",
        f"Freight from {_loc}",
        f"{greeting_name} at {_co}",
        f"{_loc} cargo, {_co}",
        f"{greeting_name}, {_loc} agent?",
        f"Re: {_co}",
    ]
    if _use_english_subject:
        subject = _rng.choice(_SUBJECTS)

    # ── Opener variations (short, direct, like a busy freight pro) ───
    _city = city or country or "your area"
    _co = company_name or "your company"
    _OPENERS = [
        f"{sender_first} here, Flash Cargo. We move containers through {_city} regularly and saw {_co} while sourcing a local partner.",
        f"{sender_first} from Flash Cargo. We handle ocean freight out of {_city} every week. Found {_co} while looking for agents.",
        f"{sender_first}, Flash Cargo Global. We’ve got cargo moving through {_city} and need a solid local agent.",
        f"Quick intro. I’m {sender_first} at Flash Cargo. We route ocean freight from {_city} to the US weekly.",
        f"{sender_first} with Flash Cargo. We ship out of {_city} regularly and your company came up in our agent search.",
        f"Flash Cargo here, {sender_first}. We move FCL and LCL out of {_city} and need a partner on the ground.",
        f"{sender_first} from Flash Cargo. We’ve been routing cargo through {_city} and want the right agent before our next shipment.",
        f"{sender_first}, Flash Cargo Global. Looking for an agent in {_city}. Your company stood out.",
        f"{sender_first} at Flash Cargo. We handle freight from {_city} to North America and need a local partner.",
        f"Hey, {sender_first} from Flash Cargo. We move containers out of {_city} every week and came across {_co}.",
    ]

    _CONTEXTS = [
        f"Quick question. What lanes do you cover out of {_city}?",
        f"We’ve got active cargo from {_city} and want to make sure we’re working with the right agent.",
        f"Need someone who knows {_city} inside out. You seem like a fit.",
        f"We route freight from {_city} to the US regularly. Looking for a partner, not a vendor.",
        f"Cargo from {_city} is a growing lane for us. Want the right agent on file.",
        f"We’ve got shipments heading from {_city} and need a reliable local team.",
    ]

    _CTAS = [
        "Two quick picks and you’re done:",
        "Takes 30 seconds. Just pick your lanes and carriers:",
        "One click, pick what applies:",
        "Just select your routes below:",
        "Here’s the ask, two clicks:",
    ]

    _BTN_LABELS = [
        "Pick My Lanes",
        "Select Routes",
        "Choose Coverage",
        "I’m In",
        "Yes, Show Me",
    ]

    _FOOTERS = [
        "Once you pick, we’ll send rate requests for those lanes only. No spam.",
        "We’ll match you with cargo on your selected routes. Nothing else.",
        "You’ll get rate requests within days. Real cargo, your lanes only.",
        "Pick your routes and we start sending relevant inquiries your way.",
        "After you respond, cargo inquiries flow your way. Only for what you selected.",
    ]

    _INSTRUCTIONS = [
        "Hit the button, pick what applies, confirm. Under a minute.",
        "Click below, select your lanes and carriers, done. No login.",
        "Tap the button, pick and confirm. Takes 30 seconds.",
    ]

    # ── Pick variations ───
    opener_html  = _rng.choice(_OPENERS)
    context_html = _rng.choice(_CONTEXTS)
    cta_html     = _rng.choice(_CTAS)
    btn_label    = _rng.choice(_BTN_LABELS)
    footer_html  = _rng.choice(_FOOTERS)
    instr_html   = _rng.choice(_INSTRUCTIONS)

    # ── Numbered lane rows ───
    carrier_letters = "ABCDEFGHIJKL"
    lane_rows_html = "".join(
        f'<tr><td style="font-family:Arial,sans-serif;font-size:13px;color:#1a73e8;font-weight:700;'
        f'padding:3px 10px 3px 0;white-space:nowrap;">{i+1}</td>'
        f'<td style="font-family:Arial,sans-serif;font-size:13px;color:#222;padding:3px 0;">{lbl}</td></tr>'
        for i, lbl in enumerate(lane_labels)
    )

    carrier_rows_html = ""
    for i, c in enumerate(_CARRIER_OPTIONS):
        letter = carrier_letters[i]
        carrier_rows_html += (
            f'<tr><td style="font-family:Arial,sans-serif;font-size:13px;color:#1a73e8;'
            f'font-weight:700;padding:3px 10px 3px 0;white-space:nowrap;">{letter}</td>'
            f'<td style="font-family:Arial,sans-serif;font-size:13px;color:#222;'
            f'padding:3px 0;">{c}</td></tr>'
        )

    lanes_param = urllib.parse.quote(",".join(lane_labels), safe="")
    selection_url = (
        f"{TRACKING_BASE}/api/respond"
        f"?token={token}"
        f"&country={urllib.parse.quote(country, safe='')}"
        f"&lanes={lanes_param}"
    )

    _greeting_tpl = _LOCAL_GREETINGS.get(_country_lower)
    if _greeting_tpl:
        _greeting_line = _greeting_tpl.format(name=greeting_name)
    else:
        _GREETINGS = [
            f"{greeting_name} —",
            f"Hey {greeting_name},",
            f"Hi {greeting_name},",
            f"{greeting_name},",
        ]
        _greeting_line = _rng.choice(_GREETINGS)

    _structure = _rng.randint(0, 3)

    _SIGNOFFS = [
        f"Cheers,<br>{sender_first}",
        f"Thanks,<br>{sender_first}",
        f"Talk soon,<br>{sender_first}",
        f"Best,<br>{sender_first}",
        f"{sender_first}",
    ]
    signoff_html = _rng.choice(_SIGNOFFS)

    _p = 'font-family:Arial,sans-serif;font-size:15px;color:#222;margin:0 0 14px;'
    _ps = 'font-family:Arial,sans-serif;font-size:13px;color:#555;margin:0 0 10px;'

    selection_box = f"""
<div style="background:#f7f9ff;border-left:3px solid #1a73e8;padding:14px 18px;margin:0 0 18px;border-radius:0 6px 6px 0;">
  <p style="font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:#111;margin:0 0 8px;">
    1. Which destinations can you quote FROM {from_label}?
  </p>
  <table style="border-collapse:collapse;margin:0 0 4px 4px;">
    {lane_rows_html}
  </table>
  <p style="font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:#111;margin:16px 0 8px;">
    2. Which shipping lines do you work with?
  </p>
  <table style="border-collapse:collapse;margin:0 0 4px 4px;">
    {carrier_rows_html}
  </table>
</div>"""

    cta_block = f"""
<p style="{_ps}">{instr_html}</p>
<div style="margin:0 0 16px;">
{_mailto_btn(btn_label, selection_url, color="#1a1a2e")}
</div>"""

    footer_block = f"""
<p style="font-family:Arial,sans-serif;font-size:12px;color:#999;margin:0 0 6px;">{footer_html}</p>
<p style="font-family:Arial,sans-serif;font-size:14px;color:#222;margin:16px 0 4px;">{signoff_html}</p>
{signature_for(sender_name_full)}"""

    if _structure == 0:
        body_html = f"""
<p style="{_p}">{_greeting_line}</p>
<p style="{_p}">{opener_html}</p>
<p style="{_p}">{cta_html}</p>
{selection_box}
{cta_block}
{footer_block}"""

    elif _structure == 1:
        body_html = f"""
<p style="{_p}">{_greeting_line}</p>
<p style="{_p}">{context_html}</p>
<p style="{_p}">{opener_html}</p>
<p style="{_p}">{cta_html}</p>
{selection_box}
{cta_block}
{footer_block}"""

    elif _structure == 2:
        body_html = f"""
<p style="{_p}">{opener_html}</p>
<p style="{_p}">{context_html}</p>
<p style="{_p}">{cta_html}</p>
{selection_box}
{cta_block}
{footer_block}"""

    else:
        body_html = f"""
<p style="{_p}">{_greeting_line}</p>
<p style="{_p}">{opener_html}</p>
<p style="{_p}">{cta_html}</p>
{selection_box}
{cta_block}
<p style="{_ps}">{context_html}</p>
{footer_block}"""

    return subject, body_html


def send_intro(contact: dict, test_mode: bool = False) -> bool:
    country     = (contact.get("country") or "").strip()
    contact_id  = contact.get("id")
    contact_name = (contact.get("contact_name") or "").strip()
    _hon = {"mr", "ms", "mrs", "dr", "prof"}
    _parts = contact_name.split() if contact_name else []
    while _parts and _parts[0].lower().rstrip(".") in _hon:
        _parts.pop(0)
    greeting_name = _parts[0] if _parts else None
    sender_name = _display_name_for_country(country, contact_id, contact_first_name=greeting_name)
    email       = (contact.get("email") or "").strip()

    if not email:
        log.warning(f"send_intro: no email for contact id={contact_id}")
        return False

    # ── Bounce check: skip if this email has bounced before ───────────────
    try:
        from bounce_monitor import is_bounced
        if is_bounced(email):
            log.info(f"send_intro: skipping bounced email {email} (contact id={contact_id})")
            return False
    except ImportError:
        pass

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
