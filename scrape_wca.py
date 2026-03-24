# scrape_wca.py
# Scrapes WCA World member directory for Italy, Spain, India, Vietnam,
# Pakistan, United Kingdom, and United States.
# Step 1: Collects all member profile URLs per country.
# Step 2: Visits each profile for company details.
# Step 3: Visits each company website to find email.
# Output: wca_scraped.csv on Desktop

import argparse
import csv
import json
import logging
import os
import random
import re
import sys

try:
    import requests
    from bs4 import BeautifulSoup
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
    from scrape_utils import (
        RateLimiter,
        ScrapeStats,
        extract_emails,
        get_proxy_session,
        is_allowed,
        is_blacklisted,
        load_proxies,
        random_headers,
        random_ua,
        rotate_proxy,
        safe_get,
    )
except ImportError as exc:
    print(f"\n[ERROR] Missing package: {exc}")
    print("Run: venv\\Scripts\\python.exe -m pip install playwright requests beautifulsoup4")
    print("Then: venv\\Scripts\\python.exe -m playwright install chromium\n")
    if sys.stdin.isatty():
        input("Press Enter to exit...")
    raise SystemExit(1)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_CSV = r"C:\Users\Owner\Desktop\wca_scraped.csv"
PROGRESS_FILE = r"C:\Users\Owner\Desktop\wca_scrape_progress.json"
LOG_FILE = r"C:\Users\Owner\Desktop\scrape_wca.log"

PROFILE_DELAY = 1.5
DIRECTORY_DELAY = 1.0
TIMEOUT = 10
SAVE_EVERY = 10
ROTATE_CONTEXT_EVERY = 50
CONTACT_SUFFIXES = ["/contact", "/contact-us", "/contatti", "/contacto"]

COUNTRIES = {
    "Italy": "IT",
    "Spain": "ES",
    "India": "IN",
    "Vietnam": "VN",
    "Pakistan": "PK",
    "United Kingdom": "GB",
    "United States": "US",
}

BASE_DIR_URL = (
    "https://www.wcaworld.com/Directory"
    "?searchby=CountryCode&country={code}"
    "&pageIndex={page}&pageSize=100&orderby=MembershipYears"
)

FIELDS = ["network", "company_name", "city", "country", "office_type", "address", "phone", "website_url", "email", "wca_id", "wca_profile_url"]


def parse_args():
    parser = argparse.ArgumentParser(description="Scrape WCA World directory and company website emails.")
    parser.add_argument("--dry-run", action="store_true", help="Check robots.txt access for known WCA URLs without scraping.")
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


def clean(value):
    return str(value).strip() if value else ""


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("results", {})
            data.setdefault("scraped_ids", [])
            data.setdefault("all_profiles", [])
            return data
    return {"results": {}, "scraped_ids": [], "all_profiles": []}


def save_progress(progress):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def write_csv(rows):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def base_domain_from_url(url):
    return re.sub(r"^https?://(www\.)?", "", url.strip(), flags=re.I).split("/")[0].lower()


def open_context(browser, proxies):
    ua = random_ua()
    context_kwargs = {
        "user_agent": ua,
        "locale": "en-US",
    }
    proxy_server = ""
    if proxies:
        proxy = random.choice(proxies)
        proxy_server = proxy["server"]
        context_kwargs["proxy"] = {"server": proxy_server}
    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.set_default_timeout(30000)
    logging.info("Opened Playwright context ua=%s proxy=%s", ua, proxy_server or "none")
    return context, page


def rotate_context(browser, current_context, proxies):
    if current_context is not None:
        current_context.close()
    return open_context(browser, proxies)


def goto_with_retry(page, url, logger, timeout=30000):
    for attempt in range(2):
        try:
            logger.info("Playwright goto %s attempt=%s", url, attempt + 1)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except PlaywrightTimeoutError:
                logger.info("networkidle timeout on %s; continuing with loaded DOM", url)
            return True
        except PlaywrightTimeoutError as exc:
            logger.warning("Timeout on %s attempt=%s error=%s", url, attempt + 1, exc)
            if attempt == 0:
                continue
            return False
    return False


def status_label(fetch_status):
    if fetch_status == "disallowed":
        return "robots denied"
    if fetch_status == "captcha":
        return "captcha"
    if fetch_status == "blocked":
        return "blocked"
    if fetch_status == "error":
        return "error"
    return "no email"


def dry_run(progress, ignore_robots):
    print("\n" + "=" * 60)
    print("  WCA World Scraper - Dry Run")
    print("=" * 60)

    urls = set()
    for code in COUNTRIES.values():
        urls.add(BASE_DIR_URL.format(code=code, page=1))

    cached_profiles = progress.get("all_profiles", [])
    cached_results = progress.get("results", {})

    for profile in cached_profiles:
        url = clean(profile.get("wca_profile_url"))
        if url:
            urls.add(url)

    for row in cached_results.values():
        website_url = clean(row.get("website_url"))
        if website_url:
            urls.add(website_url)

    allowed = 0
    denied = 0
    for url in sorted(urls):
        permitted = True if ignore_robots else is_allowed(url)
        if permitted:
            allowed += 1
        else:
            denied += 1

    print(f"  Known URLs     : {len(urls)}")
    print(f"  Allowed        : {allowed}")
    print(f"  Denied         : {denied}")
    if not cached_profiles:
        print("  Note           : profile URL dry-run coverage increases after the first cached discovery pass.")
    print(f"  Log file       : {LOG_FILE}")
    print("=" * 60 + "\n")


def main():
    args = parse_args()
    setup_logging()
    logging.info("Starting WCA scraper dry_run=%s ignore_robots=%s", args.dry_run, args.ignore_robots)

    progress = load_progress()
    if args.dry_run:
        dry_run(progress, args.ignore_robots)
        return

    results_dict = progress.get("results", {})
    scraped_ids = set(progress.get("scraped_ids", []))
    all_profiles = progress.get("all_profiles", [])

    print("\n" + "=" * 60)
    print("  WCA World Scraper - IT / ES / IN / VN / PK / GB / US")
    print("=" * 60)
    print(f"  Output    : {OUTPUT_CSV}")
    print(f"  Already done: {len(scraped_ids)} profiles")
    print("  Press Ctrl+C anytime - progress saves every 10 rows!")
    print("=" * 60 + "\n")

    proxies = load_proxies()
    logging.info("Loaded %s proxies", len(proxies))

    session = get_proxy_session(proxies)
    session.headers.update(random_headers())
    stats = ScrapeStats()
    directory_limiter = RateLimiter(default_delay=DIRECTORY_DELAY)
    profile_limiter = RateLimiter(default_delay=PROFILE_DELAY)
    website_limiter = RateLimiter(default_delay=PROFILE_DELAY)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = None
        page = None
        profiles_since_rotation = 0

        try:
            context, page = open_context(browser, proxies)

            if not all_profiles:
                print("  [Step 1] Discovering all member profiles...")

                for country_name, code in COUNTRIES.items():
                    print(f"\n  Scanning {country_name} (code={code})...")
                    page_idx = 1
                    country_total = 0

                    while True:
                        url = BASE_DIR_URL.format(code=code, page=page_idx)
                        if not args.ignore_robots and not is_allowed(url):
                            stats.record("disallowed")
                            print(f"    Page {page_idx}: robots denied")
                            logging.warning("Robots denied %s", url)
                            break

                        directory_limiter.wait(url)
                        ok = goto_with_retry(page, url, logging)
                        if not ok:
                            stats.record("error")
                            print(f"    Page {page_idx} error: timeout")
                            break

                        stats.record("ok")
                        html = page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        links = soup.find_all("a", href=re.compile(r"/directory/members/\d+", re.I))

                        if not links:
                            break

                        seen_this_page = set()
                        new_this_page = 0
                        for a in links:
                            href = a.get("href", "")
                            match = re.search(r"/directory/members/(\d+)", href, re.I)
                            if not match:
                                continue
                            wca_id = match.group(1)
                            if wca_id in seen_this_page:
                                continue
                            seen_this_page.add(wca_id)
                            all_profiles.append(
                                {
                                    "wca_id": wca_id,
                                    "wca_profile_url": f"https://www.wcaworld.com{href}",
                                    "country": country_name,
                                    "company_name": clean(a.get_text()),
                                }
                            )
                            new_this_page += 1
                            country_total += 1

                        print(f"    Page {page_idx}: {new_this_page} profiles found  (total {country_total})")

                        if new_this_page < 10:
                            break
                        page_idx += 1

                seen_profiles = set()
                deduped = []
                for profile in all_profiles:
                    if profile["wca_id"] in seen_profiles:
                        continue
                    seen_profiles.add(profile["wca_id"])
                    deduped.append(profile)
                all_profiles = [profile for profile in deduped if not is_blacklisted(profile.get("company_name", ""))]

                progress["all_profiles"] = all_profiles
                progress["results"] = results_dict
                progress["scraped_ids"] = list(scraped_ids)
                save_progress(progress)
                print(f"\n  Total unique profiles (after blacklist): {len(all_profiles)}")
            else:
                print(f"  [Step 1] Using {len(all_profiles)} cached profiles.")

            if all_profiles:
                filtered_profiles = [profile for profile in all_profiles if not is_blacklisted(profile.get("company_name", ""))]
                if len(filtered_profiles) != len(all_profiles):
                    all_profiles = filtered_profiles
                    progress["all_profiles"] = all_profiles
                    save_progress(progress)

            total = len(all_profiles)
            done_count = len(scraped_ids)
            found_emails = sum(1 for row in results_dict.values() if row.get("email"))

            print(f"\n  [Step 2+3] Scraping profiles and company websites...")
            print(f"  Remaining: {total - done_count} of {total}\n")

            for profile in all_profiles:
                wca_id = profile["wca_id"]
                if wca_id in scraped_ids:
                    continue

                if profiles_since_rotation and profiles_since_rotation % ROTATE_CONTEXT_EVERY == 0:
                    context, page = rotate_context(browser, context, proxies)
                    rotate_proxy(session, proxies)
                    session.headers.update(random_headers())

                company = clean(profile.get("company_name"))
                country = clean(profile.get("country"))
                url = profile["wca_profile_url"]

                row = {field: "" for field in FIELDS}
                row.update(
                    {
                        "network": "WCA",
                        "company_name": company,
                        "country": country,
                        "wca_id": wca_id,
                        "wca_profile_url": url,
                    }
                )

                profile_status = "no email"
                if not args.ignore_robots and not is_allowed(url):
                    stats.record("disallowed")
                    profile_status = "robots denied"
                    logging.warning("Robots denied profile %s", url)
                else:
                    profile_limiter.wait(url)
                    if goto_with_retry(page, url, logging, timeout=20000):
                        stats.record("ok")
                        html = page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        text = soup.get_text(separator="\n")

                        city_match = re.search(r"\(([^,)]+),\s*(Head Office|Branch Office)\)", text)
                        if city_match:
                            row["city"] = city_match.group(1).strip()
                            row["office_type"] = city_match.group(2).strip()

                        addr_match = re.search(r"Address:\s*\n([\s\S]{5,200}?)(?:\n\s*\n|\nContact|\nPhone|\nFax)", text)
                        if addr_match:
                            row["address"] = " ".join(addr_match.group(1).split())

                        phone_match = re.search(r"Phone:\s*\n(.+)", text)
                        if phone_match:
                            phone_value = phone_match.group(1).strip()
                            if "members only" not in phone_value.lower() and phone_value.lower() != "(n/a)":
                                row["phone"] = phone_value

                        for a in soup.find_all("a", href=True):
                            href = clean(a.get("href"))
                            if href.startswith("http") and "wcaworld.com" not in href.lower() and "javascript" not in href.lower() and len(href) > 10:
                                row["website_url"] = href
                                break
                    else:
                        stats.record("error")
                        profile_status = "profile timeout"

                if row["website_url"]:
                    base_domain = base_domain_from_url(row["website_url"])
                    candidate_urls = [row["website_url"]] + [f"{row['website_url'].rstrip('/')}{suffix}" for suffix in CONTACT_SUFFIXES]
                    for candidate_url in candidate_urls:
                        website_limiter.wait(candidate_url)
                        resp, fetch_status = safe_get(
                            session,
                            candidate_url,
                            timeout=TIMEOUT,
                            max_retries=3,
                            base_delay=PROFILE_DELAY,
                            respect_robots=not args.ignore_robots,
                            proxies=proxies,
                            stats=stats,
                            pre_waited=True,
                        )
                        if fetch_status != "ok" or resp is None:
                            profile_status = status_label(fetch_status)
                            if fetch_status in {"blocked", "captcha", "disallowed"}:
                                break
                            continue

                        emails = extract_emails(resp.text, base_domain)
                        if emails:
                            row["email"] = emails[0]
                            found_emails += 1
                            profile_status = f"email: {row['email'][:28]}"
                            break

                scraped_ids.add(wca_id)
                results_dict[wca_id] = row
                done_count += 1
                profiles_since_rotation += 1

                pct = int(done_count / max(total, 1) * 40)
                bar = "#" * pct + "-" * (40 - pct)
                print(
                    f"\r  [{bar}] {done_count}/{total}  Emails:{found_emails}  | {company[:20]:<20} {profile_status:<35}",
                    end="",
                    flush=True,
                )

                if done_count % SAVE_EVERY == 0:
                    progress["results"] = results_dict
                    progress["scraped_ids"] = list(scraped_ids)
                    progress["all_profiles"] = all_profiles
                    save_progress(progress)
                    write_csv(list(results_dict.values()))

        except KeyboardInterrupt:
            print("\n\n  Interrupted - saving progress...")
            logging.warning("WCA scraper interrupted by user")
        finally:
            progress["results"] = results_dict
            progress["scraped_ids"] = list(scraped_ids)
            progress["all_profiles"] = all_profiles
            save_progress(progress)
            write_csv(list(results_dict.values()))
            if context is not None:
                context.close()
            browser.close()

    total = len(all_profiles)
    found_emails = sum(1 for row in results_dict.values() if row.get("email"))
    print(f"\n\n{'=' * 60}")
    print("  DONE!")
    print(f"  Total profiles : {total}")
    print(f"  Emails found   : {found_emails}")
    print(f"  Success rate   : {found_emails / max(total, 1) * 100:.1f}%")
    print(f"  Saved to       : {OUTPUT_CSV}")
    print(f"  Log file       : {LOG_FILE}")
    stats.print_summary()
    print(f"{'=' * 60}\n")
    logging.info("WCA scraper finished profiles=%s emails=%s", total, found_emails)

    if sys.stdin.isatty():
        input("Press Enter to close...")


if __name__ == "__main__":
    main()
