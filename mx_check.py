"""
mx_check.py
───────────
Email domain validation — checks whether a domain is real and can receive mail.

Strategy (two-layer):
  1. dnspython MX lookup  — most accurate, catches no-MX domains
  2. socket A-record fallback — used when direct DNS port 53 is firewalled
     (e.g. sandboxed/cloud environments). A valid A record strongly implies
     the domain exists and likely accepts mail.

Only domains that fail BOTH checks are flagged as invalid.
This prevents false-positives from firewall/DNS restrictions.

Domain results are cached so each domain is only resolved once per session.

Usage:
    from mx_check import check_email_mx, check_batch

    ok = check_email_mx("sales@company.com")      # True / False
    results = check_batch(["a@x.com", "b@y.com"]) # {email: bool}

Standalone:
    python mx_check.py        # report only
    python mx_check.py fix    # report + clear invalid emails from DB
"""

import logging
import re
import socket
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    import dns.resolver
    import dns.exception
    _DNS_AVAILABLE = True
except ImportError:
    _DNS_AVAILABLE = False

log = logging.getLogger(__name__)

# ── Domain-level cache ────────────────────────────────────────────────────────
_mx_cache: dict[str, bool] = {}

# Always valid — skip lookup
_KNOWN_GOOD = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "protonmail.com", "msn.com", "ymail.com", "me.com",
}

# Obviously invalid — skip lookup
_KNOWN_BAD = {
    "2x.webp", "example.com", "test.com", "localhost", "nil", "none",
    "domain.com", "email.com", "noemail.com", "nodomain.com",
}

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$')


def _is_valid_format(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


def _mx_via_dnspython(domain: str, timeout: float = 4.0) -> bool | None:
    """Try MX lookup via dnspython. Returns True/False/None (None = DNS unreachable)."""
    if not _DNS_AVAILABLE:
        return None
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
        return len(answers) > 0
    except (getattr(dns.resolver, "NXDOMAIN", Exception),
            getattr(dns.resolver, "NoAnswer", Exception),
            getattr(dns.resolver, "NoNameservers", Exception)):
        return False  # domain definitively has no MX
    except Exception:
        return None   # timeout or network error — DNS may be firewalled


def _mx_via_socket(domain: str, timeout: float = 4.0) -> bool:
    """Fallback: check if domain resolves via OS resolver (A/AAAA record)."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None)
        return True
    except socket.gaierror:
        return False  # NXDOMAIN or genuinely unreachable
    except Exception:
        return True   # unknown error — assume valid to avoid false-positives


def _mx_for_domain(domain: str) -> bool:
    """
    Return True if the domain is real and likely accepts email.
    Uses dnspython first; falls back to socket if DNS port 53 is blocked.
    """
    domain = domain.strip().lower()

    if domain in _KNOWN_GOOD:
        return True
    if domain in _KNOWN_BAD:
        return False
    if domain in _mx_cache:
        return _mx_cache[domain]

    # Layer 1: dnspython MX
    mx_result = _mx_via_dnspython(domain)
    if mx_result is False:
        # Definitively no MX record (NXDOMAIN or NoAnswer)
        _mx_cache[domain] = False
        return False
    if mx_result is True:
        _mx_cache[domain] = True
        return True

    # Layer 2: socket fallback (DNS port 53 blocked / timeout)
    result = _mx_via_socket(domain)
    _mx_cache[domain] = result
    return result


def check_email_mx(email: str) -> bool:
    """
    Return True if the email address has valid format AND its domain has MX records.
    False if format is wrong OR domain has no MX.
    """
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    if not _is_valid_format(email):
        return False
    domain = email.split("@")[-1].lower()
    return _mx_for_domain(domain)


def check_batch(emails: list[str], workers: int = 30) -> dict[str, bool]:
    """
    Check a list of email addresses concurrently.
    Returns {email: True/False}.
    Deduplicates by domain so each domain is resolved only once.
    """
    results: dict[str, bool] = {}
    if not emails:
        return results

    # Group by domain to batch DNS calls
    domain_to_emails: dict[str, list[str]] = {}
    for email in emails:
        if not email or "@" not in email:
            results[email] = False
            continue
        domain = email.strip().lower().split("@")[-1]
        domain_to_emails.setdefault(domain, []).append(email)

    unique_domains = list(domain_to_emails.keys())
    domain_results: dict[str, bool] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_domain = {pool.submit(_mx_for_domain, d): d for d in unique_domains}
        for future in as_completed(future_to_domain):
            domain = future_to_domain[future]
            try:
                domain_results[domain] = future.result()
            except Exception:
                domain_results[domain] = False

    for domain, email_list in domain_to_emails.items():
        ok = domain_results.get(domain, False)
        for email in email_list:
            results[email] = ok

    return results


# ── Standalone DB run ─────────────────────────────────────────────────────────

def run_db_check(fix: bool = False) -> dict:
    """
    Check all emails in the contacts DB.
    If fix=True, clears emails with no MX record and recalculates scores.
    Returns summary stats.
    """
    from config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, email, company_name, network FROM contacts "
        "WHERE email IS NOT NULL AND email != ''"
    ).fetchall()

    emails = [r[1] for r in rows]
    print(f"Checking MX for {len(emails)} emails ({len(set(e.split('@')[-1] for e in emails if '@' in e))} unique domains)...")

    results = check_batch(emails, workers=30)

    invalid = [(r[0], r[1], r[2], r[3]) for r in rows if not results.get(r[1], True)]
    valid_count = len(emails) - len(invalid)

    print(f"  Valid MX:   {valid_count}")
    print(f"  No MX:      {len(invalid)}")

    if fix and invalid:
        today = datetime.now().strftime("%Y-%m-%d")
        for contact_id, email, company, network in invalid:
            conn.execute(
                "UPDATE contacts SET email='', verify_notes=?, verified_score=("
                "  CASE WHEN phone_number IS NOT NULL AND TRIM(phone_number)!='' THEN 25 ELSE 0 END +"
                "  CASE WHEN website_url  IS NOT NULL AND TRIM(website_url) !='' THEN 15 ELSE 0 END +"
                "  CASE WHEN linkedin_url IS NOT NULL AND TRIM(linkedin_url)!='' THEN 10 ELSE 0 END"
                ") WHERE id=? AND COALESCE(verified_score,0)!=100",
                (f"email cleared {today}: no MX record for domain ({email})", contact_id)
            )
        # Re-set verified_status for affected contacts
        conn.execute("""
            UPDATE contacts SET verified_status='review'
            WHERE id IN (
                SELECT id FROM contacts
                WHERE verify_notes LIKE '%no MX record%'
                  AND verified_score < 50
                  AND COALESCE(verified_score,0) != 100
            )
        """)
        conn.commit()
        print(f"  Fixed: cleared {len(invalid)} invalid emails, scores recalculated.")

    conn.close()
    return {"total": len(emails), "valid": valid_count, "invalid": len(invalid), "fixed": fix}


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    fix_mode = len(sys.argv) > 1 and sys.argv[1] == "fix"
    run_db_check(fix=fix_mode)
    if not fix_mode:
        print("\nRun  python mx_check.py fix  to clear invalid emails automatically.")
