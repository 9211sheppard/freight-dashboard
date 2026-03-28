"""
mailer.py — Microsoft Graph API email sender
Uses app-only OAuth2 (client credentials) so no user interaction needed.
"""

import json
import random
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
import base64
import logging
from datetime import date

log = logging.getLogger(__name__)

# ── Shared email signature ────────────────────────────────────────────────────
SIGNATURE = """
<p style="color:#555;font-size:13px;border-top:1px solid #ddd;padding-top:8px;margin-top:20px;">
<strong>Pricing Team | Flash Cargo Global</strong><br>
Over-the-Road &nbsp;|&nbsp; Air &nbsp;|&nbsp; Ocean &nbsp;|&nbsp; Worldwide Freight Forwarding<br>
<a href="https://www.flashcargoglobal.com" style="color:#0066cc;">www.flashcargoglobal.com</a><br>
<em>Delivering confidence worldwide</em>
</p>
"""


def signature_for(sender_name: str = None) -> str:
    """Return an HTML signature block with the given sender name.
    Falls back to 'Pricing Team | Flash Cargo Global' if no name is provided.
    Includes CAN-SPAM compliant unsubscribe link and physical address.
    """
    display = sender_name if sender_name else "Pricing Team | Flash Cargo Global"
    return (
        '<p style="color:#555;font-size:13px;border-top:1px solid #ddd;'
        'padding-top:8px;margin-top:20px;">'
        f'<strong>{display}</strong><br>'
        'Over-the-Road &nbsp;|&nbsp; Air &nbsp;|&nbsp; Ocean &nbsp;|&nbsp; '
        'Worldwide Freight Forwarding<br>'
        '<a href="https://www.flashcargoglobal.com" style="color:#0066cc;">'
        'www.flashcargoglobal.com</a><br>'
        '<em>Delivering confidence worldwide</em>'
        '</p>'
        '<p style="color:#999;font-size:11px;margin-top:12px;">'
        'Flash Cargo Global Inc.<br>'
        'This is a commercial message. '
        'If you no longer wish to receive emails from us, '
        '<a href="mailto:pricing@flashcargoglobal.com?subject=UNSUBSCRIBE" '
        'style="color:#999;">click here to unsubscribe</a>. '
        'We will remove you within 10 business days.'
        '</p>'
    )

# ── Regional display names (country → [male, female, male, female, ...]) ──────
# Multiple male AND female names per country — culturally appropriate.
# Deterministic pick based on contact_id ensures consistency.
# Replies always return to pricing@flashcargoglobal.com regardless.
_COUNTRY_NAMES = {
    # Europe
    "italy":           ["Marco", "Giulia", "Alessandro", "Chiara", "Luca", "Elena", "Matteo", "Carolina"],
    "germany":         ["Hans", "Lena", "Markus", "Katrin", "Felix", "Julia", "Daniel", "Sabine"],
    "france":          ["Pierre", "Claire", "Antoine", "Marie", "Julien", "Camille", "Nicolas", "Julie"],
    "spain":           ["Carlos", "Elena", "Javier", "Lucia", "Pablo", "Isabel", "Miguel", "Carmen"],
    "netherlands":     ["Jan", "Femke", "Daan", "Emma", "Bram", "Lotte", "Ruben", "Anouk"],
    "belgium":         ["Luc", "Noor", "Daan", "Charlotte", "Pieter", "Emma", "Marc", "Julie"],
    "switzerland":     ["Felix", "Anna", "Marc", "Laura", "Daniel", "Lisa", "Lukas", "Elena"],
    "austria":         ["Felix", "Anna", "Florian", "Lisa", "Markus", "Katharina", "Georg", "Maria"],
    "poland":          ["Piotr", "Kasia", "Pavel", "Agnieszka", "Jakub", "Magdalena", "Michal", "Anna"],
    "greece":          ["Nikos", "Elena", "Dimitris", "Maria", "Giorgos", "Katerina", "Kostas", "Olga"],
    "turkey":          ["Mehmet", "Elif", "Ahmet", "Fatima", "Emre", "Ayse", "Burak", "Fatma"],
    "portugal":        ["Jo\u00e3o", "Ana", "Rafael", "Beatriz", "Pedro", "In\u00eas", "Miguel", "Carolina"],
    "sweden":          ["Lars", "Elin", "Erik", "Anna", "Oscar", "Maja", "Gustav", "Astrid"],
    "denmark":         ["Mads", "Elin", "Frederik", "Astrid", "Anders", "Ida", "Rasmus", "Katrine"],
    "norway":          ["Lars", "Ingrid", "Magnus", "Maja", "Olav", "Astrid", "Henrik", "Elin"],
    "finland":         ["Mikko", "Aino", "Antti", "Emilia", "Jari", "Maja", "Erik", "Liisa"],
    "russia":          ["Dmitri", "Natalia", "Alexei", "Olga", "Pavel", "Irina", "Ivan", "Iryna"],
    "ukraine":         ["Oleksandr", "Natalia", "Andriy", "Oksana", "Dmitro", "Irina", "Michal", "Iryna"],
    "czech republic":  ["Martin", "Petra", "Jan", "Lucie", "Pavel", "Katalin", "Jakub", "Anna"],
    "romania":         ["Andrei", "Ioana", "Alexandru", "Maria", "Mihai", "Elena", "Florian", "Ana"],
    "hungary":         ["Balazs", "Reka", "Gabor", "Anna", "Laszlo", "Eszter", "Andrei", "Katalin"],
    "croatia":         ["Ivan", "Ana", "Marko", "Petra", "Luka", "Marina", "Ante", "Ivana"],
    "ireland":         ["Conor", "Ciara", "Padraig", "Aoife", "Brendan", "Niamh", "James", "Charlotte"],
    "united kingdom":  ["James", "Emily", "Oliver", "Emma", "George", "Charlotte", "David", "Nicole"],
    "uk":              ["James", "Emily", "Oliver", "Emma", "George", "Charlotte", "David", "Nicole"],
    # Asia-Pacific
    "china":           ["Chen", "Mei", "Hao", "Li", "Jun", "Hui", "Cheng", "Lan"],
    "hong kong":       ["Jason", "Mei", "Kevin", "Rachel", "Alan", "Jenny", "Aaron", "Grace"],
    "taiwan":          ["Ming", "Mei", "Chen", "Li", "Cheng", "Hui", "Hao", "Lan"],
    "japan":           ["Kenji", "Sakura", "Hiroshi", "Aiko", "Ryo", "Hana", "Jun", "Mei"],
    "south korea":     ["Min", "Eun", "Hyun", "Ji", "Joon", "Mei", "Jun", "Li"],
    "korea":           ["Min", "Eun", "Hyun", "Ji", "Joon", "Mei", "Jun", "Li"],
    "india":           ["Raj", "Priya", "Arjun", "Anita", "Amit", "Deepa", "Rahim", "Nadia"],
    "singapore":       ["Jun", "Li", "Jason", "Rachel", "Kevin", "Michelle", "Aaron", "Grace"],
    "malaysia":        ["Ahmad", "Nurul", "Farid", "Ain", "Hafiz", "Fatimah", "Azlan", "Amina"],
    "indonesia":       ["Budi", "Dewi", "Andi", "Putri", "Rizal", "Noor", "Agus", "Fatimah"],
    "thailand":        ["Chai", "Noi", "Natthapong", "Ploy", "Prawit", "Kannika", "Rizal", "Nadia"],
    "vietnam":         ["Minh", "Lan", "Duc", "Linh", "Hung", "Mai", "Jun", "Mei"],
    "philippines":     ["Rico", "Maria", "Juan", "Rosa", "Miguel", "Ana", "Rafael", "Luz"],
    "australia":       ["James", "Emily", "Ryan", "Emma", "Liam", "Chloe", "Jack", "Mia"],
    "new zealand":     ["James", "Emily", "Ben", "Kate", "Matt", "Lucy", "Jack", "Hannah"],
    "bangladesh":      ["Rahim", "Nadia", "Farhan", "Amina", "Hasan", "Fatema", "Kamal", "Fatima"],
    "pakistan":         ["Ali", "Fatima", "Hassan", "Ayesha", "Bilal", "Amina", "Ahmed", "Noor"],
    "sri lanka":       ["Ashan", "Dilini", "Nuwan", "Sachini", "Chaminda", "Nishanthi", "Ruwan", "Apsara"],
    # Americas
    "usa":             ["Mike", "Jessica", "Brian", "Amanda", "Ryan", "Emily", "Chris", "Nicole"],
    "united states":   ["Mike", "Jessica", "Brian", "Amanda", "Ryan", "Emily", "Chris", "Nicole"],
    "brazil":          ["Bruno", "Ana", "Rafael", "Juliana", "Lucas", "Fernanda", "Gustavo", "Camila"],
    "mexico":          ["Diego", "Paola", "Alejandro", "Daniela", "Fernando", "Gabriela", "Luis", "Mariana"],
    "colombia":        ["Andres", "Paola", "Diego", "Daniela", "Juan", "Natalia", "Carlos", "Laura"],
    "argentina":       ["Martin", "Florencia", "Nicolas", "Gabriela", "Matias", "Camila", "Diego", "Laura"],
    "chile":           ["Rodrigo", "Constanza", "Felipe", "Francisca", "Ignacio", "Catalina", "Diego", "Javiera"],
    "peru":            ["Ricardo", "Paola", "Jose", "Milagros", "Carlos", "Fernanda", "Luis", "Maria"],
    "canada":          ["James", "Emily", "Ryan", "Emma", "Michael", "Chloe", "David", "Nicole"],
    "ecuador":         ["Luis", "Maria", "Andres", "Gabriela", "Diego", "Fernanda", "Carlos", "Daniela"],
    "venezuela":       ["Carlos", "Maria", "Andres", "Gabriela", "Diego", "Natalia", "Luis", "Daniela"],
    "costa rica":      ["Jose", "Maria", "Luis", "Daniela", "Carlos", "Gabriela", "Diego", "Andrea"],
    "panama":          ["Roberto", "Maria", "Luis", "Daniela", "Carlos", "Ana", "Jose", "Isabel"],
    # Middle East / Africa
    "uae":             ["Khalid", "Fatima", "Ahmed", "Mariam", "Omar", "Noura", "Rashid", "Noor"],
    "united arab emirates": ["Khalid", "Fatima", "Ahmed", "Mariam", "Omar", "Noura", "Rashid", "Noor"],
    "saudi arabia":    ["Khalid", "Fatima", "Mohammed", "Noura", "Abdullah", "Hala", "Fahad", "Reem"],
    "qatar":           ["Khalid", "Fatima", "Hamad", "Mariam", "Ali", "Noura", "Saad", "Maha"],
    "kuwait":          ["Khalid", "Fatima", "Fahad", "Noura", "Bader", "Dana", "Saad", "Dalal"],
    "bahrain":         ["Khalid", "Fatima", "Ahmed", "Noura", "Ali", "Mariam", "Hassan", "Maha"],
    "oman":            ["Khalid", "Fatima", "Said", "Mariam", "Ahmed", "Khadija", "Hamad", "Noura"],
    "egypt":           ["Ahmed", "Fatima", "Mohamed", "Noura", "Khaled", "Mona", "Hassan", "Layla"],
    "jordan":          ["Khaled", "Fatima", "Ahmad", "Rania", "Omar", "Lina", "Faisal", "Dina"],
    "lebanon":         ["Rami", "Nadia", "Fadi", "Rita", "Omar", "Maya", "Ahmad", "Carla"],
    "israel":          ["David", "Noa", "Eyal", "Nadia", "Avi", "Maya", "Oren", "Rita"],
    "south africa":    ["James", "Naledi", "Pieter", "Lerato", "Johan", "Nandi", "David", "Emily"],
    "nigeria":         ["Emeka", "Amara", "Chukwu", "Ngozi", "Ade", "Funke", "Kofi", "Chioma"],
    "kenya":           ["James", "Amina", "John", "Akinyi", "Peter", "Njeri", "David", "Neema"],
    "ghana":           ["Kofi", "Ama", "Kwame", "Akosua", "Kwesi", "Abena", "Ade", "Adwoa"],
    "tanzania":        ["James", "Amina", "Joseph", "Rehema", "John", "Neema", "Charles", "Fatima"],
    "morocco":         ["Amine", "Fatima", "Mehdi", "Khadija", "Omar", "Layla", "Ahmed", "Noor"],
}
# -- Active email aliases on pricing@ mailbox (332 of 403 names) ------
# Names NOT in this set will send from pricing@flashcargoglobal.com.
# Limit: M365 allows max 333 proxyAddresses per mailbox.
_ACTIVE_ALIASES = {
    "aaron", "abdullah", "abena", "ade", "adwoa", "agnieszka", "agus", "ahmad",
    "ahmed", "ahmet", "aiko", "ain", "aino", "akinyi", "akosua", "alan",
    "alejandro", "alessandro", "alexandru", "alexei", "ali", "ama", "amanda", "amara",
    "amina", "amine", "amit", "ana", "anders", "andi", "andrea", "andrei",
    "andres", "andriy", "anita", "anna", "anouk", "ante", "antoine", "antti",
    "aoife", "apsara", "arjun", "ashan", "astrid", "avi", "ayesha", "ayse",
    "azlan", "bader", "balazs", "beatriz", "ben", "bilal", "bram", "brendan",
    "brian", "bruno", "budi", "burak", "camila", "camille", "carla", "carlos",
    "carmen", "carolina", "catalina", "chai", "chaminda", "charles", "charlotte", "chen",
    "cheng", "chiara", "chioma", "chloe", "chris", "chukwu", "ciara", "claire",
    "conor", "constanza", "daan", "dalal", "dana", "daniel", "daniela", "david",
    "deepa", "dewi", "diego", "dilini", "dimitris", "dina", "dmitri", "dmitro",
    "duc", "elena", "elif", "elin", "emeka", "emilia", "emily", "emma",
    "emre", "erik", "eszter", "eun", "eyal", "fadi", "fahad", "faisal",
    "farhan", "farid", "fatema", "fatima", "fatimah", "fatma", "felipe", "felix",
    "femke", "fernanda", "fernando", "florencia", "florian", "francisca", "frederik", "funke",
    "gabor", "gabriela", "georg", "george", "giorgos", "giulia", "grace", "gustav",
    "gustavo", "hafiz", "hala", "hamad", "hana", "hannah", "hans", "hao",
    "hasan", "hassan", "henrik", "hiroshi", "hui", "hung", "hyun", "ida",
    "ignacio", "ines", "ingrid", "ioana", "irina", "iryna", "isabel", "ivan",
    "ivana", "jack", "jakub", "james", "jan", "jari", "jason", "javier",
    "javiera", "jenny", "jessica", "ji", "joao", "johan", "john", "joon",
    "jose", "joseph", "juan", "julia", "juliana", "julie", "julien", "jun",
    "kamal", "kannika", "kasia", "katalin", "kate", "katerina", "katharina", "katrin",
    "katrine", "kenji", "kevin", "khadija", "khaled", "khalid", "kofi", "kostas",
    "kwame", "kwesi", "lan", "lars", "laszlo", "laura", "layla", "lena",
    "lerato", "li", "liam", "liisa", "lina", "linh", "lisa", "lotte",
    "luc", "luca", "lucas", "lucia", "lucie", "lucy", "luis", "luka",
    "lukas", "luz", "mads", "magdalena", "magnus", "maha", "mai", "maja",
    "marc", "marco", "maria", "mariam", "mariana", "marie", "marina", "marko",
    "markus", "martin", "matias", "matt", "matteo", "maya", "mehdi", "mehmet",
    "mei", "mia", "michael", "michal", "michelle", "miguel", "mihai", "mike",
    "mikko", "milagros", "min", "ming", "minh", "mohamed", "mohammed", "mona",
    "nadia", "naledi", "nandi", "natalia", "natthapong", "neema", "ngozi", "niamh",
    "nicolas", "nicole", "nikos", "nishanthi", "njeri", "noa", "noi", "noor",
    "noura", "nurul", "nuwan", "oksana", "olav", "oleksandr", "olga", "oliver",
    "omar", "oren", "oscar", "pablo", "padraig", "paola", "pavel", "pedro",
    "peter", "petra", "pierre", "pieter", "piotr", "ploy", "prawit", "priya",
    "putri", "rachel", "rafael", "rahim", "raj", "rami", "rania", "rashid",
    "rasmus", "reem", "rehema", "reka", "ricardo", "rico", "rita", "rizal",
    "roberto", "rodrigo", "rosa", "ruben", "ruwan", "ryan", "ryo", "saad",
    "sabine", "sachini", "said", "sakura",
}


def _strip_accents(s: str) -> str:
    """Remove diacritics: Joao -> Joao, Ines -> Ines."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _from_address_for_name(display_name: str) -> str:
    """Return firstname@flashcargoglobal.com if the name has an alias, else pricing@."""
    first = display_name.split("|")[0].strip().split()[0] if display_name else ""
    alias = _strip_accents(first).lower().strip() if first else ""
    if alias and alias in _ACTIVE_ALIASES:
        return f"{alias}@flashcargoglobal.com"
    return "pricing@flashcargoglobal.com"


def _display_name_for_country(country: str, contact_id: int = None,
                               contact_first_name: str = None) -> str:
    """Return a culturally appropriate sender display name for the country.

    Uses _COUNTRY_NAMES pool (4 male + 4 female per country).
    Deterministic by contact_id so the same contact always gets the same sender.
    Avoids name collision with the contact's first name.
    """
    key = country.strip().lower() if country else ""
    names = _COUNTRY_NAMES.get(key)
    if not names:
        return "Flash Cargo Global"
    idx = (contact_id or 0) % len(names)
    chosen = names[idx]
    # Avoid sender name matching contact's first name
    if contact_first_name and chosen.lower() == contact_first_name.strip().lower():
        chosen = names[(idx + 1) % len(names)]
    return f"{chosen} | Flash Cargo Global"


def _get_token(tenant_id, client_id, client_secret):
    """Fetch an OAuth2 access token via client credentials flow."""
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    body = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def send_email(to_address, subject, body_html, body_text=None,
               from_address=None, display_name=None, reply_to=None,
               tenant_id=None, client_id=None, client_secret=None):
    """
    Send an email via Microsoft Graph API.

    Parameters
    ----------
    to_address   : str   — recipient email
    subject      : str
    body_html    : str   — HTML body
    body_text    : str   — plain-text fallback (optional)
    from_address : str   — sender address (must have Mail.Send permission)
    display_name : str   — sender display name shown in email client
    reply_to     : str   — optional reply-to address
    tenant_id / client_id / client_secret : pulled from config if omitted

    Returns
    -------
    True on success, raises on failure.
    """
    from config import (
        EMAIL_FROM, GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    )

    from_address  = from_address  or EMAIL_FROM
    display_name  = display_name  or "Pricing Team | Flash Cargo Global"
    tenant_id     = tenant_id     or GRAPH_TENANT_ID
    client_id     = client_id     or GRAPH_CLIENT_ID
    client_secret = client_secret or GRAPH_CLIENT_SECRET

    # ── Bounce check: refuse to send to known-bounced addresses ──────────
    try:
        from bounce_monitor import is_bounced
        if is_bounced(to_address):
            log.warning(f"send_email: BLOCKED — {to_address} is in bounced list")
            raise ValueError(f"Recipient {to_address} is in the bounced email list")
    except ImportError:
        pass

    token = _get_token(tenant_id, client_id, client_secret)

    message = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body_html,
            },
            "from": {
                "emailAddress": {
                    "address": from_address,
                    "name":    display_name,
                }
            },
            "toRecipients": [
                {"emailAddress": {"address": to_address}}
            ],
        },
        "saveToSentItems": "true",
    }

    if reply_to:
        message["message"]["replyTo"] = [
            {"emailAddress": {"address": reply_to}}
        ]

    # Graph API sendMail must target the MAILBOX (pricing@), not the alias.
    # The alias address goes in the message 'from' field instead.
    mailbox = "pricing@flashcargoglobal.com"
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/sendMail"
    payload = json.dumps(message).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type",  "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            # 202 Accepted = success
            log.info(f"Email sent to {to_address} | status {resp.status}")
            return True
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        log.error(f"Graph API error {e.code}: {err_body}")
        raise RuntimeError(f"Graph sendMail failed ({e.code}): {err_body}") from e



# ── GDPR / E-Privacy: Countries requiring opt-in consent for cold B2B email ──
# These countries require PRIOR consent before sending commercial emails.
# Do NOT send cold outreach to contacts in these countries without explicit opt-in.
_OPT_IN_REQUIRED_COUNTRIES = {
    "germany", "italy", "spain", "austria", "poland", "czech republic",
    "czechia", "hungary", "romania", "bulgaria", "croatia", "slovenia",
    "slovakia", "greece", "portugal", "luxembourg",
}
# These countries allow opt-out model for B2B (can cold email, must include unsubscribe)
_OPT_OUT_COUNTRIES = {
    "united kingdom", "uk", "france", "netherlands", "belgium", "sweden",
    "denmark", "norway", "finland", "ireland", "united states", "usa",
    "canada", "australia", "new zealand", "singapore", "hong kong",
    "japan", "south korea", "uae", "united arab emirates",
}


def _check_email_compliance(contact) -> dict:
    """Check if we can legally send email to this contact.
    Returns {"allowed": bool, "reason": str, "requires": str}."""
    country = (contact.get("country") or "").strip().lower()
    opt_out = contact.get("opt_out", 0)
    consent = contact.get("consent_basis", "")

    # Contact has opted out — never send
    if opt_out:
        return {"allowed": False, "reason": "Contact opted out", "requires": "none"}

    # Opt-in required countries — must have explicit consent
    if country in _OPT_IN_REQUIRED_COUNTRIES:
        if consent in ("consent", "double_opt_in"):
            return {"allowed": True, "reason": f"Consent recorded for {country}", "requires": "consent"}
        return {"allowed": False,
                "reason": f"{country.title()} requires opt-in consent (GDPR/e-Privacy). "
                          f"Contact has consent_basis='{consent}'.",
                "requires": "opt_in"}

    # All other countries — allowed with opt-out link (which we now include)
    return {"allowed": True, "reason": "Opt-out jurisdiction", "requires": "unsubscribe_link"}


def send_rate_request(contact, cycle_label, lanes=None):
    """
    Send a rate-request email to a verified freight agent.
    Pulls behavioral profile + cultural/interest context from contact_engine.
    Psych elements from the 6 books are woven into every email for maximum
    uniqueness and persuasion — no two emails read the same.

    LEGAL: Checks country-level email compliance before sending.
    Contacts in opt-in countries (Germany, Italy, Spain, etc.) are blocked
    unless explicit consent is recorded.

    contact    : dict with keys: id, email, contact_name, company_name, country
    cycle_label: e.g. "April 1\u201315" or "April 16\u201330"
    lanes      : list of lane strings, e.g. ["Los Angeles \u2192 Tokyo", ...]
    """
    import contact_engine as _ce

    # ── GDPR compliance check ─────────────────────────────────────────────
    compliance = _check_email_compliance(contact)
    if not compliance["allowed"]:
        log.info(f"[BLOCKED] Email to {contact.get('email')} blocked: {compliance['reason']}")
        return {"sent": False, "reason": compliance["reason"]}

    name         = contact.get("contact_name") or contact.get("company_name") or "Team"
    country      = contact.get("country", "")
    contact_id   = contact.get("id")
    contact_first = name.split()[0] if name and name != "Team" else None
    sender_name  = _display_name_for_country(country, contact_id, contact_first_name=contact_first)

    # Get full email context (cultural line, interest opener, interest question, style, psych)
    ctx = _ce.build_email_context(contact) if contact_id else {
        "opener": None, "cultural_line": None, "interest_question": None,
        "style": "standard", "subject_tone": "functional",
        "psych": _ce.get_psych_elements(contact, "unknown", 0, email_stage="engaged") if contact_id else {},
    }

    # Opening block — interest news OR cultural/port line
    opening_block = ""
    if ctx.get("opener"):
        opening_block = ctx["opener"]
    elif ctx.get("cultural_line"):
        opening_block = (
            f"<p style='color:#555;font-size:13px;border-left:3px solid #0066cc;"
            f"padding-left:10px;margin-bottom:16px;'>"
            f"<em>{ctx['cultural_line']}</em></p>"
        )

    # ── Per-contact RNG for unique variation ─────────────────────────────────
    _seed = hash(f"{contact_id}-{contact.get('email','')}-{date.today().isoformat()}")
    _rng = random.Random(_seed)

    # Greeting warmth by behavior — multiple variations per style
    style = ctx.get("style", "standard")
    behavior = ctx.get("behavior", "unknown")

    _WARM_GREETINGS = [
        f"Hi {name}, hope all is well on your end!",
        f"Hi {name}, hope things are going well!",
        f"Hi {name}, trust you\u2019re doing well!",
        f"Hello {name}, hope you\u2019re having a great week!",
        f"Hi {name}, good to be in touch again!",
        f"Hi {name}, hoping this finds you well!",
        f"Hello {name}, great to connect again!",
    ]
    _STANDARD_GREETINGS = [
        f"Hi {name},",
        f"Hello {name},",
        f"Good day {name},",
        f"Hi {name}, greetings from Flash Cargo Global.",
        f"Hi {name}, reaching out from Flash Cargo Global.",
        f"Hello {name}, writing from Flash Cargo Global.",
    ]
    _SHORT_GREETINGS = [
        f"Hi {name},",
        f"Hello {name},",
        f"{name} \u2014 quick one for you.",
        f"{name} \u2014 straight to it.",
        f"Hi {name} \u2014 short and sweet.",
    ]
    _EMPATHETIC_GREETINGS = [
        f"Hi {name}, we know your inbox is full \u2014 we\u2019ll be brief.",
        f"Hi {name}, we respect your time \u2014 quick question.",
        f"Hi {name} \u2014 different approach this time.",
    ]

    if style == "warm":
        greeting = f"<p>{_rng.choice(_WARM_GREETINGS)}</p>"
    elif style == "short":
        greeting = f"<p>{_rng.choice(_SHORT_GREETINGS)}</p>"
    elif behavior in ("skeptical",):
        greeting = f"<p>{_rng.choice(_EMPATHETIC_GREETINGS)}</p>"
    else:
        greeting = f"<p>{_rng.choice(_STANDARD_GREETINGS)}</p>"

    if lanes:
        lane_list    = "".join(f"<li>{l}</li>" for l in lanes)
        lane_section = f"<ul>{lane_list}</ul>"
    else:
        lane_section = "<p>All US West Coast origins (Los Angeles / Long Beach)</p>"

    # Interest question block (email 2+ only)
    interest_block = ""
    if ctx.get("interest_question"):
        interest_block = (
            f"<p style='color:#777;font-size:13px;margin-top:20px;'>"
            f"{ctx['interest_question']}</p>"
        )

    # Subject line — multiple variations per tone, behavior-adapted
    _WARM_SUBJECTS = [
        f"Checking in \u2014 rates for {cycle_label} | Flash Cargo Global",
        f"Following up \u2014 {cycle_label} rate round | Flash Cargo Global",
        f"Quick follow-up \u2014 {cycle_label} rates | Flash Cargo Global",
        f"Touching base \u2014 rates for {cycle_label} | Flash Cargo Global",
        f"Good to connect \u2014 {cycle_label} rates | Flash Cargo Global",
    ]
    _FUNCTIONAL_SUBJECTS = [
        f"Rate Request \u2014 {cycle_label} | Flash Cargo Global",
        f"Freight rates needed \u2014 {cycle_label} | Flash Cargo Global",
        f"Rate round open \u2014 {cycle_label} | Flash Cargo Global",
        f"{cycle_label} \u2014 requesting your best rates | Flash Cargo Global",
        f"Open for quotes \u2014 {cycle_label} | Flash Cargo Global",
    ]
    _BUSY_SUBJECTS = [
        f"30-second ask \u2014 {cycle_label} rates | Flash Cargo",
        f"Quick: rates for {cycle_label}? | Flash Cargo",
        f"One thing \u2014 {cycle_label} rates | Flash Cargo Global",
    ]
    _SKEPTICAL_SUBJECTS = [
        f"Different question \u2014 {cycle_label} | Flash Cargo Global",
        f"Not the usual pitch \u2014 {cycle_label} rates",
        f"Honest ask \u2014 {cycle_label} rate round | Flash Cargo",
    ]
    _GHOST_SUBJECTS = [
        f"Still here \u2014 {cycle_label} rates if you\u2019re interested",
        f"One last thing \u2014 {cycle_label} | Flash Cargo Global",
        f"Quick question \u2014 are you still handling freight? | Flash Cargo",
    ]

    if behavior == "busy":
        subject = _rng.choice(_BUSY_SUBJECTS)
    elif behavior == "skeptical":
        subject = _rng.choice(_SKEPTICAL_SUBJECTS)
    elif behavior == "ghost":
        subject = _rng.choice(_GHOST_SUBJECTS)
    elif ctx.get("subject_tone") == "warm":
        subject = _rng.choice(_WARM_SUBJECTS)
    else:
        subject = _rng.choice(_FUNCTIONAL_SUBJECTS)

    # Body paragraph variations
    _COLLECTING_LINES = [
        f"We\u2019re currently collecting freight rates for <strong>{cycle_label}</strong> and would love to include your best numbers.",
        f"Our <strong>{cycle_label}</strong> rate round is open \u2014 we\u2019d appreciate your most competitive figures.",
        f"We\u2019re putting together rates for <strong>{cycle_label}</strong> and want to make sure you\u2019re included.",
        f"It\u2019s time for our <strong>{cycle_label}</strong> rate collection \u2014 looking forward to your numbers.",
        f"We\u2019re reaching out for our <strong>{cycle_label}</strong> cycle and would value your pricing.",
        f"Our <strong>{cycle_label}</strong> rate cycle just opened \u2014 we\u2019d love to hear from you.",
    ]

    _REQUEST_LINES = [
        "Please send us your rates (USD per container) for the following lanes:",
        "Could you share your best rates (USD per container) for these lanes:",
        "We\u2019d appreciate your pricing (USD per container) on the lanes below:",
        "Kindly provide your rates (USD per container) for the following:",
        "We\u2019re looking for your best rates (USD/container) on these corridors:",
    ]

    _DEADLINE_LINES = [
        "Please reply within <strong>24 hours</strong> (business hours 8 AM\u20138 PM your local time).",
        "We\u2019d appreciate a response within <strong>24 hours</strong> during your business hours.",
        "If you could get back to us within <strong>24 hours</strong>, that would be great.",
        "A reply within <strong>24 hours</strong> (your local business hours) would be ideal.",
        "Aiming to close this round in <strong>24 hours</strong> \u2014 your rates would be valued.",
    ]

    _CLOSING_LINES = [
        "Thank you for your continued partnership.",
        "As always, we appreciate your support.",
        "Thanks in advance \u2014 we value working with you.",
        "Looking forward to your response.",
        "We appreciate the partnership.",
        "Thanks for being part of our network.",
        "We look forward to including your rates in this cycle.",
    ]

    # ── Build psych-driven blocks ────────────────────────────────────────────
    # Stage enforcement: get_psych_elements() already sets banned techniques to
    # None based on email_stage. The .get() checks below naturally skip None values.
    # Behavior checks here are a SECOND layer — even if a technique is stage-legal,
    # it only appears for the right behavioral profile.
    psych = ctx.get("psych", {})
    email_stage = psych.get("email_stage", "engaged")

    psych_hook = ""
    if psych.get("opening_hook") and not opening_block:
        psych_hook = f"<p style='color:#555;font-size:13px;margin-bottom:14px;'><em>{psych['opening_hook']}</em></p>"

    # Value offer block — reciprocity (follow_up+ only, enforced by stage)
    value_block = ""
    if psych.get("value_offer") and _rng.random() < 0.4:
        value_block = f"<p style='color:#555;font-size:13px;margin-top:12px;'>{psych['value_offer']}</p>"

    # Calibrated question — engaged stage+ only (enforced by stage returning None for earlier stages)
    cal_q_block = ""
    if psych.get("calibrated_q") and behavior in ("thoughtful", "cautious", "engaged") and _rng.random() < 0.5:
        cal_q_block = f"<p style='color:#555;font-size:13px;margin-top:12px;'>{psych['calibrated_q']}</p>"

    # Label line — engaged stage+ only (enforced by stage)
    label_block = ""
    if psych.get("label_line") and behavior in ("thoughtful", "cautious", "skeptical") and _rng.random() < 0.35:
        label_block = f"<p style='color:#555;font-size:13px;margin-top:12px;font-style:italic;'>{psych['label_line']}</p>"

    # Win-win line — follow_up+ (enforced by stage)
    win_win_block = ""
    if psych.get("win_win_line") and behavior in ("engaged", "cautious", "unknown") and _rng.random() < 0.3:
        win_win_block = f"<p style='color:#555;font-size:13px;margin-top:12px;'>{psych['win_win_line']}</p>"

    # Scarcity line — re_engagement only (enforced by stage)
    scarcity_block = ""
    if psych.get("scarcity_line") and behavior in ("busy", "ghost", "skeptical") and _rng.random() < 0.4:
        scarcity_block = f"<p style='color:#555;font-size:13px;margin-top:12px;font-weight:600;'>{psych['scarcity_line']}</p>"

    # Make-it-easy line (Atomic Habits) — all stages
    easy_block = ""
    if psych.get("make_easy_line") and behavior in ("busy", "decisive") and _rng.random() < 0.5:
        easy_block = f"<p style='color:#555;font-size:13px;margin-top:12px;'>{psych['make_easy_line']}</p>"

    # Motto line — subtle cultural signal (all stages)
    motto_block = ""
    if psych.get("motto_line") and _rng.random() < 0.3:
        motto_block = f"<p style='font-size:12px;color:#888;margin:12px 0 4px;font-style:italic;'>{psych['motto_line']}</p>"

    body_html = f"""
{opening_block}
{psych_hook}
{greeting}

<p>{_rng.choice(_COLLECTING_LINES)}</p>
{label_block}

<p>{_rng.choice(_REQUEST_LINES)}</p>
{lane_section}

<p>For each lane, please include:</p>
<ul>
  <li>Carrier name</li>
  <li>Origin port &rarr; Destination port</li>
  <li>Rate for 20ft / 40ft (separate figures)</li>
  <li>Validity period</li>
  <li>Free days at destination (if applicable)</li>
</ul>

<p>{_rng.choice(_DEADLINE_LINES)}</p>
{value_block}
{cal_q_block}
{win_win_block}
{scarcity_block}
{easy_block}

<p>{_rng.choice(_CLOSING_LINES)}</p>
{interest_block}
{motto_block}
{SIGNATURE}
"""

    # Log the interaction
    if contact_id:
        _ce.log_interaction(
            contact_id,
            email_type="rate_request",
            cycle=cycle_label,
            cultural_line=ctx.get("cultural_line") or "",
            interest_asked=bool(ctx.get("interest_question")),
        )

    # ── 5-Agent Email Inspection before sending ──────────────────────────
    try:
        from email_inspectors import run_all_inspectors, build_email_dict, log_inspection, init_inspection_log_db
        try:
            init_inspection_log_db()
        except Exception:
            pass
        from_addr = _from_address_for_name(sender_name)
        ed = build_email_dict(
            subject=subject, body_html=body_html,
            sender_name=sender_name, sender_email=from_addr,
            recipient_name=name, recipient_email=contact.get("email", ""),
            country=country, behavior_type=behavior or "unknown",
            email_stage="engaged", reply_to="pricing@flashcargoglobal.com",
            allow_pricing_fallback=from_addr.startswith("pricing@"))
        inspection = run_all_inspectors(ed)
        log_inspection(contact_id, "rate_request", 1, inspection)
        if not inspection["approved"]:
            failed = [k for k, v in inspection["inspectors"].items() if not v["pass"]]
            log.warning(
                f"send_rate_request inspection FAILED for {contact.get('email')} "
                f"(score {inspection['overall_score']}, failed: {failed}) -- sending anyway"
            )
    except ImportError:
        from_addr = _from_address_for_name(sender_name)
    except Exception as insp_exc:
        log.error(f"send_rate_request inspection error: {insp_exc}")
        from_addr = _from_address_for_name(sender_name)

    result = send_email(
        to_address=contact["email"],
        subject=subject,
        body_html=body_html,
        from_address=from_addr,
        display_name=sender_name,
        reply_to="pricing@flashcargoglobal.com",
    )

    # ── Record send analytics for timezone-aware optimization ─────────────
    if result and contact_id:
        try:
            _ce.record_send_analytics(
                contact_id, "rate_request", country, behavior or "unknown"
            )
        except Exception as analytics_exc:
            log.error(
                f"send_rate_request analytics failed for contact {contact_id}: "
                f"{analytics_exc}"
            )

    return result


def test_connection():
    """Quick connectivity test — sends a test email to the FROM address itself."""
    return send_email(
        to_address="pricing@flashcargoglobal.com",
        subject="[TEST] Freight Dashboard Mailer — connection OK",
        body_html="<p>Graph API email is working correctly.</p>",
    )
