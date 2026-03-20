"""
Fix vietnam_to_na_schedules.csv:
1. Normalize destination names (remove state/province codes)
2. Normalize transit times: "33 day(s) 17 hour(s)" -> "33d 17h"
3. Strip time from ETD/ETA (keep date only for consistency)
4. Deduplicate: same vessel+ETD+destination → keep shortest transit
"""
import csv, re
from collections import defaultdict

DEST_MAP = {
    'HALIFAX, NS':    'Halifax',
    'HOUSTON, TX':    'Houston',
    'LONG BEACH, CA': 'Long Beach',
    'LOS ANGELES, CA':'Los Angeles',
    'MONTREAL, QC':   'Montreal',
    'NEW YORK, NY':   'New York / New Jersey',
    'SAVANNAH, GA':   'Savannah',
}

def normalize_transit(t):
    d = re.search(r'(\d+)\s*day', t)
    h = re.search(r'(\d+)\s*hour', t)
    days  = int(d.group(1)) if d else 0
    hours = int(h.group(1)) if h else 0
    if hours:
        return f'{days}d {hours}h'
    return f'{days}d'

def transit_hours(t):
    d = re.search(r'(\d+)d', t)
    h = re.search(r'(\d+)h', t)
    return int(d.group(1))*24 + int(h.group(1)) if d and h else (int(d.group(1))*24 if d else 9999)

def date_only(dt_str):
    return dt_str.split(' ')[0] if ' ' in dt_str else dt_str

PATH = r'C:\Users\Owner\Desktop\vietnam_to_na_schedules.csv'
rows = list(csv.DictReader(open(PATH, encoding='utf-8-sig')))
print(f'Rows before: {len(rows)}')

# Normalize
for r in rows:
    r['destination']   = DEST_MAP.get(r['destination'].strip(), r['destination'].strip())
    r['transit_time']  = normalize_transit(r.get('transit_time', ''))
    r['etd']           = date_only(r.get('etd', ''))
    r['eta']           = date_only(r.get('eta', ''))
    r['origin']        = r['origin'].title()   # CAI MEP → Cai Mep etc

# Deduplicate: same vessel + ETD + destination → keep shortest transit
groups = defaultdict(list)
for r in rows:
    key = (r['carrier'], r['vessel_name'], r['etd'], r['destination'])
    groups[key].append(r)

deduped, removed = [], 0
for key, group in groups.items():
    best = min(group, key=lambda r: transit_hours(r['transit_time']))
    deduped.append(best)
    removed += len(group) - 1

deduped.sort(key=lambda r: (r['origin'], r['destination'], r['carrier'], r['etd']))

FIELDS = ['carrier','origin','destination','vessel_name','service','etd','eta','transit_time']
with open(PATH, 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(deduped)

print(f'Duplicates removed: {removed}')
print(f'Rows after: {len(deduped)}')
from collections import Counter
print(f'Origins: {dict(Counter(r["origin"] for r in deduped))}')
print(f'Destinations: {dict(Counter(r["destination"] for r in deduped))}')
print(f'Carriers: {dict(Counter(r["carrier"] for r in deduped))}')
print(f'Sample transit: {[r["transit_time"] for r in deduped[:4]]}')
bad = [r for r in deduped if not r["transit_time"] or r["transit_time"]=="0d"]
print(f'Bad transit: {len(bad)}')
print('Done.')
