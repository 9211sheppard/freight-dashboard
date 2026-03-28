"""
email_inspectors.py -- 5-Agent Email Inspection System for Flash Cargo Global

Every outbound email must pass ALL 5 inspectors before sending.
If any inspector fails, the email is regenerated and re-inspected (max 3 attempts).
After 3 failures, the email is logged and skipped -- never send a bad email.

Agents:
  1. Identity Inspector   -- sender/recipient name collisions, alias validation
  2. Redundancy Inspector -- semantic deduplication, filler detection, word count
  3. Psychology Inspector  -- Cialdini, Kahneman, stage enforcement, commitment ladder
  4. Formatting Inspector  -- HTML structure, CTA, length, signature
  5. Human Test Inspector  -- 3-second test, trust test, action test, reply score
"""

import json
import logging
import re
import html as html_module
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_FILLER_PHRASES = [
    "i hope this email finds you well",
    "i hope this finds you well",
    "i'm reaching out to",
    "i am reaching out to",
    "i wanted to reach out",
    "i wanted to",
    "i just wanted to",
    "as per our conversation",
    "per our conversation",
    "please do not hesitate",
    "don't hesitate to",
    "do not hesitate to",
    "at your earliest convenience",
    "looking forward to hearing from you",
    "please find attached",
    "i'm writing to inform you",
    "i am writing to inform you",
    "this is to inform you",
    "allow me to introduce",
    "i trust this message finds you",
    "just checking in",
    "just following up",
    "just wanted to check",
    "touching base",
    "circling back",
    "at your convenience",
    "i look forward to",
    "i hope this message finds you well",
    "please don’t hesitate",
    "we specialize in",
    "we are pleased to",
    "we would like to",
    "i would like to introduce",
    "thank you for your time",
    "best regards",
    "kind regards",
    "warm regards",
]

_EMPTY_AUTHORITY = [
    "we're the best",
    "we are the best",
    "industry leading",
    "industry-leading",
    "world class",
    "world-class",
    "premier provider",
    "leading provider",
    "number one",
    "#1",
    "unmatched service",
    "unparalleled",
    "second to none",
    "best in class",
    "best-in-class",
    "top-notch",
]

_CREEPY_PATTERNS = [
    "your national motto",
    "as they say in your country",
    "your people say",
    "your culture teaches",
    "in your tradition",
    "your ancestors",
    "i noticed you on linkedin",
    "i saw your photo",
    "i've been watching",
    "i've been following you",
    "i found your personal",
]

_WORD_LIMITS = {
    "intro": (80, 200), "follow_up": (60, 150), "rate_request": (50, 150),
    "engaged": (50, 150), "re_engagement": (50, 150),
}

_SCARCITY_PHRASES = [
    "limited time",
    "act now",
    "don't miss out",
    "last chance",
    "spots are filling",
    "only a few",
    "running out",
    "deadline approaching",
    "closing soon",
    "hurry",
    "before it's too late",
    "exclusive offer",
    "once in a lifetime",
]

_STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 
    'for', 'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 
    'could', 'should', 'may', 'might', 'shall', 'can', 'this', 'that', 'these', 'those', 
    'i', 'you', 'he', 'she', 'it', 'we', 'they', 'my', 'your', 'his', 
    'her', 'its', 'our', 'their', 'me', 'him', 'us', 'them', 'not', 'no', 
    'so', 'if', 'as', 'just', 'also', 'very', 'too', 'up', 'out', 'about', 
    'into', 'over', 'after', 'before', 'between', 'through', 'during', 'each', 'all', 'any', 
    'both', 'more', 'most', 'other', 'some', 'such', 'than', 'then', 'there', 'here', 
    'when', 'where', 'how', 'what', 'which', 'who', 'whom', 'why', 
}


def _strip_html(html_str):
    """Remove HTML tags and decode entities to get plain text."""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_str, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html_module.unescape(text)
    return text.strip()


def _extract_sentences(text):
    text = re.sub(r'\s+', ' ', text).strip()
    raw = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in raw if len(s.strip()) > 10]


def _extract_keywords(sentence):
    words = re.findall(r'[a-z]+', sentence.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _word_count(text):
    return len(re.findall(r'\S+', text))


# ==============================================================================
# AGENT 1: Identity Inspector
# ==============================================================================
def inspect_identity(email_dict):
    """Validates sender identity consistency and appropriateness."""
    issues = []
    score = 100
    sender_name = (email_dict.get("sender_name") or "").strip()
    sender_email = (email_dict.get("sender_email") or "").strip().lower()
    recipient_name = (email_dict.get("recipient_name") or "").strip()
    country = (email_dict.get("country") or "").strip().lower()
    body_html = email_dict.get("body_html") or ""
    reply_to = (email_dict.get("reply_to") or "").strip().lower()

    sender_first = sender_name.split("|")[0].strip().split()[0].lower() if sender_name else ""
    recipient_first = recipient_name.split()[0].lower() if recipient_name else ""

    if sender_first and recipient_first and sender_first == recipient_first:
        issues.append("Sender '%s' matches recipient '%s' -- identity collision" % (sender_first, recipient_first))
        score -= 30

    if sender_first and sender_email:
        prefix = sender_email.split("@")[0].lower() if "@" in sender_email else ""
        if prefix and prefix != "pricing" and prefix != sender_first:
            issues.append("Email prefix '%s' != sender name '%s'" % (prefix, sender_first))
            score -= 15

    if sender_email.startswith("pricing@") and not email_dict.get("allow_pricing_fallback"):
        issues.append("Sending from pricing@ instead of personal alias -- impersonal")
        score -= 20

    if sender_first:
        sig_area = body_html.lower()[int(len(body_html) * 0.7):]
        if sender_first not in sig_area and "pricing team" in sig_area:
            issues.append("Signature says Pricing Team but sent by named person")
            score -= 15

    if reply_to and "pricing@" not in reply_to:
        issues.append("Reply-to '%s' not pricing@" % reply_to)
        score -= 10

    try:
        from mailer import _COUNTRY_NAMES
        if country and sender_first:
            names = _COUNTRY_NAMES.get(country, [])
            if names and sender_first not in [n.lower() for n in names]:
                issues.append("Sender '%s' not culturally matched for '%s'" % (sender_first, country))
                score -= 5
    except ImportError:
        pass

    # ── Local-language subject / country mismatch check ─────────────────────
    # If a local-language subject is used, verify it matches the contact's country.
    # A Turkish subject should never go to a German contact.
    subject = (email_dict.get("subject") or "").strip()
    if subject and country:
        try:
            from intro_mailer import _COUNTRY_SUBJECTS
            for subj_country, templates in _COUNTRY_SUBJECTS.items():
                if subj_country == country:
                    continue  # correct country — skip
                # Check if subject matches any template from a DIFFERENT country
                for tpl in templates:
                    # Build a rough regex from the template: replace placeholders with .*
                    import re as _re
                    pattern = _re.escape(tpl)
                    for ph in [r"\{greeting_name\}", r"\{sender_first\}", r"\{_co\}", r"\{_loc\}"]:
                        pattern = pattern.replace(_re.escape("{" + ph.strip("\\{}") + "}"), ".+")
                    # Check for distinctive non-ASCII words (>= 3 chars) from the template
                    # that are unique to that language
                    non_ascii_words = [w for w in tpl.split() if any(ord(c) > 127 for c in w) and len(w) >= 3]
                    if non_ascii_words and any(w in subject for w in non_ascii_words):
                        issues.append(
                            "Local-language subject contains '%s' words but contact country is '%s'"
                            % (subj_country, country)
                        )
                        score -= 25
                        break
        except ImportError:
            pass

    passed = score >= 60 and not any("identity collision" in i for i in issues)
    return {"pass": passed, "issues": issues, "score": max(0, score)}


# ==============================================================================
# AGENT 2: Redundancy Inspector
# ==============================================================================
def inspect_redundancy(email_dict):
    """Linguistics PhD agent -- eliminates wasted words."""
    issues = []
    score = 100
    subject = (email_dict.get("subject") or "").strip()
    body_html = email_dict.get("body_html") or ""
    body_text = email_dict.get("body_text") or _strip_html(body_html)
    email_stage = (email_dict.get("email_stage") or "intro").strip().lower()
    sentences = _extract_sentences(body_text)
    body_lower = body_text.lower()

    for filler in _FILLER_PHRASES:
        if filler in body_lower:
            issues.append("Filler: '%s'" % filler)
            score -= 8

    for i in range(len(sentences)):
        kw_i = _extract_keywords(sentences[i])
        if not kw_i:
            continue
        for j in range(i + 1, len(sentences)):
            kw_j = _extract_keywords(sentences[j])
            if not kw_j:
                continue
            overlap = kw_i & kw_j
            smaller = min(len(kw_i), len(kw_j))
            if smaller > 0 and len(overlap) / smaller > 0.50:
                issues.append("Sentences %d & %d redundant (overlap=%s)" % (i+1, j+1, sorted(overlap)))
                score -= 10

    if sentences and subject:
        s_kw = _extract_keywords(subject)
        f_kw = _extract_keywords(sentences[0])
        if s_kw and f_kw:
            ov = s_kw & f_kw
            sm = min(len(s_kw), len(f_kw))
            if sm > 0 and len(ov) / sm > 0.60:
                issues.append("Subject repeats first sentence")
                score -= 10

    wc = _word_count(body_text)
    lo, hi = _WORD_LIMITS.get(email_stage, (50, 200))
    if wc < lo:
        issues.append("Too short: %d words (min %d)" % (wc, lo))
        score -= 15
    elif wc > hi:
        issues.append("Too long: %d words (max %d)" % (wc, hi))
        score -= 10

    return {"pass": score >= 60, "issues": issues, "score": max(0, score)}




# ==============================================================================
# AGENT 3: Psychology Inspector
# ==============================================================================
def inspect_psychology(email_dict):
    """Behavioral scientist agent -- Cialdini, Kahneman, stage enforcement."""
    issues = []
    score = 100
    subject = (email_dict.get("subject") or "").strip()
    body_html = email_dict.get("body_html") or ""
    body_text = email_dict.get("body_text") or _strip_html(body_html)
    email_stage = (email_dict.get("email_stage") or "intro").strip().lower()
    body_lower = body_text.lower()

    # Cialdini: Reciprocity -- give before ask
    if email_stage in ("engaged", "rate_request"):
        ask_pos, give_pos = -1, -1
        for pat in ["please send", "could you share", "provide your rates",
                    "requesting your", "appreciate your pricing", "looking for your"]:
            pos = body_lower.find(pat)
            if pos >= 0 and (ask_pos < 0 or pos < ask_pos):
                ask_pos = pos
        for pat in ["we'll include you", "cargo inquiries", "rate requests tailored",
                    "volume", "partnership", "we'll send", "we'll route"]:
            pos = body_lower.find(pat)
            if pos >= 0 and (give_pos < 0 or pos < give_pos):
                give_pos = pos
        if ask_pos >= 0 and give_pos >= 0 and give_pos > ask_pos:
            issues.append("Reciprocity: asks before offering value")
            score -= 5

    # Social Proof must be specific
    for phrase in ["countries", "agents", "partners", "ports", "clients"]:
        idx = body_lower.find(phrase)
        if idx >= 0:
            window = body_lower[max(0, idx - 30):idx]
            if not re.search(r"\d+", window):
                for v in ["many", "several", "numerous", "various", "lots of"]:
                    if v in window:
                        issues.append("Vague social proof: %s %s" % (v, phrase))
                        score -= 5
                        break

    for claim in _EMPTY_AUTHORITY:
        if claim in body_lower:
            issues.append("Empty authority: %s" % claim)
            score -= 10

    if email_stage != "re_engagement":
        for phrase in _SCARCITY_PHRASES:
            if phrase in body_lower:
                issues.append("Scarcity %s in %s -- banned" % (phrase, email_stage))
                score -= 15

    if len(subject) > 80:
        issues.append("Subject %d chars -- too long" % len(subject))
        score -= 8

    markers = ["rate", "lane", "carrier", "freight", "cargo", "port",
               "container", "origin", "destination", "partner"]
    if sum(1 for m in markers if m in body_lower) < 2:
        issues.append("Low substance -- add freight terms")
        score -= 10

    if email_stage == "intro":
        for qp in ["what would it take", "how would you feel", "what does your team",
                    "what challenges", "how do you handle"]:
            if qp in body_lower:
                issues.append("Calibrated Q %s banned in intro" % qp)
                score -= 15
        for lp in ["you seem like", "you're clearly", "you are clearly",
                    "you strike me as", "someone like you"]:
            if lp in body_lower:
                issues.append("Label %s banned in intro" % lp)
                score -= 12
        for mp in ["and also", "additionally please", "we also need", "secondly", "third"]:
            if mp in body_lower:
                issues.append("Multiple asks (%s) in intro" % mp)
                score -= 10

    return {"pass": score >= 60, "issues": issues, "score": max(0, score)}


# ==============================================================================
# AGENT 4: Formatting Inspector
# ==============================================================================
def inspect_formatting(email_dict):
    issues = []
    score = 100
    body_html = email_dict.get("body_html") or ""
    body_text = email_dict.get("body_text") or _strip_html(body_html)
    email_stage = (email_dict.get("email_stage") or "intro").strip().lower()

    for tag in ["p", "div", "table", "tr", "td", "ul", "li", "strong", "em"]:
        pat_open = r'<%s[\\s>]' % tag
        pat_close = r'</%s>' % tag
        opens = len(re.findall(pat_open, body_html, re.IGNORECASE))
        closes = len(re.findall(pat_close, body_html, re.IGNORECASE))
        if opens > closes + 2:
            issues.append("Unclosed <%s> tags" % tag)
            score -= 5

    has_cta = bool(re.search(
        r'<a\\s+[^>]*style="[^"]*display:\\s*inline-block[^"]*background[^"]*"',
        body_html, re.IGNORECASE))
    if not has_cta:
        has_cta = bool(re.search(
            r'<a\\s+[^>]*style="[^"]*padding[^"]*border-radius[^"]*"',
            body_html, re.IGNORECASE))
    if not has_cta and email_stage == "intro":
        issues.append("No CTA button in intro email")
        score -= 15

    if has_cta:
        m = re.search(r'<a\\s+[^>]*style="[^"]*padding', body_html, re.IGNORECASE)
        if m:
            before = body_html[:m.start()]
            pc = len(re.findall(r'<p[\\s>]', before, re.IGNORECASE))
            if pc > 6:
                issues.append("%d paragraphs before CTA" % pc)
                score -= 5

    for s in re.findall(r'font-size:\\s*(\\d+)px', body_html):
        if int(s) < 10:
            issues.append("Font %spx too small" % s)
            score -= 5

    for href in re.findall(r'<a\\s+[^>]*href="([^"]*)"', body_html, re.IGNORECASE):
        if not href or href == "#" or href.startswith("javascript:"):
            issues.append("Invalid href: %s" % href)
            score -= 5

    wc = _word_count(body_text)
    mx = {"intro": 250, "follow_up": 200, "rate_request": 200,
          "engaged": 200, "re_engagement": 200}.get(email_stage, 250)
    if wc > mx:
        issues.append("%d words (max %d)" % (wc, mx))
        score -= 10

    if not any(sp in body_html.lower() for sp in
               ["flash cargo global", "flashcargoglobal.com", "worldwide freight"]):
        issues.append("No signature block")
        score -= 10

    if body_text and re.search(r'<[a-zA-Z][^>]*>', body_text):
        issues.append("Raw HTML in plain text")
        score -= 10

    return {"pass": score >= 60, "issues": issues, "score": max(0, score)}

# ==============================================================================
# AGENT 5: Human Test Inspector (AI Detection)
# ==============================================================================
# AI detection checklist: filler phrases, specificity, formal patterns,
# word count, template structure. Score: 0-2 AI signals = pass, 3+ = fail
def inspect_human_test(email_dict):
    issues = []
    score = 100
    reply_score = 7
    ai_signals = 0
    subject = (email_dict.get("subject") or "").strip()
    body_html = email_dict.get("body_html") or ""
    body_text = email_dict.get("body_text") or _strip_html(body_html)
    email_stage = (email_dict.get("email_stage") or "intro").strip().lower()
    country = (email_dict.get("country") or "").strip()
    recipient_name = (email_dict.get("recipient_name") or "").strip()
    body_lower = body_text.lower()
    first_name = recipient_name.split()[0] if recipient_name else ""
    words = body_text.split()
    wc = _word_count(body_text)
    first_15 = " ".join(words[:15]).lower() if len(words) >= 15 else body_lower

    # — AI SIGNAL 1: Filler phrases (+1 per filler found)
    filler_count = 0
    for filler in _FILLER_PHRASES:
        if filler in body_lower:
            filler_count += 1
            issues.append("AI filler: %s" % filler)
            score -= 8
            reply_score -= 0.5
    ai_signals += filler_count

    # — AI SIGNAL 2: No specific details (city, port, company name)
    specific_details = 0
    if country and country.lower() in body_lower:
        specific_details += 1
    # Extract city/company from contact data passed in email_dict
    _city = (email_dict.get("city") or "").strip()
    _company = (email_dict.get("company_name") or "").strip()
    if _city and _city.lower() in body_lower:
        specific_details += 1
    if _company and _company.lower() in body_lower:
        specific_details += 1
    port_terms = ["port", "istanbul", "hamburg", "mumbai", "shanghai", "rotterdam",
                  "fcl", "lcl", "container", "maersk", "msc", "cma", "hapag",
                  "cosco", "evergreen", "zim"]
    for pt in port_terms:
        if pt in body_lower:
            specific_details += 1
            break
    if specific_details < 2:
        ai_signals += 1
        issues.append("AI signal: only %d specific details (need 2+)" % specific_details)
        score -= 12
        reply_score -= 1

    # — AI SIGNAL 3: Formal greeting + formal sign-off
    formal_greetings = ["dear ", "good morning", "good afternoon", "good evening",
                        "i hope this", "greetings"]
    formal_signoffs = ["best regards", "kind regards", "warm regards", "sincerely",
                       "yours truly", "respectfully", "with best wishes"]
    has_formal_greeting = any(fg in first_15 for fg in formal_greetings)
    tail_text = body_lower[int(len(body_lower) * 0.8):]
    has_formal_signoff = any(fs in tail_text for fs in formal_signoffs)
    if has_formal_greeting and has_formal_signoff:
        ai_signals += 1
        issues.append("AI signal: formal greeting + formal sign-off = robot pattern")
        score -= 10
        reply_score -= 1

    # — AI SIGNAL 4: Over 150 words for intros
    if email_stage == "intro" and wc > 150:
        ai_signals += 1
        issues.append("AI signal: intro %d words (max 150 for human feel)" % wc)
        score -= 10
        reply_score -= 1

    # — AI SIGNAL 5: Template structure detection
    structure_markers = [
        ("my name is", "i" + chr(8217) + "m ", "allow me to introduce"),
        ("we came across", "your company stood out", "we" + chr(8217) + "ve been expanding", "while sourcing"),
        ("two quick questions", "we" + chr(8217) + "d love to know", "just two things"),
    ]
    sections_found = 0
    for marker_group in structure_markers:
        if any(m in body_lower for m in marker_group):
            sections_found += 1
    if sections_found >= 3:
        ai_signals += 1
        issues.append("AI signal: follows exact template structure")
        score -= 8

    # — EXISTING CHECKS (freight relevance, name, country, etc)
    triggers = ["freight", "cargo", "shipping", "logistics", "agent",
                "partner", "ocean", "air"]
    if country:
        triggers.append(country.lower())
    post = body_lower
    if re.match(r'^hi\s|^hello\s|^dear\s|^good\s|^hey\s', first_15):
        blines = body_text.split(chr(10))
        post = " ".join(blines[1:3]).lower() if len(blines) > 1 else body_lower
    p30 = " ".join(post.split()[:30]).lower()
    if sum(1 for t in triggers if t and t in p30) < 1:
        issues.append("3-second FAIL: no freight relevance in opening")
        score -= 15
        reply_score -= 2

    if first_name and first_name.lower() not in first_15:
        issues.append("Name not in greeting -- generic feel")
        score -= 10
        reply_score -= 1
    if country and country.lower() not in body_lower:
        issues.append("Country never mentioned -- mass email feel")
        score -= 10
        reply_score -= 1

    if email_stage == "intro" and wc > 200:
        issues.append("Intro %d words -- way too long" % wc)
        score -= 15
        reply_score -= 2
    elif email_stage != "intro" and wc > 180:
        issues.append("%d words -- trim it" % wc)
        score -= 5

    vals = ["cargo", "rate request", "volume", "inquiries your way", "partner",
            "include you", "send you", "route", "rate round", "freight", "lanes", "container"]
    if sum(1 for v in vals if v in body_lower) < 1:
        issues.append("No value proposition")
        score -= 15
        reply_score -= 2

    for pat in _CREEPY_PATTERNS:
        if pat in body_lower:
            issues.append("Creepy: %s" % pat)
            score -= 20
            reply_score -= 3

    ctas = re.findall(
        r'<a\s+[^>]*style="[^"]*(?:padding|display:\s*inline-block)[^"]*"[^>]*>(.*?)</a>',
        body_html, re.IGNORECASE)
    if email_stage == "intro":
        if len(ctas) == 0:
            issues.append("No CTA button")
            score -= 10
            reply_score -= 2
        elif len(ctas) > 2:
            issues.append("%d CTAs -- too many" % len(ctas))
            score -= 8
            reply_score -= 1

    # Bonus for human feel
    if first_name and first_name.lower() in first_15:
        reply_score += 0.5
    if country and country.lower() in subject.lower():
        reply_score += 0.5
    if wc < 150:
        reply_score += 0.5
    if specific_details >= 3:
        reply_score += 1

    reply_score = max(1, min(10, round(reply_score)))
    if reply_score < 6:
        issues.append("Reply score %d/10 -- would be deleted" % reply_score)
        score -= 15

    # — FINAL: AI signal scoring (0-2 pass, 3+ fail)
    ai_pass = ai_signals <= 2
    if not ai_pass:
        issues.append("AI DETECTION FAIL: %d AI signals (max 2)" % ai_signals)
        score -= 20

    return {"pass": score >= 60 and reply_score >= 6 and ai_pass, "issues": issues,
            "score": max(0, score), "reply_score": reply_score, "ai_signals": ai_signals}

# ==============================================================================
# INTEGRATION
# ==============================================================================
def run_all_inspectors(email_dict):
    inspectors = {
        "identity":   inspect_identity(email_dict),
        "redundancy": inspect_redundancy(email_dict),
        "psychology": inspect_psychology(email_dict),
        "formatting": inspect_formatting(email_dict),
        "human_test": inspect_human_test(email_dict),
    }
    all_pass = all(r["pass"] for r in inspectors.values())
    overall = round(sum(r["score"] for r in inspectors.values()) / 5)
    return {"approved": all_pass, "inspectors": inspectors, "overall_score": overall}


def init_inspection_log_db():
    import os as _os
    from config import DB_PATH
    _os.makedirs(_os.path.dirname(DB_PATH), exist_ok=True)
    from database import get_db
    conn = get_db()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS email_inspection_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "contact_id INTEGER, "
        "email_type TEXT DEFAULT '', "
        "attempt INTEGER DEFAULT 1, "
        "passed INTEGER DEFAULT 0, "
        "issues_json TEXT DEFAULT '[]', "
        "score INTEGER DEFAULT 0, "
        "inspector_details TEXT DEFAULT '{}', "
        "timestamp TEXT DEFAULT '')"
    )
    conn.commit()
    conn.close()


def log_inspection(contact_id, email_type, attempt, result):
    try:
        from database import get_db
        conn = get_db()
        all_issues = []
        for name, insp in result.get("inspectors", {}).items():
            for issue in insp.get("issues", []):
                all_issues.append("[%s] %s" % (name, issue))
        conn.execute(
            "INSERT INTO email_inspection_log "
            "(contact_id, email_type, attempt, passed, issues_json, score, "
            "inspector_details, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (contact_id, email_type, attempt,
             1 if result.get("approved") else 0,
             json.dumps(all_issues), result.get("overall_score", 0),
             json.dumps({k: {"pass": v["pass"], "score": v["score"],
                             "issue_count": len(v["issues"])}
                         for k, v in result.get("inspectors", {}).items()}),
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    except Exception as exc:
        log.error("log_inspection failed: %s" % exc)


def build_email_dict(subject, body_html, sender_name, sender_email,
                     recipient_name="", recipient_email="", country="",
                     behavior_type="unknown", email_stage="intro",
                     reply_to="pricing@flashcargoglobal.com",
                     allow_pricing_fallback=False,
                     city="", company_name=""):
    return {
        "subject": subject, "body_html": body_html,
        "body_text": _strip_html(body_html),
        "sender_name": sender_name, "sender_email": sender_email,
        "recipient_name": recipient_name, "recipient_email": recipient_email,
        "country": country, "behavior_type": behavior_type,
        "email_stage": email_stage, "reply_to": reply_to,
        "allow_pricing_fallback": allow_pricing_fallback,
        "city": city, "company_name": company_name,
    }


def inspect_and_retry(build_fn, contact, email_type="intro",
                      max_attempts=3, **build_kwargs):
    from mailer import _display_name_for_country, _from_address_for_name
    contact_id = contact.get("id", 0)
    country = (contact.get("country") or "").strip()
    contact_name = (contact.get("contact_name") or "").strip()
    # Strip honorifics (Mr., Ms., Mrs., Dr., etc.)
    _hon = {"mr", "ms", "mrs", "dr", "prof"}
    _parts = contact_name.split() if contact_name else []
    while _parts and _parts[0].lower().rstrip(".") in _hon:
        _parts.pop(0)
    contact_first = _parts[0] if _parts else None
    clean_name = " ".join(_parts) if _parts else contact_name
    email_addr = (contact.get("email") or "").strip()
    sender_name = _display_name_for_country(
        country, contact_id, contact_first_name=contact_first)
    sender_email = _from_address_for_name(sender_name)
    email_stage = "intro" if email_type == "intro" else "engaged"
    last_result = None
    for attempt in range(1, max_attempts + 1):
        try:
            subject, body_html = build_fn(contact, **build_kwargs)
        except Exception as exc:
            log.error("inspect_and_retry build fail #%d: %s" % (attempt, exc))
            continue
        ed = build_email_dict(
            subject=subject, body_html=body_html,
            sender_name=sender_name, sender_email=sender_email,
            recipient_name=clean_name, recipient_email=email_addr,
            country=country,
            behavior_type=contact.get("behavior_type", "unknown"),
            email_stage=email_stage,
            reply_to="pricing@flashcargoglobal.com",
            allow_pricing_fallback=sender_email.startswith("pricing@"),
            city=(contact.get("city") or "").strip(),
            company_name=(contact.get("company_name") or "").strip())
        result = run_all_inspectors(ed)
        last_result = result
        log_inspection(contact_id, email_type, attempt, result)
        if result["approved"]:
            log.info("[inspect] %s contact %s PASSED #%d score %d" % (
                email_type, contact_id, attempt, result["overall_score"]))
            return subject, body_html, result
        failed = [k for k, v in result["inspectors"].items() if not v["pass"]]
        log.warning("[inspect] %s contact %s FAILED #%d score=%d failed=%s" % (
            email_type, contact_id, attempt, result["overall_score"], failed))
    log.error("[inspect] %s contact %s FAILED all %d attempts -- skip" % (
        email_type, contact_id, max_attempts))
    return None, None, last_result
