"""
import_csv.py
────────────
Imports one or all configured CSVs into the local SQLite database.
Handles different column layouts automatically.

Usage:
    python import_csv.py              # imports all configured CSVs
    python import_csv.py path/to.csv  # imports a single file
"""

import csv
import os
import sys

from database import init_db, get_db
from config import CSV_SOURCES
from mx_check import check_batch as _mx_check_batch


def normalize(value: str) -> str:
    """Strip whitespace; return empty string for blank/None values."""
    if value is None:
        return ""
    return str(value).strip()


def _find_col(headers: list, candidates: list):
    """Return the first candidate column name found in headers, or None."""
    for c in candidates:
        if c in headers:
            return c
    return None


def _get(row: dict, col) -> str:
    """Safely get a value from a row dict; return '' if col is None."""
    if col is None:
        return ""
    return normalize(row.get(col, ""))


def import_csv(csv_path: str, network_override: str = None) -> dict:
    """
    Import a single CSV into the contacts table.
    - Deletes all existing contacts for the same network before inserting.
    - Returns a summary dict: {network, total, dupes, imported}.
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"CSV file not found at:\n  {csv_path}\n"
            "Please check the path in config.py is correct."
        )

    init_db()
    conn = get_db()

    rows_raw = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = [h.strip().lower() for h in (reader.fieldnames or [])]

            # Detect column names flexibly
            col_network  = _find_col(headers, ["network_name", "network"])
            col_company  = _find_col(headers, ["company_name", "company"])
            col_contact  = _find_col(headers, ["contact_name", "contact"])
            col_email    = _find_col(headers, ["email"])
            col_phone    = _find_col(headers, ["phone_number", "phone"])
            col_country  = _find_col(headers, ["country"])
            col_city     = _find_col(headers, ["city"])

            for row in reader:
                clean = {k.strip().lower(): normalize(v) for k, v in row.items()}

                # Determine network name
                network = network_override
                if not network:
                    network = _get(clean, col_network)
                if not network:
                    network = os.path.splitext(os.path.basename(csv_path))[0].upper()

                rows_raw.append({
                    "network":      network,
                    "company_name": _get(clean, col_company),
                    "contact_name": _get(clean, col_contact),
                    "email":        _get(clean, col_email),
                    "phone_number": _get(clean, col_phone),
                    "country":      _get(clean, col_country),
                    "city":         _get(clean, col_city),
                })

    except Exception as e:
        raise RuntimeError(f"Error reading CSV: {e}") from e

    # Deduplicate on (network, company_name, email, country)
    seen       = set()
    unique     = []
    dupes      = 0
    networks   = set()
    for r in rows_raw:
        networks.add(r["network"])
        key = (r["network"].lower(), r["company_name"].lower(),
               r["email"].lower(),   r["country"].lower())
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        unique.append(r)

    # Save existing verification data before deleting, so we can restore it after.
    # Key by email (ASCII-safe, survives special-character encoding mismatches).
    # Also keep a fallback key by (network, company_name_lower) for contacts without email.
    verify_by_email   = {}   # email.lower()  → verify dict
    verify_by_name    = {}   # (network, company_name.lower()) → verify dict
    for net in networks:
        rows = conn.execute(
            """SELECT company_name, country, email, verified_status, verified_score,
                      verified_date, website_url, linkedin_url, verify_notes
               FROM contacts WHERE network = ?""", (net,)
        ).fetchall()
        for r in rows:
            if r[4] and r[3] not in (None, "", "unverified"):
                verify_by_email[r[2].strip().lower()] = {
                    "verified_status": r[3], "verified_score": r[4],
                    "verified_date":   r[5], "website_url":    r[6],
                    "linkedin_url":    r[7], "verify_notes":   r[8],
                }
            if r[3] not in (None, "", "unverified"):
                verify_by_name[(net.lower(), r[0].strip().lower())] = {
                    "verified_status": r[3], "verified_score": r[4],
                    "verified_date":   r[5], "website_url":    r[6],
                    "linkedin_url":    r[7], "verify_notes":   r[8],
                }

    # Snapshot scraped emails before wiping — preserve any email found by scraper
    scraped_emails = {}
    for net in networks:
        for row in conn.execute(
            "SELECT company_name, email FROM contacts WHERE network=? AND email!='' AND email IS NOT NULL",
            (net,)
        ).fetchall():
            scraped_emails[(net.lower(), row[0].strip().lower())] = row[1]

    # DISABLED: destructive delete removed — import_codex_batch.py handles dedup safely
    # for net in networks:
    #     conn.execute("DELETE FROM contacts WHERE network = ?", (net,))

    conn.executemany(
        """INSERT INTO contacts
               (network, company_name, contact_name, email, phone_number, country, city)
           VALUES
               (:network, :company_name, :contact_name, :email, :phone_number, :country, :city)""",
        unique,
    )

    # Restore verification — try email key first, fall back to name key
    if verify_by_email or verify_by_name:
        for row in unique:
            email_key = row["email"].strip().lower() if row.get("email") else ""
            name_key  = (row["network"].lower(), row["company_name"].strip().lower())
            v = (verify_by_email.get(email_key) if email_key else None) \
                or verify_by_name.get(name_key)
            if v:
                conn.execute(
                    """UPDATE contacts SET
                           verified_status = ?, verified_score  = ?,
                           verified_date   = ?, website_url     = ?,
                           linkedin_url    = ?, verify_notes    = ?
                       WHERE network = ?
                         AND LOWER(email) = LOWER(?)""",
                    (v["verified_status"], v["verified_score"],
                     v["verified_date"],   v["website_url"],
                     v["linkedin_url"],    v["verify_notes"],
                     row["network"],       row["email"]),
                ) if email_key else conn.execute(
                    """UPDATE contacts SET
                           verified_status = ?, verified_score  = ?,
                           verified_date   = ?, website_url     = ?,
                           linkedin_url    = ?, verify_notes    = ?
                       WHERE network = ?
                         AND LOWER(company_name) = LOWER(?)""",
                    (v["verified_status"], v["verified_score"],
                     v["verified_date"],   v["website_url"],
                     v["linkedin_url"],    v["verify_notes"],
                     row["network"],       row["company_name"]),
                )

    # Restore scraped emails that were wiped by the delete+insert
    for (net, company), email in scraped_emails.items():
        conn.execute(
            "UPDATE contacts SET email=? WHERE LOWER(network)=? AND LOWER(company_name)=? AND (email IS NULL OR email='')",
            (email, net, company)
        )

    # ── Step 1: Recalculate score from actual DB fields ───────────────────────
    # Rules (CLAUDE.md): email +35, phone +25, website +15, linkedin +10. Max = 85.
    # Score 100 = confirmed email reply only — never recalculated, never reset.
    from datetime import datetime as _dt
    today = _dt.now().strftime("%Y-%m-%d")

    for net in networks:
        conn.execute("""
            UPDATE contacts SET verified_score = (
                CASE WHEN email        IS NOT NULL AND TRIM(email)        != '' THEN 35 ELSE 0 END +
                CASE WHEN phone_number IS NOT NULL AND TRIM(phone_number) != '' THEN 25 ELSE 0 END +
                CASE WHEN website_url  IS NOT NULL AND TRIM(website_url)  != '' THEN 15 ELSE 0 END +
                CASE WHEN linkedin_url IS NOT NULL AND TRIM(linkedin_url) != '' THEN 10 ELSE 0 END
            )
            WHERE network = ? AND COALESCE(verified_score, 0) != 100
        """, (net,))

    # ── Step 2: Set verified_status for trusted networks ──────────────────────
    # Trusted = paid memberships or government-issued registries.
    # score >= 50 → verified   |   score < 50 → review (needs more data)
    # Unknown networks land as unverified until manually reviewed.
    TRUSTED_NETWORKS = {
        # Existing sources
        "WFA":            "WFA paid member",
        "WWPC":           "WWPC paid member",
        "FIATA":          "FIATA paid member",
        "Freightnet-FF":  "Freightnet paid member, IATA accredited",
        "Freightnet-Air": "Freightnet paid member, IATA accredited",
        "AHK-Japan":      "AHK Japan member directory",
        # Phase 2 — country association sources
        "BIFA":           "BIFA member (British International Freight Association)",
        "NCBFAA":         "NCBFAA member (US customs brokers & forwarders)",
        "DSLV":           "DSLV member (Germany, Bundesverband Spedition)",
        "Fenex":          "Fenex member (Netherlands freight association)",
        "Fedespedi":      "Fedespedi member (Italy freight association)",
        "FETEIA":         "FETEIA member (Spain freight association)",
        "AFIF":           "AFIF member (Australia International Freight Association)",
        "JIFFA":          "JIFFA member (Japan International Freight Forwarders Assoc.)",
        "KIFFA":          "KIFFA member (Korea International Freight Forwarders Assoc.)",
        "CIFA":           "CIFA member (China International Freight Forwarders Assoc.)",
        "FMC-NVOCC":      "FMC licensed NVOCC (US Federal Maritime Commission registry)",
        "WCA":            "WCA World member",
    }

    for net in networks:
        if net not in TRUSTED_NETWORKS:
            continue  # unknown source — leave as unverified for manual review
        note = TRUSTED_NETWORKS[net]
        # score >= 50 → verified (only upgrade, never overwrite score=100)
        conn.execute("""
            UPDATE contacts SET
                verified_status = 'verified',
                verified_date   = ?,
                verify_notes    = ?
            WHERE network = ?
              AND verified_score >= 50
              AND COALESCE(verified_score, 0) != 100
              AND (verified_status IS NULL OR verified_status IN ('', 'unverified', 'review'))
        """, (today, note, net))
        # score < 50 → review (missing email or phone — needs enrichment)
        conn.execute("""
            UPDATE contacts SET
                verified_status = 'review',
                verified_date   = ?,
                verify_notes    = ?
            WHERE network = ?
              AND verified_score < 50
              AND COALESCE(verified_score, 0) != 100
              AND (verified_status IS NULL OR verified_status IN ('', 'unverified'))
        """, (today, note + " — needs email to reach verified", net))

    # ── Step 3: MX record validation ──────────────────────────────────────────
    # Check that each email domain actually accepts mail.
    # Invalid MX → clear email, append note, recalculate score.
    # Never touches score=100 contacts.
    imported_emails = conn.execute(
        "SELECT id, email FROM contacts WHERE network IN ({}) AND email IS NOT NULL AND email != ''"
        .format(",".join("?" * len(networks))),
        list(networks)
    ).fetchall()

    if imported_emails:
        mx_results = _mx_check_batch([r[1] for r in imported_emails], workers=30)
        bad_mx = [(r[0], r[1]) for r in imported_emails if not mx_results.get(r[1], True)]
        if bad_mx:
            for contact_id, email in bad_mx:
                conn.execute(
                    "UPDATE contacts SET email='', "
                    "verify_notes=verify_notes || ' | MX FAIL: no MX record for ' || ?, "
                    "verified_score=("
                    "  CASE WHEN phone_number IS NOT NULL AND TRIM(phone_number)!='' THEN 25 ELSE 0 END +"
                    "  CASE WHEN website_url  IS NOT NULL AND TRIM(website_url) !='' THEN 15 ELSE 0 END +"
                    "  CASE WHEN linkedin_url IS NOT NULL AND TRIM(linkedin_url)!='' THEN 10 ELSE 0 END"
                    ") WHERE id=? AND COALESCE(verified_score,0)!=100",
                    (email, contact_id)
                )
            # Re-set status for any that dropped below 50
            for net in networks:
                conn.execute("""
                    UPDATE contacts SET verified_status='review'
                    WHERE network=? AND verified_score < 50
                      AND COALESCE(verified_score,0)!=100
                      AND verified_status='verified'
                """, (net,))

    conn.commit()
    conn.close()

    network_label = network_override or (list(networks)[0] if networks else "?")
    return {
        "network":  network_label,
        "total":    len(rows_raw),
        "dupes":    dupes,
        "imported": len(unique),
    }


def import_all_csvs() -> list:
    """Import every CSV listed in config.CSV_SOURCES. Returns list of summaries."""
    init_db()

    # Only wipe the networks we are about to reimport — this preserves any
    # contacts that were manually added (e.g. AHK-Japan, direct DB inserts).
    # Each import_csv() call handles deleting its own network before reinserting.

    results = []
    for src in CSV_SOURCES:
        path    = src["path"]
        network = src.get("network")
        if not os.path.exists(path):
            print(f"  [{network or path}] WARNING: file not found — skipping.")
            continue
        summary = import_csv(path, network_override=network)
        print(f"  [{summary['network']}] "
              f"{summary['imported']} imported "
              f"({summary['dupes']} dupes removed, {summary['total']} total rows)")
        results.append(summary)
    return results


if __name__ == "__main__":
    init_db()
    if len(sys.argv) > 1:
        # Single file passed on command line
        result = import_csv(sys.argv[1])
        print(f"Done — {result['imported']} contacts imported.")
    else:
        print("Importing all configured CSVs…")
        summaries = import_all_csvs()
        total = sum(s["imported"] for s in summaries)
        print(f"\nAll done — {total} total contacts in database.")
