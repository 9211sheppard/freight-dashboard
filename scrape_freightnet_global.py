# scrape_freightnet_global.py
# Scrapes Freightnet global directory listings:
#   - Air Freight worldwide (s4)
#   - Freight Forwarders worldwide (s99)
# Stops automatically when phone rate drops below 80% on any page.
# Output: freightnet_global.csv on Desktop

import argparse
import csv
import json
import logging
import os
import re
import sys

try:
    from bs4 import BeautifulSoup
    from scrape_utils import (
        RateLimiter,
        ScrapeStats,
        get_proxy_session,
        is_allowed,
        is_blacklisted,
        load_proxies,
        random_headers,
        rotate_proxy,
        safe_get,
    )
except ImportError:
    print("Missing packages. Run: venv\\Scripts\\python.exe -m pip install requests beautifulsoup4")
    raise SystemExit(1)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_CSV = r"C:\Users\Owner\Desktop\freightnet_global.csv"
PROGRESS_FILE = r"C:\Users\Owner\Desktop\freightnet_global_progress.json"
LOG_FILE = r"C:\Users\Owner\Desktop\scrape_freightnet_global.log"

DELAY = 1.0
TIMEOUT = 10
PHONE_THRESHOLD = 0.8
ROTATE_PROXY_EVERY = 50

SOURCES = [
    {"label": "Air Freight", "url": "https://www.freightnet.com/directory/p{}/cAA/s4.htm", "network": "Freightnet-Air"},
    {"label": "Freight Forwarders", "url": "https://www.freightnet.com/directory/p{}/cAA/s99.htm", "network": "Freightnet-FF"},
]

FIELDS = ["network", "company_name", "phone_number", "address", "city", "region", "zip", "country", "sector", "website_url"]


def parse_args():
    parser = argparse.ArgumentParser(description="Scrape Freightnet global directory listings.")
    parser.add_argument("--dry-run", action="store_true", help="Check robots.txt access for known directory URLs without scraping.")
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


def norm(s):
    return re.sub(r"\s+", " ", str(s).lower().strip())


def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {"results": [], "seen": [], "source_progress": {}}
    with open(PROGRESS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {"results": [], "seen": [], "source_progress": {}}
    data.setdefault("results", [])
    data.setdefault("seen", [])
    data.setdefault("source_progress", {})
    return data


def save_progress(progress):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def write_csv(rows):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def parse_page_html(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("div", class_="listing-card")
    results = []
    for card in cards:
        name = card.find(itemprop="name")
        phone = card.find(itemprop="telephone")
        street = card.find(itemprop="streetAddress")
        city = card.find(itemprop="addressLocality")
        region = card.find(itemprop="addressRegion")
        zipcode = card.find(itemprop="postalCode")
        country = card.find(itemprop="addressCountry")
        badge = card.find("span", class_="badge")
        website = card.find("a", href=re.compile(r"^http", re.I))

        company_name = name.get_text(strip=True) if name else ""
        if not company_name or is_blacklisted(company_name):
            continue

        website_val = ""
        if website:
            href = website.get("href", "")
            if href and "freightnet.com" not in href.lower() and "javascript" not in href.lower():
                website_val = href

        results.append(
            {
                "network": "",
                "company_name": company_name,
                "phone_number": phone.get_text(strip=True) if phone else "",
                "address": street.get_text(strip=True) if street else "",
                "city": city.get_text(strip=True) if city else "",
                "region": region.get_text(strip=True) if region else "",
                "zip": zipcode.get_text(strip=True) if zipcode else "",
                "country": country.get("content", "") if country else "",
                "sector": badge.get_text(strip=True) if badge else "",
                "website_url": website_val,
            }
        )
    return results


def maybe_rotate_session(session, proxies, request_count):
    if proxies and request_count and request_count % ROTATE_PROXY_EVERY == 0:
        rotate_proxy(session, proxies)
        session.headers.update(random_headers())


def dry_run(progress, ignore_robots):
    print("\n" + "=" * 55)
    print("  Freightnet Global Scraper - Dry Run")
    print("=" * 55)

    known_urls = set()
    source_progress = progress.get("source_progress", {})
    unknown_exact_pages = False

    for source in SOURCES:
        state = source_progress.get(source["label"], {})
        next_page = int(state.get("next_page", 1) or 1)
        max_known_page = max(1, next_page if state.get("done") else next_page)
        if next_page == 1 and not state:
            unknown_exact_pages = True
        for page_num in range(1, max_known_page + 1):
            known_urls.add(source["url"].format(page_num))

    allowed = 0
    denied = 0
    for url in sorted(known_urls):
        permitted = True if ignore_robots else is_allowed(url)
        if permitted:
            allowed += 1
        else:
            denied += 1

    print(f"  Known URLs     : {len(known_urls)}")
    print(f"  Allowed        : {allowed}")
    print(f"  Denied         : {denied}")
    if unknown_exact_pages:
        print("  Note           : first run dry-run only knows the seed pages until progress exists.")
    print(f"  Log file       : {LOG_FILE}")
    print("=" * 55 + "\n")


def main():
    args = parse_args()
    setup_logging()
    logging.info("Starting Freightnet global scraper dry_run=%s ignore_robots=%s", args.dry_run, args.ignore_robots)

    progress = load_progress()
    if args.dry_run:
        dry_run(progress, args.ignore_robots)
        return

    print("\n" + "=" * 55)
    print("  Freightnet Global Scraper")
    print("=" * 55)

    proxies = load_proxies()
    logging.info("Loaded %s proxies", len(proxies))

    all_results = progress.get("results", [])
    seen = set(progress.get("seen") or [f"{norm(r.get('company_name'))}|||{norm(r.get('country'))}" for r in all_results])
    source_progress = progress.get("source_progress", {})

    session = get_proxy_session(proxies)
    session.headers.update(random_headers())
    rate_limiter = RateLimiter(default_delay=DELAY)
    stats = ScrapeStats()
    request_count = 0

    for source in SOURCES:
        label = source["label"]
        base = source["url"]
        network = source["network"]
        state = source_progress.setdefault(label, {"next_page": 1, "done": False, "source_total": 0})

        if state.get("done"):
            print(f"\n--- {label} ---")
            print(f"  already complete: {state.get('source_total', 0)} companies")
            continue

        print(f"\n--- {label} ---")
        page = int(state.get("next_page", 1) or 1)
        source_total = int(state.get("source_total", 0) or 0)

        while True:
            url = base.format(page)
            maybe_rotate_session(session, proxies, request_count)
            rate_limiter.wait(url)
            resp, status = safe_get(
                session,
                url,
                timeout=TIMEOUT,
                max_retries=3,
                base_delay=DELAY,
                respect_robots=not args.ignore_robots,
                proxies=proxies,
                stats=stats,
                pre_waited=True,
            )
            request_count += 1

            if status != "ok" or resp is None:
                print(f"  p{page}: ERROR {status}")
                logging.warning("Source %s page %s stopped with status=%s", label, page, status)
                break

            rows = parse_page_html(resp.text)
            if not rows:
                print(f"  p{page}: no cards - stopping")
                state["done"] = True
                state["next_page"] = page
                break

            phones = sum(1 for row in rows if row["phone_number"])
            rate = phones / len(rows)

            if rate < PHONE_THRESHOLD:
                print(f"  p{page}: {phones}/{len(rows)} phones ({int(rate * 100)}%) - below threshold, STOPPING")
                state["done"] = True
                state["next_page"] = page
                break

            added = 0
            for row in rows:
                row["network"] = network
                key = f"{norm(row['company_name'])}|||{norm(row['country'])}"
                if key in seen:
                    continue
                seen.add(key)
                all_results.append(row)
                added += 1

            source_total += added
            state["source_total"] = source_total
            state["next_page"] = page + 1
            progress["results"] = all_results
            progress["seen"] = sorted(seen)
            progress["source_progress"] = source_progress
            save_progress(progress)
            write_csv(all_results)

            print(f"  p{page}: {added} added | phones {phones}/{len(rows)} ({int(rate * 100)}%) | running total: {len(all_results)}")
            page += 1

        progress["results"] = all_results
        progress["seen"] = sorted(seen)
        progress["source_progress"] = source_progress
        save_progress(progress)
        write_csv(all_results)
        print(f"  {label} done: {source_total} companies")

    print(f"\n{'=' * 55}")
    print("  COMPLETE")
    print(f"  Total companies : {len(all_results)}")
    print(f"  With phone      : {sum(1 for row in all_results if row['phone_number'])}")
    print(f"  Saved to        : {OUTPUT_CSV}")
    print(f"  Log file        : {LOG_FILE}")
    stats.print_summary()
    print(f"{'=' * 55}\n")
    logging.info("Freightnet global scraper finished total=%s", len(all_results))


if __name__ == "__main__":
    main()
