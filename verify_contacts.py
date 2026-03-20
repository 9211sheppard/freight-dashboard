"""
verify_contacts.py — Automated contact verifier
────────────────────────────────────────────────
Searches DuckDuckGo for every company in the database and checks:
  1. Does a matching company website exist?
  2. Does a LinkedIn company page exist?
  3. Are they IATA-accredited? (air/freight networks only)

Scoring (0–100):
  WFA / WWPC / FIATA membership   → +30  (paid/vetted network)
  Freightnet membership           → +20
  Matching website found          → +35
  LinkedIn company page found     → +25
  IATA accreditation confirmed    → +10

Status thresholds:
  70–100  →  ✅  Verified
  45–69   →  ⚠️  Needs Review
   0–44   →  ❌  Flagged

Progress is saved after every single contact — safe to Ctrl+C and resume.

Usage:
  run_verify.bat              ← easiest way
  venv\\Scripts\\python verify_contacts.py            ← resume from where stopped
  venv\\Scripts\\python verify_contacts.py --reset    ← start fresh, re-verify all
"""

import os
import re
import sys
import time
import random
from datetime import datetime

# ── Path setup (must be before local imports) ──────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(_HERE)
sys.path.insert(0, _HERE)

from database import get_db, init_db

# ── Settings ───────────────────────────────────────────────────────────────
DELAY_MIN       = 2.2    # minimum seconds between DDG requests
DELAY_MAX       = 3.8    # maximum seconds (random jitter avoids rate limits)
IATA_DELAY_MIN  = 1.0
IATA_DELAY_MAX  = 2.0
BATCH_SIZE      = 50     # contacts pulled from DB per loop iteration
REQUEST_TIMEOUT = 14     # HTTP timeout in seconds

NETWORK_BASE = {
    'WFA':            30,
    'WWPC':           30,
    'FIATA':          30,
    'FREIGHTNET-FF':  20,
    'FREIGHTNET-AIR': 20,
}

IATA_NETWORKS = {'WFA', 'WWPC', 'FIATA', 'FREIGHTNET-AIR'}

FREIGHT_KW = {
    'freight', 'logistics', 'forwarding', 'shipping', 'cargo',
    'transport', 'customs', 'courier', 'supply chain', 'warehousing',
    'air freight', 'sea freight', 'import', 'export',
}

STOP_WORDS = {
    'the','a','an','and','or','of','for','in','at','by',
    'ltd','llc','inc','co','corp','srl','gmbh','bv','sa',
    'spa','nv','ag','pty','plc','group','international',
    'global','logistics','freight','forwarding','shipping',
    'cargo','transport',
}

SKIP_DOMAINS = {
    'linkedin','facebook','instagram','twitter','x.com',
    'yellowpages','yelp','dnb','crunchbase','bloomberg',
    'zoominfo','glassdoor','wikipedia','wikidata',
    'kompass','opencorporates','companieshouse','trustpilot',
    'algeriayp','freightcue','wfalliance','cargo-partner-finder',
    'europages','business.site','manta','cylex','hotfrog','chamberofcommerce',
    'bizapedia','opencorp','dun','hoovers','corporationwiki','bizstanding',
}

# ── DB migration ────────────────────────────────────────────────────────────
def _migrate():
    conn = get_db()
    existing = {r[1] for r in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    for col, defn in [
        ("verified_status", "TEXT    DEFAULT 'unverified'"),
        ("verified_score",  "INTEGER DEFAULT 0"),
        ("verified_date",   "TEXT    DEFAULT ''"),
        ("website_url",     "TEXT    DEFAULT ''"),
        ("linkedin_url",    "TEXT    DEFAULT ''"),
        ("verify_notes",    "TEXT    DEFAULT ''"),
    ]:
        if col not in existing:
            conn.execute(f"ALTER TABLE contacts ADD COLUMN {col} {defn}")
    conn.commit()
    conn.close()


# ── DuckDuckGo search ────────────────────────────────────────────────────────
def _search(query, max_results=7):
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        return []


# ── Name token matching ──────────────────────────────────────────────────────
def _tokens(name):
    words = set(re.findall(r'[a-z]+', name.lower()))
    clean = words - STOP_WORDS
    return clean if clean else words


def _match_ratio(company, text):
    """0.0–1.0: fraction of company name tokens found in text."""
    tok = _tokens(company)
    if not tok:
        return 0.0
    tl = text.lower()
    return sum(1 for t in tok if t in tl) / len(tok)


# ── Analyse search results ────────────────────────────────────────────────────
def _analyse(company, results):
    """
    Returns (website_url, website_found, linkedin_url, linkedin_found)
    """
    w_url, w_found = '', False
    li_url, li_found = '', False

    for r in results:
        href  = r.get('href', '')
        title = r.get('title', '')
        body  = r.get('body', '')
        blob  = f"{title} {body} {href}".lower()
        score = _match_ratio(company, blob)
        frt   = any(k in blob for k in FREIGHT_KW)

        # LinkedIn
        if 'linkedin.com/company' in href.lower() and not li_found:
            if score >= 0.4:
                li_url, li_found = href, True
            continue

        # Company website
        if not w_found:
            if any(d in href.lower() for d in SKIP_DOMAINS):
                continue
            if (score >= 0.45 and frt) or score >= 0.65:
                w_url, w_found = href, True

    return w_url, w_found, li_url, li_found


# ── IATA directory check ──────────────────────────────────────────────────────
def _iata(company):
    try:
        import requests as _req
        q = _req.utils.quote(company)
        r = _req.get(
            f"https://www.iata.org/en/publications/directories/cargolink/directory/?q={q}",
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
            timeout=REQUEST_TIMEOUT,
        )
        return _match_ratio(company, r.text) >= 0.6
    except Exception:
        return False


# ── Score & status ────────────────────────────────────────────────────────────
def _calc(network, w_found, li_found, iata_found):
    base  = NETWORK_BASE.get(network.upper(), 10)
    total = min(base + (35 if w_found else 0) + (25 if li_found else 0) + (10 if iata_found else 0), 100)
    notes = []
    if network:    notes.append(f'{network} member')
    if w_found:    notes.append('website found')
    if li_found:   notes.append('LinkedIn found')
    if iata_found: notes.append('IATA accredited')
    return total, ', '.join(notes)


def _status(score):
    if score >= 70: return 'verified'
    if score >= 45: return 'review'
    return 'flagged'


# ── Main loop ──────────────────────────────────────────────────────────────────
def verify_all(resume=True):
    init_db()
    _migrate()

    conn = get_db()
    if not resume:
        conn.execute(
            "UPDATE contacts SET verified_status='unverified', verified_score=0, "
            "verified_date='', website_url='', linkedin_url='', verify_notes=''"
        )
        conn.commit()

    pending   = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE verified_status='unverified'"
    ).fetchone()[0]
    total_all = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    conn.close()

    already = total_all - pending

    if pending == 0:
        print("\n  All contacts are already verified.")
        print("  Run with  --reset  to re-verify everything from scratch.\n")
        return

    est = round(pending * 3.2 / 60)
    print(f"\n{'='*62}")
    print(f"  Automated Contact Verifier")
    print(f"  {pending:,} contacts to process   ({already:,} already done)")
    print(f"  Estimated time: ~{est} minutes")
    print(f"  Ctrl+C stops safely - progress is saved after every contact")
    print(f"{'='*62}\n")

    done  = 0
    stats = {'verified': 0, 'review': 0, 'flagged': 0}

    try:
        while True:
            conn  = get_db()
            batch = conn.execute(
                "SELECT id, company_name, country, network FROM contacts "
                "WHERE verified_status='unverified' LIMIT ?",
                (BATCH_SIZE,),
            ).fetchall()
            conn.close()

            if not batch:
                break

            for row in batch:
                cid     = row['id']
                company = (row['company_name'] or '').strip()
                country = (row['country']      or '').strip()
                network = (row['network']      or '').strip()

                done += 1
                total_so_far = already + done
                pct = round(total_so_far / total_all * 100)

                print(f"  [{total_so_far}/{total_all}] ({pct}%)  "
                      f"{company[:50]:<50}  {country}")

                if not company:
                    _save(cid, 'flagged', 0, '', '', 'No company name')
                    stats['flagged'] += 1
                    continue

                # ── Main search ───────────────────────────────────────────────
                results = _search(f"{company} {country} freight forwarding logistics")
                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

                w_url, w_found, li_url, li_found = _analyse(company, results)

                # ── IATA check (only for relevant networks) ────────────────────
                iata = False
                if network.upper() in IATA_NETWORKS:
                    iata = _iata(company)
                    time.sleep(random.uniform(IATA_DELAY_MIN, IATA_DELAY_MAX))

                score, notes = _calc(network, w_found, li_found, iata)
                status = _status(score)
                stats[status] += 1

                icon = {'verified': '[OK]', 'review': '[??]', 'flagged': '[--]'}[status]
                print(f"          {icon}  {score}/100  -  "
                      f"{notes if notes else 'no matches found'}")

                _save(cid, status, score, w_url, li_url, notes)

    except KeyboardInterrupt:
        print("\n\n  Stopped by user — progress saved.\n")

    total_done = already + done
    print(f"\n{'='*62}")
    print(f"  Session complete — {done:,} contacts processed this run")
    print(f"  Total verified so far: {total_done:,} / {total_all:,}")
    print(f"  [OK] Verified:      {stats['verified']:,}")
    print(f"  [??] Needs review: {stats['review']:,}")
    print(f"  [--] Flagged:       {stats['flagged']:,}")
    print(f"{'='*62}\n")


def _save(cid, status, score, w_url, li_url, notes):
    conn = get_db()
    conn.execute(
        """UPDATE contacts SET
               verified_status = ?,
               verified_score  = ?,
               verified_date   = ?,
               website_url     = ?,
               linkedin_url    = ?,
               verify_notes    = ?
           WHERE id = ?""",
        (status, score,
         datetime.now().strftime('%Y-%m-%d'),
         w_url, li_url, notes, cid),
    )
    conn.commit()
    conn.close()


if __name__ == '__main__':
    verify_all(resume='--reset' not in sys.argv)
