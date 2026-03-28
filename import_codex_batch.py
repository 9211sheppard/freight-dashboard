"""
Import and validate Codex-delivered CSV files into the contacts DB.
Enforces all scoring rules, MX checks, deduplication, and verification thresholds.
"""
import csv, os, sqlite3, re, sys, time
sys.path.insert(0, r"C:\Users\Owner\Desktop\claude code\contact-dashboard")
from mx_check import check_batch as mx_check_batch

DB_PATH = r"C:\Users\Owner\Desktop\claude code\contact-dashboard\data\contacts.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# Country name normalisation
COUNTRY_MAP = {
    "united states": "USA", "us": "USA", "u.s.a.": "USA", "u.s.": "USA",
    "united kingdom": "UK", "great britain": "UK",
    "united arab emirates": "UAE", "u.a.e.": "UAE", "u.a.e": "UAE",
    "turkiye": "Turkey", "türkiye": "Turkey",
    "republic of korea": "South Korea", "korea": "South Korea",
    "viet nam": "Vietnam",
    "russian federation": "Russia",
    # Hong Kong is always separate from China mainland
    "hong kong sar": "Hong Kong", "hong kong, china": "Hong Kong",
    "hongkong-china": "Hong Kong", "hong kong - china": "Hong Kong",
    "hong kong s.a.r.": "Hong Kong",
    # China mainland
    "china, mainland": "China", "mainland china": "China",
    "people's republic of china": "China",
    # Taiwan always separate
    "taiwan-china": "Taiwan", "taiwan, china": "Taiwan",
    "taiwan, province of china": "Taiwan",
    "chinese taipei": "Taiwan",
    # Macao
    "macao-china": "Macao", "macau": "Macao", "macao sar": "Macao",
}

def norm_country(c):
    return COUNTRY_MAP.get(c.strip().lower(), c.strip())

def score_row(email, phone, website, linkedin):
    s = 0
    if email and email.strip() and '@' in email: s += 35
    if phone and phone.strip(): s += 25
    if website and website.strip(): s += 15
    if linkedin and linkedin.strip(): s += 10
    return s

def clean_row(r, file_type):
    """Normalise a raw CSV row. Returns cleaned dict or None if row should be skipped."""
    name = r.get('company_name','').strip()
    if not name or len(name) < 3:
        return None

    email = r.get('email','').strip()
    # Drop masked emails (JCtrans format: jj******, ab*****)
    if email and ('*' in email or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', email)):
        email = ''

    phone = r.get('phone_number','').strip()
    # Basic phone sanity — must have at least 6 digits
    if phone and len(re.sub(r'[^0-9]','',phone)) < 6:
        phone = ''

    website = r.get('website_url','').strip()
    if website and not re.match(r'^https?://', website, re.I):
        website = ''

    contact_name = r.get('contact_name','').strip().lstrip('/')

    country = norm_country(r.get('country','').strip())
    city    = r.get('city','').strip()
    network = r.get('network','').strip()
    source  = r.get('source_url','').strip()
    services= r.get('services','').strip()

    return {
        'company_name':  name,
        'contact_name':  contact_name,
        'email':         email,
        'phone_number':  phone,
        'website_url':   website,
        'linkedin_url':  '',
        'country':       country,
        'city':          city,
        'network':       network,
        'source_url':    source,
        'services':      services,
    }


def import_file(csv_path, file_type):
    with open(csv_path, encoding='utf-8-sig') as f:
        raw_rows = list(csv.DictReader(f))

    print(f"\n{'='*60}")
    print(f"Importing: {csv_path}")
    print(f"Raw rows: {len(raw_rows)}")

    # 1. Clean all rows
    cleaned = [clean_row(r, file_type) for r in raw_rows]
    cleaned = [r for r in cleaned if r is not None]
    print(f"After cleaning: {len(cleaned)}")

    # 2. MX check all emails
    emails_to_check = [r['email'] for r in cleaned if r['email']]
    if emails_to_check:
        print(f"MX-checking {len(emails_to_check)} emails ({len(set(e.split('@')[-1] for e in emails_to_check))} unique domains)...")
        mx_results = mx_check_batch(emails_to_check, workers=30)
        mx_failed = 0
        for r in cleaned:
            if r['email'] and not mx_results.get(r['email'], True):
                r['verify_notes'] = f"MX FAIL: no MX record for {r['email']}"
                r['email'] = ''
                mx_failed += 1
        print(f"  MX failures cleared: {mx_failed}")
    else:
        mx_results = {}

    # 3. Score each row
    for r in cleaned:
        r['verified_score'] = score_row(r['email'], r['phone_number'], r['website_url'], r['linkedin_url'])
        r['verified_status'] = 'verified' if r['verified_score'] >= 50 else 'review'
        if 'verify_notes' not in r:
            r['verify_notes'] = ''

    # 4. Deduplicate within this batch (same name+country keep highest score)
    seen = {}
    for r in cleaned:
        key = (r['company_name'].lower().strip(), r['country'].lower().strip())
        if key not in seen or r['verified_score'] > seen[key]['verified_score']:
            seen[key] = r
    deduped = list(seen.values())
    print(f"After internal dedup: {len(deduped)} (removed {len(cleaned)-len(deduped)})")

    # 5. Check against blocklist + existing DB
    conn = get_conn()

    blocklist = conn.execute("SELECT match_type, LOWER(match_value) FROM contact_blocklist").fetchall()
    def is_blocked(r):
        name_l = r['company_name'].lower()
        email_l = r['email'].lower()
        for match_type, val in blocklist:
            if match_type == 'company_name_exact' and name_l == val:
                return True
            if match_type == 'company_name_contains' and val in name_l:
                return True
            if match_type == 'email_domain' and email_l.endswith('@' + val):
                return True
        return False

    before_block = len(deduped)
    deduped = [r for r in deduped if not is_blocked(r)]
    blocked_count = before_block - len(deduped)
    if blocked_count:
        print(f"Blocked (on blocklist): {blocked_count}")

    existing_names = set(
        r[0].lower().strip()+'|'+r[1].lower().strip()
        for r in conn.execute('SELECT company_name, country FROM contacts').fetchall()
    )
    existing_emails = set(
        r[0].lower().strip()
        for r in conn.execute('SELECT email FROM contacts WHERE email IS NOT NULL AND email!=""').fetchall()
    )

    new_rows = []
    skipped_dupe = 0
    for r in deduped:
        name_country_key = r['company_name'].lower().strip()+'|'+r['country'].lower().strip()
        email_key = r['email'].lower().strip() if r['email'] else None

        if name_country_key in existing_names:
            skipped_dupe += 1
            continue
        if email_key and email_key in existing_emails:
            skipped_dupe += 1
            continue
        new_rows.append(r)

    print(f"Skipped (already in DB): {skipped_dupe}")
    print(f"New rows to insert: {len(new_rows)}")

    # 6a. Insert new rows
    inserted = 0
    for r in new_rows:
        try:
            conn.execute("""
                INSERT INTO contacts
                    (network, company_name, contact_name, email, phone_number,
                     website_url, linkedin_url, country, city,
                     verified_score, verified_status, verify_notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r['network'], r['company_name'], r['contact_name'],
                r['email'], r['phone_number'], r['website_url'], r['linkedin_url'],
                r['country'], r['city'],
                r['verified_score'], r['verified_status'], r['verify_notes']
            ))
            inserted += 1
        except Exception:
            pass

    # 6b. Enrichment UPDATE — for files named *enriched*, patch email/website
    #     into existing contacts that currently have those fields empty.
    updated = 0
    is_enrichment = 'enrich' in os.path.basename(csv_path).lower()
    if is_enrichment:
        for r in deduped:
            if not r.get('email') and not r.get('website_url'):
                continue  # nothing new to patch
            new_score = score_row(r['email'], r['phone_number'], r['website_url'], r['linkedin_url'])
            try:
                conn.execute("""
                    UPDATE contacts SET
                        email       = CASE WHEN (email IS NULL OR email='')       AND ? != '' THEN ? ELSE email END,
                        website_url = CASE WHEN (website_url IS NULL OR website_url='') AND ? != '' THEN ? ELSE website_url END,
                        verified_score  = MAX(COALESCE(verified_score,0),
                            (CASE WHEN (email IS NULL OR email='')       AND ? != '' THEN 35 ELSE
                             CASE WHEN email IS NOT NULL AND email != '' THEN 35 ELSE 0 END END) +
                            (CASE WHEN phone_number IS NOT NULL AND phone_number != '' THEN 25 ELSE 0 END) +
                            (CASE WHEN (website_url IS NULL OR website_url='') AND ? != '' THEN 15 ELSE
                             CASE WHEN website_url IS NOT NULL AND website_url != '' THEN 15 ELSE 0 END END) +
                            (CASE WHEN linkedin_url IS NOT NULL AND linkedin_url != '' THEN 10 ELSE 0 END)
                        ),
                        verified_status = CASE WHEN MAX(COALESCE(verified_score,0), ?) >= 50
                                          THEN 'verified' ELSE verified_status END,
                        verify_notes = verify_notes || CASE WHEN ? != '' THEN ' | enriched: ' || ? ELSE '' END
                    WHERE LOWER(TRIM(company_name)) = LOWER(TRIM(?))
                      AND LOWER(TRIM(country))      = LOWER(TRIM(?))
                      AND COALESCE(verified_score,0) != 100
                """, (
                    r['email'], r['email'],
                    r['website_url'], r['website_url'],
                    r['email'], r['website_url'],
                    new_score,
                    r.get('enrichment_source',''), r.get('enrichment_source',''),
                    r['company_name'], r['country']
                ))
                if conn.execute('SELECT changes()').fetchone()[0] > 0:
                    updated += 1
            except Exception:
                pass
        if updated:
            print(f"Enrichment updates applied: {updated}")

    conn.commit()
    conn.close()

    # 7. Log + summary — separate connection with retry to avoid lock from Flask
    total = verified = review = 0
    for attempt in range(10):
        try:
            log_conn = get_conn()
            log_conn.execute("""INSERT OR REPLACE INTO imported_files
                (filename, imported_at, rows_inserted, rows_skipped, notes)
                VALUES (?, strftime('%s','now')*1000, ?, ?, ?)""",
                (os.path.basename(csv_path), inserted + updated, skipped_dupe,
                 f"{file_type} | enrichment_updates={updated}" if is_enrichment else file_type))
            total    = log_conn.execute('SELECT COUNT(*) FROM contacts').fetchone()[0]
            verified = log_conn.execute('SELECT COUNT(*) FROM contacts WHERE verified_status="verified"').fetchone()[0]
            review   = log_conn.execute('SELECT COUNT(*) FROM contacts WHERE verified_status="review"').fetchone()[0]
            log_conn.commit()
            log_conn.close()
            break
        except Exception as e:
            try:
                log_conn.close()
            except Exception:
                pass
            if attempt < 9:
                time.sleep(1)
            else:
                print(f"Warning: could not log to imported_files after 10 attempts: {e}")

    print(f"\nInserted: {inserted}")
    print(f"DB totals: {total} contacts | {verified} verified | {review} review")
    return inserted


def scan_and_import():
    """Scan codex_output folder and auto-import any new files not yet processed."""
    import os
    output_dir = r"C:\Users\Owner\Desktop\codex_output"
    if not os.path.exists(output_dir):
        print("codex_output folder not found")
        return

    conn = get_conn()
    already_done = set(r[0] for r in conn.execute('SELECT filename FROM imported_files').fetchall())
    conn.close()

    # Skip meta/log files Codex writes alongside data
    SKIP_FILES = {'run_errors.csv', 'run_summary.txt', 'run_log.csv',
                  'fmc_enriched_v2_errors.csv', 'run_errors.csv'}
    found = [f for f in os.listdir(output_dir)
             if f.endswith('.csv') and f not in already_done and f not in SKIP_FILES]

    if not found:
        print("No new files in codex_output.")
        return

    print(f"New files found: {found}")
    for fname in found:
        full_path = os.path.join(output_dir, fname)
        file_type = fname.replace('.csv','').replace('_enriched','').replace('_full','').replace('_directory','')
        import_file(full_path, file_type)


if __name__ == '__main__':
    import os
    scan_and_import()
