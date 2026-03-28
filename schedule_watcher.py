"""
Vessel Schedule Watcher
Polls CSVs every 30s. When a file grows, verifies and syncs new rows to DB.
Run: python schedule_watcher.py
"""
import os, csv, sqlite3, time, logging
from datetime import datetime

from predictive_eta import compute_delay_stats
from reliability import compute_reliability_scores

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[
        logging.FileHandler(r'C:\Users\Owner\Desktop\claude code\contact-dashboard\schedule_watcher.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DB_PATH = r'C:\Users\Owner\Desktop\claude code\contact-dashboard\data\contacts.db'

LANES = {
    'China to NA':        r'C:\Users\Owner\Desktop\Vessel Schedule\china_to_na_schedules.csv',
    'Europe to NA':       r'C:\Users\Owner\Desktop\Vessel Schedule\europe_to_na_schedules.csv',
    'India to NA':        r'C:\Users\Owner\Desktop\Vessel Schedule\india_to_na_schedules.csv',
    'Middle East to NA':  r'C:\Users\Owner\Desktop\Vessel Schedule\middle_east_to_na_schedules.csv',
    'Vietnam to Europe':  r'C:\Users\Owner\Desktop\Vessel Schedule\vietnam_to_europe_schedules.csv',
    'Vietnam to NA':      r'C:\Users\Owner\Desktop\Vessel Schedule\vietnam_to_na_schedules.csv',
}

def get_sizes():
    return {lane: os.path.getsize(path) for lane, path in LANES.items()}

def sync_lane(lane, path):
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    inserted = 0
    skipped = 0
    bad = 0

    with open(path, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            carrier = row.get('carrier', '').strip()
            origin = row.get('origin', '').strip()
            dest = row.get('destination', '').strip()
            vessel = row.get('vessel_name', '').strip()
            service = row.get('service', '').strip()
            etd = row.get('etd', '').strip()
            eta = row.get('eta', '').strip()
            transit = row.get('transit_time', '').strip()

            # Verify: must have carrier, origin, valid date
            if not carrier or not origin or not etd or not etd.startswith('202'):
                bad += 1
                continue

            # Middle East guard — reject wrong region ports
            if lane == 'Middle East to NA':
                wrong = ['Port Klang', 'Klang', 'Singapore', 'Colombo']
                if any(w.lower() in origin.lower() for w in wrong):
                    log.warning(f'REJECTED wrong port in Middle East lane: {origin}')
                    bad += 1
                    continue

            try:
                cur.execute('''
                    INSERT OR IGNORE INTO vessel_schedules
                    (lane, carrier, origin, destination, vessel_name, service, etd, eta, transit_time, source_file)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                ''', (lane, carrier, origin, dest, vessel, service, etd, eta, transit,
                      os.path.basename(path)))
                if cur.rowcount:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                log.error(f'DB error: {e}')
                bad += 1

    db.commit()
    db.close()
    return inserted, skipped, bad

def print_summary():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute('SELECT lane, COUNT(*), COUNT(DISTINCT carrier) FROM vessel_schedules GROUP BY lane ORDER BY lane')
    rows = cur.fetchall()
    db.close()
    log.info('--- DB SUMMARY ---')
    total = 0
    for r in rows:
        log.info(f'  {r[0]}: {r[1]} sailings | {r[2]} carriers')
        total += r[1]
    log.info(f'  TOTAL: {total} sailings')

def main():
    log.info('Schedule watcher started.')
    print_summary()
    prev_sizes = get_sizes()

    while True:
        time.sleep(30)
        curr_sizes = get_sizes()

        for lane, path in LANES.items():
            prev = prev_sizes.get(lane, 0)
            curr = curr_sizes.get(lane, 0)
            if curr > prev:
                log.info(f'CHANGE DETECTED: {lane} ({prev} -> {curr} bytes) — syncing...')
                ins, skip, bad = sync_lane(lane, path)
                try:
                    compute_delay_stats()
                    compute_reliability_scores()
                except Exception as exc:
                    log.error(f'Prediction refresh failed: {exc}')
                log.info(f'  +{ins} new rows | {skip} dupes | {bad} rejected')
                if ins > 0:
                    print_summary()

        prev_sizes = curr_sizes

if __name__ == '__main__':
    main()
