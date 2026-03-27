"""
enrich_review_websites.py
─────────────────────────
Scrapes contact pages of review-status companies that have a website but no email.
Extracts emails from the page HTML, validates MX, updates the DB.

Run: python enrich_review_websites.py
"""

import re
import sqlite3
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from mx_check import check_email_mx

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

DB_PATH = r"C:\Users\Owner\Desktop\claude code\contact-dashboard\data\contacts.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FreightDashboard/1.0; contact research)",
    "Accept": "text/html,application/xhtml+xml",
}
TIMEOUT = 10
RATE_LIMIT = 1.2  # seconds between requests per domain

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

# Email patterns to skip (generic catchalls, image artifacts, etc.)
BAD_EMAIL_PATTERNS = [
    r'@example\.', r'@test\.', r'noreply@', r'no-reply@',
    r'\.png$', r'\.jpg$', r'\.webp$', r'\.gif$', r'\.svg$',
    r'@sentry\.', r'@schema\.', r'@w3\.org', r'@jquery',
    r'@tracxn\.', r'@forwarderdata\.', r'@zoominfo\.',
    r'@apollo\.io', r'@hunter\.io', r'@crunchbase\.',
]
BAD_RE = re.compile('|'.join(BAD_EMAIL_PATTERNS), re.IGNORECASE)

# Sites that aggregate company data — don't trust emails found on these
AGGREGATOR_DOMAINS = {
    'tracxn.com', 'forwarderdata.com', 'zoominfo.com', 'dnb.com',
    'crunchbase.com', 'apollo.io', 'hunter.io', 'clearbit.com',
    'owler.com', 'manta.com', 'yelp.com', 'shipify.com',
}


def _is_good_email(email: str) -> bool:
    if BAD_RE.search(email):
        return False
    if len(email) > 80:
        return False
    return check_email_mx(email)


def _contact_urls(base_url: str) -> list[str]:
    """Generate candidate contact page URLs to try."""
    base = base_url.rstrip('/')
    return [
        base + '/contact',
        base + '/contact-us',
        base + '/about',
        base + '/about-us',
        base + '/team',
        base,  # homepage last
    ]


def _fetch(url: str) -> str | None:
    try:
        domain = urlparse(url).netloc.lower().replace('www.', '')
        if any(agg in domain for agg in AGGREGATOR_DOMAINS):
            return None  # never trust data aggregator pages
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        # Reject if redirected to an aggregator
        final_domain = urlparse(r.url).netloc.lower().replace('www.', '')
        if any(agg in final_domain for agg in AGGREGATOR_DOMAINS):
            return None
        if r.status_code == 200 and 'text/html' in r.headers.get('content-type', ''):
            return r.text
    except Exception:
        pass
    return None


def _extract_emails(html: str, company_domain: str) -> list[str]:
    """Extract emails from HTML, preferring same-domain emails."""
    soup = BeautifulSoup(html, 'html.parser')

    # Remove script/style noise
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    text = soup.get_text(separator=' ')

    # Also check mailto: links
    mailto_emails = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.startswith('mailto:'):
            email = href[7:].split('?')[0].strip()
            mailto_emails.append(email)

    all_found = EMAIL_RE.findall(text) + mailto_emails
    # Deduplicate, lowercase
    seen = set()
    unique = []
    for e in all_found:
        e = e.lower().strip()
        if e not in seen:
            seen.add(e)
            unique.append(e)

    # Prefer same-domain emails, then any valid email
    same_domain = [e for e in unique if company_domain in e]
    other = [e for e in unique if company_domain not in e]
    return same_domain + other


def enrich_one(contact_id: int, company_name: str, website_url: str) -> dict:
    domain = urlparse(website_url).netloc.lower().replace('www.', '')
    found_email = None
    source = None

    for url in _contact_urls(website_url):
        html = _fetch(url)
        if not html:
            time.sleep(0.3)
            continue
        emails = _extract_emails(html, domain)
        for email in emails:
            if _is_good_email(email):
                found_email = email
                source = url
                break
        if found_email:
            break
        time.sleep(RATE_LIMIT)

    return {
        'id': contact_id,
        'company_name': company_name,
        'email': found_email,
        'source': source,
    }


def run():
    conn = sqlite3.connect(DB_PATH)
    targets = conn.execute("""
        SELECT id, company_name, website_url
        FROM contacts
        WHERE verified_status='review'
          AND (website_url IS NOT NULL AND TRIM(website_url) != '')
          AND (email IS NULL OR TRIM(email) = '')
          AND COALESCE(verified_score, 0) != 100
        ORDER BY verified_score DESC
    """).fetchall()
    conn.close()

    log.info(f"Enriching {len(targets)} review contacts with websites but no email...")

    enriched = 0
    failed  = 0

    # Process with modest concurrency (respect rate limits)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(enrich_one, row[0], row[1], row[2]): row
            for row in targets
        }
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            name = result['company_name'][:40]
            if result['email']:
                log.info(f"  [{i}/{len(targets)}] FOUND  {name} -> {result['email']}")
                enriched += 1
            else:
                log.info(f"  [{i}/{len(targets)}] none   {name}")
                failed += 1

            # Write to DB after each find
            if result['email']:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("""
                    UPDATE contacts SET
                        email = ?,
                        verify_notes = COALESCE(verify_notes,'') || ' | email found via website scrape: ' || ?,
                        verified_score = (
                            35 +
                            CASE WHEN phone_number IS NOT NULL AND TRIM(phone_number)!='' THEN 25 ELSE 0 END +
                            CASE WHEN website_url  IS NOT NULL AND TRIM(website_url) !='' THEN 15 ELSE 0 END +
                            CASE WHEN linkedin_url IS NOT NULL AND TRIM(linkedin_url)!='' THEN 10 ELSE 0 END
                        ),
                        verified_status = CASE WHEN (
                            35 +
                            CASE WHEN phone_number IS NOT NULL AND TRIM(phone_number)!='' THEN 25 ELSE 0 END +
                            CASE WHEN website_url  IS NOT NULL AND TRIM(website_url) !='' THEN 15 ELSE 0 END +
                            CASE WHEN linkedin_url IS NOT NULL AND TRIM(linkedin_url)!='' THEN 10 ELSE 0 END
                        ) >= 50 THEN 'verified' ELSE 'review' END
                    WHERE id = ? AND COALESCE(verified_score,0) != 100
                """, (result['email'], result['source'] or 'website', result['id']))
                conn.commit()
                conn.close()

    log.info(f"\nDone. Found emails for {enriched}/{len(targets)} contacts.")
    log.info(f"Failed to find: {failed}")

    # Final DB stats
    conn = sqlite3.connect(DB_PATH)
    v = conn.execute('SELECT COUNT(*) FROM contacts WHERE verified_status="verified"').fetchone()[0]
    r = conn.execute('SELECT COUNT(*) FROM contacts WHERE verified_status="review"').fetchone()[0]
    conn.close()
    log.info(f"DB now: {v} verified | {r} review")


if __name__ == '__main__':
    run()
