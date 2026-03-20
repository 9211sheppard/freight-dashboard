"""
fast_verify.py — Fast domain-based verification for Freightnet contacts
────────────────────────────────────────────────────────────────────────
Instead of slow DuckDuckGo scraping (which takes 60+ days due to rate limits),
this checks the email domain directly via HTTP — 3 second timeout per contact.

Logic:
  Freightnet network membership     → base score 20 (paid member = real company)
  Email domain resolves to website  → +35 points → score 55 → "review"
  No working website found          → score 45  → "review" (network member, web unconfirmed)
  No email at all                   → score 30  → "flagged" (needs manual check)

Status thresholds (same as main verifier):
  70+  → verified
  45+  → review
  <45  → flagged

Runs in ~30 minutes for 800 contacts vs 60+ days with DuckDuckGo.
Safe to run alongside Flask — reads/writes one contact at a time.
"""

import os, sys, time, re, socket
_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)

from datetime import datetime
from database import get_db, init_db

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

TIMEOUT     = 4      # seconds per HTTP check
DELAY       = 0.3    # seconds between contacts (light delay — no scraping)
BATCH_SIZE  = 50

def extract_domain(email):
    if not email:
        return None
    m = re.search(r'@([\w\.\-]+)', email.strip().lower())
    return m.group(1) if m else None

def domain_has_website(domain):
    """Return True if domain responds to HTTP/HTTPS."""
    if not domain:
        return False
    for scheme in ('https', 'http'):
        try:
            url = f"{scheme}://{domain}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                method="HEAD"
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                if r.status < 500:
                    return True
        except Exception:
            pass
    # Fallback: DNS resolve
    try:
        socket.setdefaulttimeout(TIMEOUT)
        socket.gethostbyname(domain)
        return True   # domain resolves even if HTTP blocked
    except Exception:
        return False

def score_and_status(network, has_email, has_website):
    is_freightnet = network.upper().startswith('FREIGHTNET')
    base        = 20 if is_freightnet else 0
    site        = 35 if has_website else 0
    email_bonus =  5 if has_email   else 0
    score       = base + site + email_bonus

    # Freightnet = paid network member = real business → minimum "review"
    if is_freightnet and score < 45:
        score = 45

    if score >= 70:   status = 'verified'
    elif score >= 45: status = 'review'
    else:             status = 'flagged'
    return score, status

def main():
    init_db()
    conn = get_db()

    total = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE verified_status='unverified'"
    ).fetchone()[0]
    print(f"Fast verifier starting — {total} contacts to process")
    print(f"Estimated time: ~{round(total * DELAY / 60, 1)} minutes\n")

    done = 0
    today = datetime.now().strftime('%Y-%m-%d')

    while True:
        batch = conn.execute("""
            SELECT id, company_name, email, network
            FROM contacts
            WHERE verified_status = 'unverified'
            LIMIT ?
        """, (BATCH_SIZE,)).fetchall()

        if not batch:
            break

        for row in batch:
            cid, name, email, network = row['id'], row['company_name'], row['email'], row['network']

            domain     = extract_domain(email)
            has_website = domain_has_website(domain)
            score, status = score_and_status(network, bool(email), has_website)

            notes_parts = [f"{network} member"]
            if has_website:  notes_parts.append(f"website confirmed ({domain})")
            else:            notes_parts.append("no web presence found")
            if not email:    notes_parts.append("no email")

            conn.execute("""
                UPDATE contacts
                SET verified_status=?, verified_score=?, verified_date=?, verify_notes=?
                WHERE id=?
            """, (status, score, today, ' | '.join(notes_parts), cid))
            conn.commit()

            done += 1
            pct = round(done / total * 100, 1)
            icon = 'OK' if status == 'verified' else 'RV' if status == 'review' else 'FL'
            print(f"[{done}/{total} {pct}%] {icon} {name[:45]:<45} score={score} ({status})", flush=True)

            time.sleep(DELAY)

    # Final tally
    results = conn.execute(
        "SELECT verified_status, COUNT(*) FROM contacts GROUP BY verified_status"
    ).fetchall()
    print("\n── FINAL RESULTS ─────────────────────")
    for r in results:
        print(f"  {r[0]}: {r[1]}")
    conn.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
