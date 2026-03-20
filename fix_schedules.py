"""
Fix all shipping schedule CSVs:
1. china_to_na_schedules.csv  - recalculate transit from ETD/ETA (day count was zeroed out)
2. india_to_na_schedules.csv  - normalize transit format + deduplicate
"""
import csv, re
from datetime import datetime
from collections import defaultdict

def calc_transit(etd_str, eta_str, fallback_str=''):
    """Calculate transit days from ETD/ETA dates. Fall back to parsing the string."""
    if etd_str and eta_str:
        try:
            etd = datetime.strptime(etd_str, '%Y-%m-%d')
            eta = datetime.strptime(eta_str, '%Y-%m-%d')
            days = (eta - etd).days
            if days > 0:
                return f'{days}d'
        except:
            pass
    # Parse from string if dates unavailable
    if fallback_str:
        d = re.search(r'(\d+)\s*d', fallback_str)
        if d:
            return f'{d.group(1)}d'
        days_match = re.search(r'(\d+)\s*day', fallback_str)
        if days_match:
            return f'{days_match.group(1)}d'
    return ''

def dedup_rows(rows):
    """Keep shortest-transit row per carrier+vessel+etd+destination."""
    def transit_days(t):
        m = re.search(r'(\d+)d', t)
        return int(m.group(1)) if m else 9999

    groups = defaultdict(list)
    for r in rows:
        key = (r['carrier'], r['vessel_name'], r['etd'], r['destination'])
        groups[key].append(r)

    deduped = []
    removed = 0
    for key, group in groups.items():
        if len(group) == 1:
            deduped.append(group[0])
        else:
            best = min(group, key=lambda r: transit_days(r.get('transit_time', '')))
            deduped.append(best)
            removed += len(group) - 1
    return deduped, removed


# ─── FIX 1: china_to_na_schedules.csv ────────────────────────────────────────
print("=== china_to_na_schedules.csv ===")
CHINA = r'C:\Users\Owner\Desktop\china_to_na_schedules.csv'

rows = list(csv.DictReader(open(CHINA, encoding='utf-8-sig')))
print(f"  Rows before: {len(rows)}")

fixed = 0
for r in rows:
    new_t = calc_transit(r.get('etd',''), r.get('eta',''), r.get('transit_time',''))
    if new_t and new_t != r.get('transit_time',''):
        r['transit_time'] = new_t
        fixed += 1

rows.sort(key=lambda r: (r['carrier'], r['origin'], r['destination'], r['etd']))

with open(CHINA, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['carrier','origin','destination','vessel_name','service','etd','eta','transit_time'])
    w.writeheader()
    w.writerows(rows)

print(f"  Rows after: {len(rows)}")
print(f"  Transit times fixed: {fixed}")
print(f"  Sample: {[r['transit_time'] for r in rows[:5]]}")
print()


# ─── FIX 2: india_to_na_schedules.csv ────────────────────────────────────────
print("=== india_to_na_schedules.csv ===")
INDIA = r'C:\Users\Owner\Desktop\india_to_na_schedules.csv'

rows = list(csv.DictReader(open(INDIA, encoding='utf-8-sig')))
print(f"  Rows before: {len(rows)}")

# Recalculate transit from ETD/ETA
fixed = 0
for r in rows:
    new_t = calc_transit(r.get('etd',''), r.get('eta',''), r.get('transit_time',''))
    if new_t != r.get('transit_time',''):
        r['transit_time'] = new_t
        fixed += 1

# Deduplicate
rows, removed = dedup_rows(rows)
print(f"  Duplicates removed: {removed}")
print(f"  Transit times fixed: {fixed}")

rows.sort(key=lambda r: (r['carrier'], r['origin'], r['destination'], r['etd']))

with open(INDIA, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['carrier','origin','destination','vessel_name','service','etd','eta','transit_time'])
    w.writeheader()
    w.writerows(rows)

print(f"  Rows after: {len(rows)}")
print(f"  Sample: {[r['transit_time'] for r in rows[:5]]}")
print()

print("=== shipping_schedules.csv ===")
print("  FILE NOT FOUND on Desktop")
print("  This file needs to be generated or uploaded.")
print()
print("Done.")
