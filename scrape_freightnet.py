# scrape_freightnet.py
# Visits every Freightnet member company website from the CSV,
# extracts emails, and saves results to a NEW comparison file.
# Output: freightnet_scraped_claude.csv on the Desktop
# Progress is saved every 10 rows so it can resume if interrupted.

import argparse
import csv
import json
import logging
import os
import re
import sys
from urllib.parse import urljoin

try:
    import requests
    from scrape_utils import (
        RateLimiter,
        ScrapeStats,
        extract_emails,
        get_proxy_session,
        is_allowed,
        is_blacklisted,
        load_proxies,
        random_headers,
        rotate_proxy,
        safe_get,
    )
except ImportError:
    print("\n[ERROR] Missing packages. Run this first:")
    print("  venv\\Scripts\\python.exe -m pip install requests beautifulsoup4\n")
    if sys.stdin.isatty():
        input("Press Enter to exit...")
    raise SystemExit(1)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

INPUT_CSV = r"C:\Users\Owner\Desktop\freightnet_contacts.csv"
OUTPUT_CSV = r"C:\Users\Owner\Desktop\freightnet_scraped_claude.csv"
PROGRESS_FILE = r"C:\Users\Owner\Desktop\freightnet_scrape_progress.json"
LOG_FILE = r"C:\Users\Owner\Desktop\scrape_freightnet.log"

DELAY_SECONDS = 2.0
TIMEOUT = 10
SAVE_EVERY = 10
ROTATE_PROXY_EVERY = 50
CONTACT_SUFFIXES = ["/contact", "/contact-us", "/contacts", "/about", "/about-us", "/kontakt"]


def parse_args():
    parser = argparse.ArgumentParser(description="Scrape Freightnet company websites for email addresses.")
    parser.add_argument("--dry-run", action="store_true", help="Check robots.txt access for target URLs without scraping.")
    parser.add_argument("--ignore-robots", action="store_true", help="Disable robots.txt checks (testing only).")
    return parser.parse_args()


def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )


def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f)


def save_results(out_fields, results):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(results)


def base_domain_from_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip(), flags=re.I).split("/")[0].lower()


def status_label(fetch_status: str) -> str:
    if fetch_status == "disallowed":
        return "robots denied"
    if fetch_status == "captcha":
        return "captcha"
    if fetch_status == "blocked":
        return "blocked"
    if fetch_status == "error":
        return "error"
    return "-- no email"


def maybe_rotate_session(session, proxies, request_count):
    if proxies and request_count and request_count % ROTATE_PROXY_EVERY == 0:
        rotate_proxy(session, proxies)
        session.headers.update(random_headers())


def dry_run(rows, ignore_robots):
    print("\n" + "=" * 55)
    print("  Freightnet Email Scraper - Dry Run")
    print("=" * 55)

    if ignore_robots:
        print("  --ignore-robots supplied; all URLs would be treated as allowed.")

    targets = set()
    skipped_blacklist = 0
    skipped_no_site = 0

    for row in rows:
        company = (row.get("company_name") or "").strip()
        website_url = (row.get("website_url") or "").strip()
        if is_blacklisted(company):
            skipped_blacklist += 1
            continue
        if not website_url:
            skipped_no_site += 1
            continue

        homepage = website_url.rstrip("/")
        targets.add(homepage)
        for suffix in CONTACT_SUFFIXES:
            targets.add(urljoin(homepage + "/", suffix.lstrip("/")))

    allowed = 0
    denied = 0
    for url in sorted(targets):
        permitted = True if ignore_robots else is_allowed(url)
        if permitted:
            allowed += 1
        else:
            denied += 1

    print(f"  URL targets    : {len(targets)}")
    print(f"  Allowed        : {allowed}")
    print(f"  Denied         : {denied}")
    print(f"  Blacklisted    : {skipped_blacklist}")
    print(f"  No website     : {skipped_no_site}")
    print(f"  Log file       : {LOG_FILE}")
    print("=" * 55 + "\n")


def load_input_rows():
    if not os.path.exists(INPUT_CSV):
        message = f"[ERROR] Input CSV not found: {INPUT_CSV}"
        print(message)
        logging.error(message)
        return None, []

    with open(INPUT_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    return rows, fieldnames


def main():
    args = parse_args()
    setup_logging()
    logging.info("Starting Freightnet scraper dry_run=%s ignore_robots=%s", args.dry_run, args.ignore_robots)

    rows, fieldnames = load_input_rows()
    if rows is None:
        raise SystemExit(1)

    if args.dry_run:
        dry_run(rows, args.ignore_robots)
        return

    print("\n" + "=" * 55)
    print("  Freightnet Email Scraper - Claude Edition")
    print("=" * 55)

    total = len(rows)
    print(f"  Loaded {total} contacts from CSV")

    out_fields = list(fieldnames)
    if "emails_found" not in out_fields:
        out_fields.append("emails_found")

    progress = load_progress()
    already_done = len(progress)
    print(f"  Already scraped: {already_done} (resuming...)" if already_done else "  Starting fresh...")
    print(f"  Estimated time: ~{int(max(total - already_done, 0) * DELAY_SECONDS // 60)} minutes")
    print(f"  Output file: {OUTPUT_CSV}")
    print("  Press Ctrl+C at any time - progress is saved!\n")

    proxies = load_proxies()
    if proxies:
        print(f"  Proxies loaded : {len(proxies)}")
    logging.info("Loaded %s proxies", len(proxies))

    results = []
    session = get_proxy_session(proxies)
    session.headers.update(random_headers())
    rate_limiter = RateLimiter(default_delay=DELAY_SECONDS)
    stats = ScrapeStats()

    found_count = 0
    error_count = 0
    request_count = 0

    try:
        for i, row in enumerate(rows, 1):
            company = (row.get("company_name") or "").strip()
            website_url = (row.get("website_url") or "").strip()
            profile_url = (row.get("member_profile_url") or "").strip()
            cache_key = website_url or profile_url

            if is_blacklisted(company):
                row["emails_found"] = ""
                results.append(row)
                continue

            if cache_key in progress:
                row["emails_found"] = progress[cache_key]
                results.append(row)
                if progress[cache_key]:
                    found_count += 1
                continue

            if not website_url:
                row["emails_found"] = ""
                results.append(row)
                progress[cache_key] = ""
                continue

            emails = []
            status = "-- no email"
            base_domain = base_domain_from_url(website_url)

            for candidate_url in [website_url] + [urljoin(website_url.rstrip("/") + "/", suffix.lstrip("/")) for suffix in CONTACT_SUFFIXES]:
                maybe_rotate_session(session, proxies, request_count)
                rate_limiter.wait(candidate_url)
                resp, fetch_status = safe_get(
                    session,
                    candidate_url,
                    timeout=TIMEOUT,
                    max_retries=3,
                    base_delay=DELAY_SECONDS,
                    respect_robots=not args.ignore_robots,
                    proxies=proxies,
                    stats=stats,
                    pre_waited=True,
                )
                request_count += 1

                if fetch_status != "ok":
                    status = status_label(fetch_status)
                    if fetch_status in {"disallowed", "captcha", "blocked"}:
                        break
                    continue

                emails = extract_emails(resp.text, base_domain)
                if emails:
                    status = f"+ {emails[0][:40]}"
                    break

            email_str = "; ".join(emails)
            row["emails_found"] = email_str
            progress[cache_key] = email_str
            if emails:
                found_count += 1
            elif status in {"error", "blocked", "captcha"}:
                error_count += 1

            results.append(row)

            pct = int(i / max(total, 1) * 40)
            bar = "#" * pct + "-" * (40 - pct)
            print(
                f"\r  [{bar}] {i}/{total}  Found: {found_count}  | {company[:25]:<25} {status:<45}",
                end="",
                flush=True,
            )

            if i % SAVE_EVERY == 0:
                save_progress(progress)
                save_results(out_fields, results)

    except KeyboardInterrupt:
        print("\n\n  Interrupted - saving progress...")
        logging.warning("Freightnet scraper interrupted by user")
    finally:
        save_progress(progress)
        save_results(out_fields, results)

    print(f"\n\n{'=' * 55}")
    print("  DONE!")
    print(f"  Total contacts : {total}")
    print(f"  Emails found   : {found_count}")
    print(f"  Errors         : {error_count}")
    print(f"  Success rate   : {found_count / max(total, 1) * 100:.1f}%")
    print(f"  Output saved to: {OUTPUT_CSV}")
    print(f"  Log file       : {LOG_FILE}")
    stats.print_summary()
    print(f"{'=' * 55}\n")

    logging.info("Freightnet scraper finished: found=%s errors=%s total=%s", found_count, error_count, total)
    if sys.stdin.isatty():
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
