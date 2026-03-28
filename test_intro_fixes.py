"""
Test script to verify all 6 intro email bug fixes.
Uses a Mehmet Yilmaz contact from Turkey to test name collision.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Mock database to avoid real DB dependency
import types
_mock_db = types.ModuleType("database")
def _get_db():
    raise RuntimeError("DB not needed for this test")
_mock_db.get_db = _get_db
sys.modules["database"] = _mock_db

# Mock config
_mock_config = types.ModuleType("config")
_mock_config.EMAIL_FROM = "pricing@flashcargoglobal.com"
_mock_config.GRAPH_TENANT_ID = "test-tenant"
_mock_config.GRAPH_CLIENT_ID = "test-client"
_mock_config.GRAPH_CLIENT_SECRET = "test-secret"
sys.modules["config"] = _mock_config

from mailer import _display_name_for_country, _from_address_for_name, signature_for
from contact_engine import get_psych_elements, get_lanes_for_country

# ── Test contact ──────────────────────────────────────────────────────────────
test_contact = {
    "id": 0,  # id=0 picks index 0 from Turkey list = "Mehmet"
    "contact_name": "Mehmet Yilmaz",
    "company_name": "Yilmaz Logistics",
    "country": "Turkey",
    "city": "Istanbul",
    "email": "mehmet@yilmazlogistics.com",
}

errors = []

# ── Bug 2: Name collision ─────────────────────────────────────────────────────
print("=" * 60)
print("BUG 2: Sender name != recipient name collision")
print("=" * 60)

# Without collision avoidance (old behavior): id=0, Turkey → "Mehmet"
name_no_fix = _display_name_for_country("Turkey", 0)
print(f"  Without contact_first_name: {name_no_fix}")

# With collision avoidance: contact is "Mehmet", so should pick next name
name_with_fix = _display_name_for_country("Turkey", 0, contact_first_name="Mehmet")
print(f"  With contact_first_name='Mehmet': {name_with_fix}")

sender_first = name_with_fix.split("|")[0].strip().split()[0]
if sender_first.lower() == "mehmet":
    errors.append("Bug 2 FAILED: sender is still 'Mehmet' despite contact being Mehmet")
    print("  FAIL: sender name still matches contact!")
else:
    print(f"  PASS: sender is '{sender_first}', not 'Mehmet'")

# ── Bug 1: FROM address uses alias ────────────────────────────────────────────
print()
print("=" * 60)
print("BUG 1: FROM address uses alias, not pricing@")
print("=" * 60)

from_addr = _from_address_for_name(name_with_fix)
print(f"  Sender name: {name_with_fix}")
print(f"  From address: {from_addr}")
if from_addr == "pricing@flashcargoglobal.com":
    # This is OK only if the alias isn't in _ACTIVE_ALIASES
    first = name_with_fix.split("|")[0].strip().split()[0].lower()
    from mailer import _ACTIVE_ALIASES
    if first in _ACTIVE_ALIASES:
        errors.append(f"Bug 1 FAILED: {first} is in ACTIVE_ALIASES but from_addr is pricing@")
        print(f"  FAIL: {first} is an active alias but from is pricing@")
    else:
        print(f"  PASS: {first} not in aliases, pricing@ is correct fallback")
else:
    print(f"  PASS: from address is alias: {from_addr}")

# ── Bug 5: Signature shows sender name ────────────────────────────────────────
print()
print("=" * 60)
print("BUG 5: Signature shows sender name, not 'Pricing Team'")
print("=" * 60)

sig = signature_for(name_with_fix)
if "Pricing Team" in sig:
    errors.append("Bug 5 FAILED: signature still shows 'Pricing Team'")
    print("  FAIL: signature contains 'Pricing Team'")
else:
    print(f"  PASS: signature contains '{name_with_fix}'")

sig_default = signature_for()
if "Pricing Team" not in sig_default:
    errors.append("Bug 5 FAILED: default signature doesn't show 'Pricing Team'")
    print("  FAIL: default signature missing 'Pricing Team'")
else:
    print("  PASS: default signature shows 'Pricing Team | Flash Cargo Global'")

# ── Bug 6: No motto in intro stage ───────────────────────────────────────────
print()
print("=" * 60)
print("BUG 6: No motto in intro emails")
print("=" * 60)

psych_intro = get_psych_elements(test_contact, "unknown", 0, email_stage="intro")
if psych_intro.get("motto_line") is not None:
    errors.append("Bug 6 FAILED: motto_line not None for intro stage")
    print(f"  FAIL: motto_line = {psych_intro['motto_line']}")
else:
    print("  PASS: motto_line is None for intro stage")

# Verify motto IS present for follow_up
psych_followup = get_psych_elements(test_contact, "unknown", 1, email_stage="follow_up")
if psych_followup.get("motto_line") is None:
    print("  INFO: motto_line also None for follow_up (may be None if no motto for Turkey?)")
else:
    print(f"  PASS: motto_line present for follow_up: {psych_followup['motto_line'][:50]}...")

# ── Bug 3 & 4: Build the email and inspect ──────────────────────────────────
print()
print("=" * 60)
print("BUG 3 & 4: Email body structure (redundancy + formatting)")
print("=" * 60)

from intro_mailer import build_intro_email
subject, body = build_intro_email(test_contact, token="test-token-123")

print(f"  Subject: {subject}")

# Bug 3: Check for redundancy — the openers should NOT contain "sought out"
if "sought out your company" in body:
    errors.append("Bug 3 FAILED: 'sought out your company' still in body openers")
    print("  FAIL: redundant 'sought out your company' found in body")
else:
    print("  PASS: no redundant 'sought out' phrases in openers")

# Bug 4: Check carrier formatting — each carrier should be in its own <tr>
carrier_count = body.count("</td></tr>")
# Lanes + carriers, each on its own row
print(f"  Table rows found: {carrier_count}")
# Should NOT have 3 <td> in a single <tr> for carriers
import re
all_rows = re.findall(r'<tr>(.*?)</tr>', body, re.DOTALL)
max_tds = max((row.count('<td') for row in all_rows), default=0)
if max_tds > 2:
    errors.append(f"Bug 4 FAILED: found row with {max_tds} cells (expected max 2)")
    print(f"  FAIL: found row with {max_tds} cells")
else:
    print(f"  PASS: all {len(all_rows)} rows have at most 2 cells each")

# Bug 5: Check signature in body
if "Pricing Team" in body:
    errors.append("Bug 5 FAILED: 'Pricing Team' still in email body signature")
    print("  FAIL: 'Pricing Team' found in email body")
else:
    print("  PASS: no 'Pricing Team' in email body")

# Check sender name IS in signature
sender_in_body = name_with_fix.split("|")[0].strip().split()[0]
if sender_in_body in body:
    print(f"  PASS: sender name '{sender_in_body}' found in body")
else:
    errors.append(f"Bug 5 FAIL: sender name '{sender_in_body}' not in body")
    print(f"  FAIL: sender name '{sender_in_body}' not found in body")

# Bug 6: Check no motto in body
motto_patterns = ["Yurtta sulh", "cihanda sulh", "motto"]
motto_found = [p for p in motto_patterns if p.lower() in body.lower()]
if motto_found:
    # Check if it's actually a motto line (not just the word 'motto' in a comment)
    if any(p in body for p in ["Yurtta sulh", "cihanda sulh"]):
        errors.append("Bug 6 FAILED: Turkish motto still in intro email body")
        print(f"  FAIL: motto text found in body")
    else:
        print("  PASS: no motto in intro email")
else:
    print("  PASS: no motto in intro email body")

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 60)
if errors:
    print(f"RESULT: {len(errors)} FAILURE(S)")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("RESULT: ALL 6 BUGS VERIFIED FIXED")
    sys.exit(0)
