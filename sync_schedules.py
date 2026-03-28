"""
sync_schedules.py
-----------------
Imports all 6 vessel schedule CSVs into vessel_schedules table in the DB.
Safe to run multiple times -- uses INSERT OR IGNORE to skip duplicates.
"""
import csv, os, sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "contacts.db")

VS = r"C:\Users\Owner\Desktop\Vessel Schedule"

FILES = {
    # ── Existing lanes ────────────────────────────────────────────────────────
    VS + r"\china_to_na_schedules.csv":               "China to NA",
    VS + r"\europe_to_na_schedules.csv":              "Europe to NA",
    VS + r"\india_to_na_schedules.csv":               "India to NA",
    VS + r"\middle_east_to_na_schedules.csv":         "Middle East to NA",
    VS + r"\vietnam_to_europe_schedules.csv":         "Vietnam to Europe",
    VS + r"\vietnam_to_na_schedules.csv":             "Vietnam to NA",
    # ── China expanded ────────────────────────────────────────────────────────
    VS + r"\china_to_europe_schedules.csv":           "China to Europe",
    VS + r"\china_to_canada_schedules.csv":           "China to Canada",
    VS + r"\china_to_australia_schedules.csv":        "China to Australia/NZ",
    VS + r"\china_to_mexico_schedules.csv":           "China to Mexico",
    VS + r"\china_to_southamerica_schedules.csv":     "China to South America",
    # ── Northeast Asia ────────────────────────────────────────────────────────
    VS + r"\northeast_asia_to_na_schedules.csv":      "Northeast Asia to NA",
    VS + r"\northeast_asia_to_europe_schedules.csv":  "Northeast Asia to Europe",
    VS + r"\northeast_asia_to_australia_schedules.csv": "Northeast Asia to Australia/NZ",
    # ── South Asia expanded ───────────────────────────────────────────────────
    VS + r"\south_asia_to_europe_schedules.csv":      "South Asia to Europe",
    VS + r"\south_asia_to_canada_schedules.csv":      "South Asia to Canada",
    VS + r"\south_asia_to_australia_schedules.csv":   "South Asia to Australia/NZ",
    # ── Southeast Asia ────────────────────────────────────────────────────────
    VS + r"\sea_to_na_schedules.csv":                 "SE Asia to NA",
    VS + r"\sea_to_europe_schedules.csv":             "SE Asia to Europe",
    VS + r"\sea_to_australia_schedules.csv":          "SE Asia to Australia/NZ",
    # ── Middle East / Turkey / Egypt ──────────────────────────────────────────
    VS + r"\me_turkey_egypt_to_europe_schedules.csv": "Middle East to Europe",
    VS + r"\me_turkey_egypt_to_canada_schedules.csv": "Middle East to Canada",
    VS + r"\me_turkey_egypt_to_australia_schedules.csv": "Middle East to Australia/NZ",
    # ── Africa + Brazil ───────────────────────────────────────────────────────
    VS + r"\africa_brazil_to_na_schedules.csv":       "Africa/Brazil to NA",
    VS + r"\africa_brazil_to_europe_schedules.csv":   "Africa/Brazil to Europe",
    VS + r"\africa_regional_schedules.csv":           "Africa Regional",
}

db = sqlite3.connect(DB_PATH)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS vessel_schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lane          TEXT,
    carrier       TEXT,
    origin        TEXT,
    destination   TEXT,
    vessel_name   TEXT,
    service       TEXT,
    etd           TEXT,
    eta           TEXT,
    transit_time  TEXT,
    imported_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(carrier, origin, destination, vessel_name, etd)
)
""")
db.commit()

total_new = 0
for path, lane in FILES.items():
    if not os.path.exists(path):
        print("MISSING: " + path)
        continue
    added = 0
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute(
                "INSERT OR IGNORE INTO vessel_schedules "
                "(lane,carrier,origin,destination,vessel_name,service,etd,eta,transit_time) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    lane,
                    (row.get("carrier") or "").strip(),
                    (row.get("origin") or "").strip(),
                    (row.get("destination") or "").strip(),
                    (row.get("vessel_name") or "").strip(),
                    (row.get("service") or "").strip(),
                    (row.get("etd") or "").strip(),
                    (row.get("eta") or "").strip(),
                    (row.get("transit_time") or "").strip(),
                ),
            )
            if cur.rowcount > 0:
                added += 1
    db.commit()
    cur.execute("SELECT COUNT(*) FROM vessel_schedules WHERE lane=?", (lane,))
    total = cur.fetchone()[0]
    print(lane + ": +" + str(added) + " new  |  " + str(total) + " total in DB")
    total_new += added

cur.execute("SELECT COUNT(*) FROM vessel_schedules")
grand = cur.fetchone()[0]
print("\nDB total: " + str(grand) + " sailings  |  " + str(total_new) + " new this sync")

# Show carrier breakdown
print("\nCarrier breakdown by lane:")
cur.execute("""
    SELECT lane, carrier, COUNT(*) as cnt
    FROM vessel_schedules
    GROUP BY lane, carrier
    ORDER BY lane, cnt DESC
""")
current_lane = ""
for lane, carrier, cnt in cur.fetchall():
    if lane != current_lane:
        print("  [" + lane + "]")
        current_lane = lane
    print("    " + carrier + ": " + str(cnt))

db.close()
