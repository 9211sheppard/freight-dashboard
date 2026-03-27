"""
test_psych_staging.py — Verify that psychological techniques are correctly
staged across email types. Run this to prove the fix works.

Usage:  python test_psych_staging.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from contact_engine import get_psych_elements
from intro_mailer import build_intro_email

# ── Fake contacts for testing ────────────────────────────────────────────────
CONTACTS = [
    {"id": 1, "email": "test1@example.com", "contact_name": "Ali Hassan",
     "company_name": "Gulf Freight", "country": "UAE", "city": "Dubai"},
    {"id": 2, "email": "test2@example.com", "contact_name": "Maria Lopez",
     "company_name": "Cargo Sur", "country": "Chile", "city": "Santiago"},
    {"id": 3, "email": "test3@example.com", "contact_name": "Kenji Tanaka",
     "company_name": "Nippon Freight", "country": "Japan", "city": "Tokyo"},
    {"id": 4, "email": "test4@example.com", "contact_name": "Piotr Nowak",
     "company_name": "Euro Ship", "country": "Poland", "city": "Warsaw"},
    {"id": 5, "email": "test5@example.com", "contact_name": "Ahmed Mohamed",
     "company_name": "Nile Cargo", "country": "Egypt", "city": "Cairo"},
]

BANNED_INTRO_KEYS = ["calibrated_q", "label_line", "scarcity_line", "win_win_line", "value_offer"]
BANNED_FOLLOWUP_KEYS = ["calibrated_q", "label_line", "scarcity_line"]
BANNED_ENGAGED_KEYS = ["scarcity_line"]

PASS = 0
FAIL = 0

def check(description, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {description}")
    else:
        FAIL += 1
        print(f"  FAIL: {description}")

# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 70)
print("TEST 1: INTRO STAGE — get_psych_elements(email_stage='intro')")
print("=" * 70)
for c in CONTACTS:
    psych = get_psych_elements(c, "unknown", 0, email_stage="intro")
    print(f"\n  Contact: {c['contact_name']} ({c['country']})")
    print(f"    email_stage: {psych.get('email_stage')}")
    print(f"    social_proof: {psych.get('social_proof', 'N/A')[:60]}...")
    print(f"    make_easy_line: {psych.get('make_easy_line', 'N/A')}")
    for key in BANNED_INTRO_KEYS:
        check(f"{key} is None for intro", psych.get(key) is None)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 2: FOLLOW-UP STAGE — get_psych_elements(email_stage='follow_up')")
print("=" * 70)
for c in CONTACTS:
    psych = get_psych_elements(c, "engaged", 1, email_stage="follow_up")
    print(f"\n  Contact: {c['contact_name']} ({c['country']})")
    print(f"    win_win_line: {psych.get('win_win_line', 'N/A')}")
    print(f"    value_offer: {psych.get('value_offer', 'N/A')}")
    check("win_win_line IS present for follow_up", psych.get("win_win_line") is not None)
    check("value_offer IS present for follow_up", psych.get("value_offer") is not None)
    for key in BANNED_FOLLOWUP_KEYS:
        check(f"{key} is None for follow_up", psych.get(key) is None)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 3: ENGAGED STAGE — get_psych_elements(email_stage='engaged')")
print("=" * 70)
for c in CONTACTS:
    psych = get_psych_elements(c, "thoughtful", 3, email_stage="engaged")
    print(f"\n  Contact: {c['contact_name']} ({c['country']})")
    print(f"    calibrated_q: {psych.get('calibrated_q', 'N/A')}")
    print(f"    label_line: {psych.get('label_line', 'N/A')}")
    check("calibrated_q IS present for engaged", psych.get("calibrated_q") is not None)
    check("label_line IS present for engaged", psych.get("label_line") is not None)
    for key in BANNED_ENGAGED_KEYS:
        check(f"{key} is None for engaged", psych.get(key) is None)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 4: RE-ENGAGEMENT STAGE — get_psych_elements(email_stage='re_engagement')")
print("=" * 70)
for c in CONTACTS:
    psych = get_psych_elements(c, "ghost", 4, email_stage="re_engagement")
    print(f"\n  Contact: {c['contact_name']} ({c['country']})")
    print(f"    scarcity_line: {psych.get('scarcity_line', 'N/A')}")
    print(f"    calibrated_q: {psych.get('calibrated_q', 'N/A')}")
    check("scarcity_line IS present for re_engagement", psych.get("scarcity_line") is not None)
    check("calibrated_q IS present for re_engagement", psych.get("calibrated_q") is not None)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 5: INTRO EMAILS — build_intro_email() produces clean output")
print("=" * 70)
BANNED_PHRASES = [
    "How do you", "What's your biggest", "What would make",  # calibrated questions
    "It seems like", "It sounds like", "It looks like",      # labels
    "You probably get", "heard it all before",                # accusation audit
    "rate round closes", "finalizing our", "Spots for new",  # scarcity
]
for c in CONTACTS:
    subject, body = build_intro_email(c, token="test123")
    print(f"\n  Contact: {c['contact_name']} ({c['country']})")
    print(f"    Subject: {subject}")
    full_text = subject + " " + body
    for phrase in BANNED_PHRASES:
        found = phrase.lower() in full_text.lower()
        check(f"No '{phrase}' in intro email", not found)

# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print(f"RESULTS: {PASS} passed, {FAIL} failed out of {PASS + FAIL} checks")
print("=" * 70)

if FAIL > 0:
    print("\nFAILURES DETECTED — psych staging is NOT clean.")
    sys.exit(1)
else:
    print("\nAll checks passed — psych staging is correctly enforced.")
    sys.exit(0)
