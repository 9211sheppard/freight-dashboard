import csv
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


sys.stdout.reconfigure(encoding="utf-8", errors="replace")

INPUT_CSV = Path(r"C:\Users\Owner\Desktop\freightnet_global.csv")
DB_PATH = Path(r"C:\Users\Owner\Desktop\claude code\contact-dashboard\data\contacts.db")
PROGRESS_FILE = Path(r"C:\Users\Owner\Desktop\freightnet_website_email_progress.json")
DELAY_SECONDS = 1.5
REQUEST_TIMEOUT = 8
SAVE_EVERY = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
JUNK_PARTS = (
    "noreply",
    "no-reply",
    "@wix",
    "@sentry",
    "@google",
    "@facebook",
    "@microsoft",
    "example.com",
)
PREFERRED_PREFIXES = ("info@", "contact@", "sales@", "freight@")


def normalize_url(raw_url: str) -> str:
    raw_url = (raw_url or "").strip()
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.scheme:
        return raw_url
    return f"https://{raw_url}"


def is_junk_email(email: str) -> bool:
    lowered = email.lower()
    return any(part in lowered for part in JUNK_PARTS)


def pick_best_email(emails: list[str]) -> str:
    ranked = sorted({email.strip() for email in emails if email.strip()})
    for prefix in PREFERRED_PREFIXES:
        for email in ranked:
            if email.lower().startswith(prefix):
                return email
    return ranked[0] if ranked else ""


def candidate_urls(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    return [base_url.rstrip("/"), urljoin(root, "/contact"), urljoin(root, "/contact-us")]


def extract_emails_from_html(html: str, soup: BeautifulSoup) -> list[str]:
    found: set[str] = set()
    for anchor in soup.select("a[href^='mailto:']"):
        value = anchor["href"].replace("mailto:", "", 1).split("?", 1)[0].strip()
        if value and not is_junk_email(value):
            found.add(value)
    for email in EMAIL_RE.findall(html):
        if not is_junk_email(email):
            found.add(email)
    return sorted(found)


def fetch_emails(session: requests.Session, base_url: str) -> list[str]:
    all_found: list[str] = []
    seen_urls: set[str] = set()
    targets = candidate_urls(base_url)
    for index, target_url in enumerate(targets):
        if target_url in seen_urls:
            continue
        seen_urls.add(target_url)
        try:
            response = session.get(
                target_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            if response.status_code >= 400:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            for email in extract_emails_from_html(response.text, soup):
                if email not in all_found:
                    all_found.append(email)
        except requests.RequestException:
            pass
        finally:
            if index < len(targets) - 1:
                time.sleep(DELAY_SECONDS)
    return all_found


def load_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {"processed_keys": [], "visited": 0, "emails_found": 0, "rows_updated": 0}
    try:
        payload = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"processed_keys": [], "visited": 0, "emails_found": 0, "rows_updated": 0}
    if isinstance(payload, list):
        return {"processed_keys": payload, "visited": 0, "emails_found": 0, "rows_updated": 0}
    return {
        "processed_keys": payload.get("processed_keys", []),
        "visited": int(payload.get("visited", 0)),
        "emails_found": int(payload.get("emails_found", 0)),
        "rows_updated": int(payload.get("rows_updated", 0)),
    }


def save_progress(processed_keys: set[str], visited: int, emails_found: int, rows_updated: int) -> None:
    payload = {
        "processed_keys": sorted(processed_keys),
        "visited": visited,
        "emails_found": emails_found,
        "rows_updated": rows_updated,
    }
    PROGRESS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_rows() -> list[dict]:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("website_url") or "").strip()]


def row_key(row: dict) -> str:
    return "|".join(
        [
            (row.get("network") or "").strip(),
            (row.get("company_name") or "").strip(),
            normalize_url(row.get("website_url") or ""),
        ]
    )


def update_email(connection: sqlite3.Connection, email: str, company_name: str) -> int:
    cursor = connection.execute(
        """
        UPDATE contacts
        SET email = ?,
            verified_status = 'verified',
            verified_score = 90,
            verify_notes = coalesce(verify_notes, '') || ' | email scraped from website'
        WHERE network IN ('Freightnet-Air', 'Freightnet-FF')
          AND company_name = ?
          AND (email IS NULL OR email = '')
        """,
        (email, company_name),
    )
    return cursor.rowcount


def main() -> None:
    rows = load_rows()
    progress = load_progress()
    processed_keys = set(progress["processed_keys"])
    visited = progress["visited"]
    emails_found = progress["emails_found"]
    rows_updated = progress["rows_updated"]

    print(f"targets={len(rows)}")
    print(f"resume_processed={len(processed_keys)}")

    session = requests.Session()
    connection = sqlite3.connect(DB_PATH)
    processed_this_run = 0

    try:
        for index, row in enumerate(rows, start=1):
            key = row_key(row)
            if key in processed_keys:
                continue

            company_name = (row.get("company_name") or "").strip()
            website_url = normalize_url(row.get("website_url") or "")
            if not company_name or not website_url:
                processed_keys.add(key)
                continue

            print(f"[{index}/{len(rows)}] {company_name} | {website_url}")
            emails = fetch_emails(session, website_url)
            visited += 1
            processed_this_run += 1

            if emails:
                best_email = pick_best_email(emails)
                emails_found += 1
                updated = update_email(connection, best_email, company_name)
                if updated:
                    rows_updated += updated
                    connection.commit()
                    print(f"  email={best_email} updated_rows={updated}")
                else:
                    print(f"  email={best_email} matched_no_blank_rows")
            else:
                print("  email=not_found")

            processed_keys.add(key)

            if processed_this_run % SAVE_EVERY == 0:
                save_progress(processed_keys, visited, emails_found, rows_updated)
                print(
                    f"checkpoint visited={visited} emails_found={emails_found} rows_updated={rows_updated}"
                )

    finally:
        save_progress(processed_keys, visited, emails_found, rows_updated)
        connection.close()
        session.close()

    print(f"total visited / emails found / DB rows updated = {visited} / {emails_found} / {rows_updated}")


if __name__ == "__main__":
    main()
