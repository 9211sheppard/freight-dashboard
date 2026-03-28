"""
rate_data_seeder.py  —  Seed rate benchmarks from free public freight rate indexes

Solves the cold-start problem: new users see market context BEFORE running their own RFQ cycles.

Data sources (all free, all legal for commercial use):
1. Freightos Baltic Index (FBX) — 12 global container trade lanes, updated daily
   - Published freely at fbx.freightos.com and via press/data partners
   - IOSCO-compliant index, designed for public distribution
2. Drewry World Container Index (WCI) — 8 routes, updated weekly (Thursdays)
   - Free weekly composite published at drewry.co.uk/supply-chain-advisors/wci
3. Carrier spot rates — via existing carrier API adapters (Maersk, CMA CGM, etc.)
   - Uses keys already configured in config.py

These are INDEX-level benchmarks (market averages), NOT proprietary contracted rates.
They provide directional context ("rates on Asia-US are rising") rather than exact quotes.
User's own RFQ data (from rate_engine_v2) overrides these as it accumulates.
"""

import json
import urllib.request
from datetime import datetime
from database import get_db

import logging
log = logging.getLogger("rate_seeder")


# ─────────────────────────────────────────────────────────────────────────────
#  FBX Trade Lanes — Freightos Baltic Index
#  These are the 12 standard FBX container trade lanes with typical LOCODEs
# ─────────────────────────────────────────────────────────────────────────────

FBX_LANES = [
    # (lane_name, origin_locode, dest_locode, description)
    ("FBX01", "CNSHA", "USLAX", "China/East Asia → North America West Coast"),
    ("FBX02", "CNSHA", "USNYC", "China/East Asia → North America East Coast"),
    ("FBX03", "CNSHA", "NLRTM", "China/East Asia → North Europe"),
    ("FBX04", "CNSHA", "GRHEL", "China/East Asia → Mediterranean"),
    ("FBX11", "NLRTM", "CNSHA", "North Europe → China/East Asia"),
    ("FBX12", "NLRTM", "USLAX", "North Europe → North America"),
    ("FBX13", "USLAX", "CNSHA", "North America → China/East Asia"),
    ("FBX14", "USLAX", "NLRTM", "North America → North Europe"),
    ("FBX21", "CNSHA", "BRSSZ", "China/East Asia → South America"),
    ("FBX22", "CNSHA", "AEJEA", "China/East Asia → Middle East"),
    ("FBX23", "CNSHA", "INMAA", "China/East Asia → Indian Subcontinent"),
    ("FBX24", "CNSHA", "AUSYD", "China/East Asia → Oceania"),
]

# ─────────────────────────────────────────────────────────────────────────────
#  WCI Routes — Drewry World Container Index
# ─────────────────────────────────────────────────────────────────────────────

WCI_ROUTES = [
    ("WCI-SHA-RTM", "CNSHA", "NLRTM", "Shanghai → Rotterdam"),
    ("WCI-RTM-SHA", "NLRTM", "CNSHA", "Rotterdam → Shanghai"),
    ("WCI-SHA-GEN", "CNSHA", "ITGOA", "Shanghai → Genoa"),
    ("WCI-SHA-LAX", "CNSHA", "USLAX", "Shanghai → Los Angeles"),
    ("WCI-SHA-NYC", "CNSHA", "USNYC", "Shanghai → New York"),
    ("WCI-NYC-RTM", "USNYC", "NLRTM", "New York → Rotterdam"),
    ("WCI-RTM-NYC", "NLRTM", "USNYC", "Rotterdam → New York"),
    ("WCI-SHA-SYD", "CNSHA", "AUSYD", "Shanghai → Sydney"),
]


# ─────────────────────────────────────────────────────────────────────────────
#  Seed Market Index Benchmarks
# ─────────────────────────────────────────────────────────────────────────────

def seed_index_benchmarks():
    """Seed the rate_benchmarks table with public index data.
    These are market-level benchmarks that provide context for users
    before they have their own RFQ data.

    Marked with carrier='MARKET_INDEX' so they're clearly distinguished
    from user-generated benchmarks.
    """
    conn = get_db()
    now = datetime.now().isoformat()
    seeded = 0

    try:
        # Combine all known lanes
        all_lanes = []
        for lane_id, origin, dest, desc in FBX_LANES:
            all_lanes.append({
                "source": f"FBX:{lane_id}",
                "origin_locode": origin,
                "dest_locode": dest,
                "carrier": "MARKET_INDEX",
                "description": desc,
            })
        for lane_id, origin, dest, desc in WCI_ROUTES:
            all_lanes.append({
                "source": f"WCI:{lane_id}",
                "origin_locode": origin,
                "dest_locode": dest,
                "carrier": "MARKET_INDEX",
                "description": desc,
            })

        for lane in all_lanes:
            # Check if already seeded
            existing = conn.execute(
                """SELECT id FROM rate_benchmarks
                   WHERE origin_locode = ? AND dest_locode = ? AND carrier = 'MARKET_INDEX'""",
                (lane["origin_locode"], lane["dest_locode"])
            ).fetchone()

            if existing:
                continue  # Don't overwrite — user data or previous seed exists

            # Insert placeholder benchmark (will be updated by live fetch)
            conn.execute(
                """INSERT INTO rate_benchmarks
                   (origin_locode, dest_locode, carrier,
                    floor_20ft, mid_20ft, max_20ft,
                    floor_40ft, mid_40ft, max_40ft,
                    confidence, sample_count, calculated_at)
                   VALUES (?, ?, 'MARKET_INDEX', 0, 0, 0, 0, 0, 0, 'index', 0, ?)""",
                (lane["origin_locode"], lane["dest_locode"], now)
            )
            seeded += 1
            log.info(f"[seed] Seeded lane: {lane['source']} {lane['origin_locode']} → {lane['dest_locode']}")

        conn.commit()
        log.info(f"[seed] Seeded {seeded} market index lanes")
        return {"ok": True, "seeded": seeded}

    except Exception as e:
        log.error(f"[seed] Error seeding benchmarks: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Fetch Live FBX Data (from Freightos public endpoint)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_fbx_rates() -> list:
    """Attempt to fetch current FBX index rates.
    Returns list of {lane, rate_40ft, date} or empty list if unavailable.

    FBX data is published on various financial data platforms.
    We try the Freightos Terminal API first, then fall back to known endpoints.
    """
    results = []

    # Try Freightos Terminal public API
    endpoints = [
        "https://terminal.freightos.com/api/fbx",
        "https://fbx.freightos.com/api/indexData",
    ]

    for url in endpoints:
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "FreightIntelligence/1.0")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                if isinstance(data, list):
                    for item in data:
                        results.append({
                            "lane": item.get("lane", ""),
                            "rate_40ft": item.get("value") or item.get("rate") or 0,
                            "date": item.get("date", now_str()),
                        })
                elif isinstance(data, dict) and "data" in data:
                    for item in data["data"]:
                        results.append({
                            "lane": item.get("lane", ""),
                            "rate_40ft": item.get("value") or item.get("rate") or 0,
                            "date": item.get("date", now_str()),
                        })
                if results:
                    log.info(f"[fbx] Fetched {len(results)} FBX rates from {url}")
                    return results
        except Exception as e:
            log.debug(f"[fbx] Failed to fetch from {url}: {e}")
            continue

    log.info("[fbx] Could not fetch live FBX data — will use seeded lanes only")
    return results


def update_benchmarks_from_index(rates: list) -> int:
    """Update rate_benchmarks with live index data.
    Only updates MARKET_INDEX entries (never overwrites user-generated benchmarks).
    """
    if not rates:
        return 0

    conn = get_db()
    updated = 0
    now = datetime.now().isoformat()

    try:
        for rate in rates:
            lane_code = rate.get("lane", "")
            value = float(rate.get("rate_40ft", 0))
            if not value:
                continue

            # Map FBX lane code to LOCODEs
            for fbx_id, origin, dest, desc in FBX_LANES:
                if fbx_id in lane_code or lane_code in desc:
                    # Estimate 20ft as ~60% of 40ft (industry standard)
                    rate_20ft = round(value * 0.6, 2)
                    # Floor/mid/max: ±15% band around the index value
                    conn.execute(
                        """UPDATE rate_benchmarks
                           SET floor_20ft = ?, mid_20ft = ?, max_20ft = ?,
                               floor_40ft = ?, mid_40ft = ?, max_40ft = ?,
                               sample_count = 1, calculated_at = ?
                           WHERE origin_locode = ? AND dest_locode = ?
                             AND carrier = 'MARKET_INDEX'""",
                        (round(rate_20ft * 0.85), round(rate_20ft), round(rate_20ft * 1.15),
                         round(value * 0.85), round(value), round(value * 1.15),
                         now, origin, dest)
                    )
                    updated += 1
                    break

        conn.commit()
        log.info(f"[index] Updated {updated} benchmark entries from index data")
        return updated
    finally:
        conn.close()


def now_str():
    return datetime.now().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
#  Full Seed Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_full_seed():
    """Run the complete data seeding pipeline.
    1. Seed lane structures from FBX + WCI
    2. Try to fetch live FBX rates
    3. Update benchmarks with any live data found
    """
    log.info("[seed] Starting full rate data seed...")

    # Step 1: Seed lane structures
    result = seed_index_benchmarks()
    log.info(f"[seed] Lane structures: {result}")

    # Step 2: Fetch live rates
    fbx_rates = fetch_fbx_rates()

    # Step 3: Update with live data
    if fbx_rates:
        updated = update_benchmarks_from_index(fbx_rates)
        log.info(f"[seed] Updated {updated} lanes with live index data")
    else:
        log.info("[seed] No live data available — lanes seeded with structure only. "
                 "User RFQ data will populate actual rates.")

    return {
        "seeded_lanes": result.get("seeded", 0),
        "live_rates_found": len(fbx_rates),
        "benchmarks_updated": updated if fbx_rates else 0,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_full_seed())
