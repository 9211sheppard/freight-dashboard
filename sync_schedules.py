"""
sync_schedules.py
-----------------
Imports all 6 vessel schedule CSVs into vessel_schedules table in the DB.
Safe to run multiple times -- uses INSERT OR IGNORE to skip duplicates.
"""
import csv, os, sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "contacts.db")

FILES = {
    r"C:\Users\Owner\Desktop\Vessel Schedule\china_to_na_schedules.csv":        "China to NA",
    r"C:\Users\Owner\Desktop\Vessel Schedule\europe_to_na_schedules.csv":       "Europe to NA",
    r"C:\Users\Owner\Desktop\Vessel Schedule\india_to_na_schedules.csv":        "India to NA",
    r"C:\Users\Owner\Desktop\Vessel Schedule\middle_east_to_na_schedules.csv":  "Middle East to NA",
    r"C:\Users\Owner\Desktop\Vessel Schedule\vietnam_to_europe_schedules.csv":  "Vietnam to Europe",
    r"C:\Users\Owner\Desktop\Vessel Schedule\vietnam_to_na_schedules.csv":      "Vietnam to NA",
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
