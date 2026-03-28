"""
rate_engine_v2.py — Rate Intelligence Engine V2
Benchmark calculation, agent scoring, nudge logic, flag + self-recovery.
All rules locked and confirmed. Runs autonomously. No manual overrides.

CONFIRMED RULES:
- Store by LOCODE, display as name
- Agent weights: Response 35% / Quality 30% / Consistency 20% / Coverage 15%
- Negotiation score: 10% of overall
- RFQ cooldown: 7 days
- Confidence: >=80 High, 60-79 Medium, <60 Low
- Nudge: score>=70 AND rate>benchmark_mid by 15-30% (score 70-84) or 15-35% (score>=85)
- Hard flag: score 70-84 >30%, score>=85 >35%
- Flagged: excluded from RFQ priority, no nudge this cycle, rates still stored
- Self-recovery: 2 consecutive clean submissions = auto-unflag
- Archive forever, never delete
- Trend tracking activates after 2-3 cycles
- Smart matching: internal only
- Win = rate selected/booked
- Tie-break: speed > price > consistency
- Benchmark floor: drop bottom 10%
"""

import json
import statistics
from datetime import datetime, timedelta
from database import get_db

NOW = lambda: datetime.now().isoformat()[:16]

# ── LOCODE lookup (matches lanes.js) ─────────────────────────────────────────
LOCODE = {
    # China
    'Shanghai': 'CNSHA', 'Ningbo': 'CNNBO', 'Shenzhen': 'CNSZX',
    'Qingdao': 'CNTAO', 'Xiamen': 'CNXMN', 'Guangzhou': 'CNGZU',
    'Tianjin': 'CNTJN', 'Dalian': 'CNDLC',
    # USA
    'Los Angeles': 'USLAX', 'Long Beach': 'USLGB', 'New York / New Jersey': 'USNYC',
    'Savannah': 'USSAV', 'Houston': 'USHOU', 'Seattle': 'USSEA',
    'Tacoma': 'USTIW', 'Oakland': 'USOAK', 'Miami': 'USMIA',
    'Norfolk': 'USORF', 'Baltimore': 'USBAL', 'Halifax': 'CAHAL',
    # Canada
    'Montreal': 'CAMTR', 'Vancouver': 'CAVAN', 'Prince Rupert': 'CAPTR',
    # India
    'Nhava Sheva / JNPT': 'INNSA', 'Mundra': 'INMUN', 'Chennai': 'INMAA',
    'Pipavav': 'INPAV', 'Hazira': 'INHAZ',
    # Middle East
    'Jebel Ali': 'AEJEA', 'Dubai': 'AEDXB', 'Jeddah': 'SAJED',
    'Dammam': 'SADMM', 'Salalah': 'OMSLL', 'Sohar': 'OMSOH',
    # Europe
    'Rotterdam': 'NLRTM', 'Hamburg': 'DEHAM', 'Antwerp': 'BEANR',
    'Felixstowe': 'GBFXT', 'Le Havre': 'FRLEH', 'Valencia': 'ESVLC',
    'Genoa': 'ITGOA', 'Barcelona': 'ESBCN', 'Algeciras': 'ESALG',
    'La Spezia': 'ITLSP', 'Gioia Tauro': 'ITGIT',
    # Vietnam
    'Cai Mep': 'VNCMP', 'Cai Mep / Vung Tau': 'VNCMP',
    'Hai Phong': 'VNHPH',
    'Ho Chi Minh': 'VNSGN', 'Ho Chi Minh City': 'VNSGN',
    'Ho Chi Minh City / Cat Lai': 'VNSGN',
    'Da Nang': 'VNDAD',
}

def to_locode(name):
    return LOCODE.get(name, name.upper()[:6])


# ── BENCHMARK CALCULATOR ──────────────────────────────────────────────────────

def calculate_benchmarks(cycle_id=None):
    """
    For each lane (origin_locode, dest_locode, carrier):
    1. Gather all rates for this cycle
    2. Drop bottom 10% (floor rule — avoids fake cheap)
    3. Calculate floor/mid/max
    4. Assign confidence: >=5 samples=high, >=3=medium, <3=low
    5. Store in rate_benchmarks
    """
    conn = get_db()
    now  = NOW()

    query = """
        SELECT origin_locode, dest_locode, carrier,
               rate_20ft, rate_40ft, contact_id
        FROM rates
        WHERE archived = 0
          AND validation_status = 'valid'
    """
    params = []
    if cycle_id:
        query += " AND cycle_id = ?"
        params.append(cycle_id)

    rows = conn.execute(query, params).fetchall()

    # Group by lane+carrier
    from collections import defaultdict
    groups = defaultdict(list)
    for r in rows:
        key = (r['origin_locode'], r['dest_locode'], r['carrier'])
        groups[key].append({'20ft': r['rate_20ft'], '40ft': r['rate_40ft']})

    inserted = 0
    for (orig, dest, carrier), rates in groups.items():
        for container in ('20ft', '40ft'):
            vals = sorted([r[container] for r in rates if r[container] and r[container] > 0])
            if not vals:
                continue

            # Drop bottom 10%
            cut = max(1, int(len(vals) * 0.10))
            vals = vals[cut:]

            if not vals:
                continue

            floor_v = vals[0]
            mid_v   = statistics.median(vals)
            max_v   = vals[-1]
            n       = len(vals)
            confidence = 'high' if n >= 5 else ('medium' if n >= 3 else 'low')

            col_floor = f'floor_{container.replace("ft","ft")}'
            col_mid   = f'mid_{container.replace("ft","ft")}'
            col_max   = f'max_{container.replace("ft","ft")}'

            conn.execute(f"""
                INSERT INTO rate_benchmarks
                    (origin_locode, dest_locode, carrier,
                     {col_floor}, {col_mid}, {col_max},
                     confidence, sample_count, cycle_id, calculated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(origin_locode, dest_locode, carrier, cycle_id)
                DO UPDATE SET
                    {col_floor}=excluded.{col_floor},
                    {col_mid}=excluded.{col_mid},
                    {col_max}=excluded.{col_max},
                    confidence=excluded.confidence,
                    sample_count=excluded.sample_count,
                    calculated_at=excluded.calculated_at
            """, (orig, dest, carrier, floor_v, mid_v, max_v,
                  confidence, n, cycle_id, now))
            inserted += 1

    conn.commit()
    conn.close()
    return inserted


# ── AGENT SCORER ──────────────────────────────────────────────────────────────

WEIGHTS = {
    'response_time':   0.35,
    'data_quality':    0.30,
    'consistency':     0.20,
    'lane_coverage':   0.15,
}
NEGOTIATION_WEIGHT = 0.10

def score_agent(contact_id):
    """
    Calculate and store overall agent score.
    Weights: Response 35% / Quality 30% / Consistency 20% / Coverage 15%
    Negotiation score feeds in at 10% of overall.
    """
    conn = get_db()

    # Get existing scores or defaults
    row = conn.execute(
        "SELECT * FROM agent_scores WHERE contact_id=?", (contact_id,)
    ).fetchone()

    if not row:
        # Initialize with defaults
        conn.execute("""
            INSERT OR IGNORE INTO agent_scores (contact_id, updated_at)
            VALUES (?, ?)
        """, (contact_id, NOW()))
        conn.commit()
        row = conn.execute(
            "SELECT * FROM agent_scores WHERE contact_id=?", (contact_id,)
        ).fetchone()

    rt  = row['response_time_score']
    dq  = row['data_quality_score']
    con = row['consistency_score']
    lc  = row['lane_coverage_score']
    neg = row['negotiation_score']

    # Weighted score (excluding negotiation)
    base = (rt  * WEIGHTS['response_time'] +
            dq  * WEIGHTS['data_quality'] +
            con * WEIGHTS['consistency'] +
            lc  * WEIGHTS['lane_coverage'])

    # Negotiation adjusts overall by 10%
    overall = round(base * (1 - NEGOTIATION_WEIGHT) + neg * NEGOTIATION_WEIGHT, 2)
    overall = max(0, min(100, overall))

    conn.execute("""
        UPDATE agent_scores
        SET overall_score=?, updated_at=?
        WHERE contact_id=?
    """, (overall, NOW(), contact_id))
    conn.commit()
    conn.close()
    return overall


def update_negotiation_score(contact_id, event):
    """
    Update negotiation score based on agent response to nudge.
    Events: responded_adjusted, responded_improved, responded_no_change, ignored, flagged, clean_submission
    """
    DELTAS = {
        'responded_adjusted':  +15,
        'responded_improved':   +5,
        'responded_no_change': -10,
        'ignored':             -15,
        'flagged':             -20,
        'clean_submission':     +5,
    }
    delta = DELTAS.get(event, 0)
    if delta == 0:
        return

    conn = get_db()
    conn.execute("""
        INSERT OR IGNORE INTO agent_scores (contact_id, negotiation_score, updated_at)
        VALUES (?, 50, ?)
    """, (contact_id, NOW()))
    conn.execute("""
        UPDATE agent_scores
        SET negotiation_score = MAX(0, MIN(100, negotiation_score + ?)),
            updated_at = ?
        WHERE contact_id = ?
    """, (delta, NOW(), contact_id))
    conn.commit()
    conn.close()
    score_agent(contact_id)


# ── RATE VALIDATOR ────────────────────────────────────────────────────────────

def validate_rate(rate_id):
    """
    Validate a rate against benchmark and flag issues.
    Returns: (status, deviation_pct, confidence)
    """
    conn = get_db()
    rate = conn.execute("SELECT * FROM rates WHERE id=?", (rate_id,)).fetchone()
    if not rate:
        conn.close()
        return 'rejected', 0, 'low'

    origin   = to_locode(rate['origin'])
    dest     = to_locode(rate['destination'])
    carrier  = rate['carrier']
    r20      = rate['rate_20ft']
    r40      = rate['rate_40ft']

    # Check LOCODE validity
    if not origin or not dest:
        _update_rate_status(conn, rate_id, 'flagged', 0, 'low')
        conn.close()
        return 'flagged', 0, 'low'

    # Update LOCODEs on rate record
    conn.execute("""
        UPDATE rates SET origin_locode=?, dest_locode=?
        WHERE id=?
    """, (origin, dest, rate_id))

    # Get benchmark
    bm = conn.execute("""
        SELECT * FROM rate_benchmarks
        WHERE origin_locode=? AND dest_locode=? AND carrier=?
        ORDER BY calculated_at DESC LIMIT 1
    """, (origin, dest, carrier)).fetchone()

    if not bm:
        # No benchmark yet — store as valid, low confidence
        _update_rate_status(conn, rate_id, 'valid', 0, 'low')
        conn.commit()
        conn.close()
        return 'valid', 0, 'low'

    # Check deviation against benchmark mid
    deviation = 0
    if r20 and bm['mid_20ft']:
        deviation = ((r20 - bm['mid_20ft']) / bm['mid_20ft']) * 100
    elif r40 and bm['mid_40ft']:
        deviation = ((r40 - bm['mid_40ft']) / bm['mid_40ft']) * 100

    # Confidence from benchmark
    confidence = bm['confidence']

    # Determine status
    status = 'valid'
    if abs(deviation) > 50:
        status = 'flagged'  # extreme deviation

    _update_rate_status(conn, rate_id, status, deviation, confidence)
    conn.commit()
    conn.close()
    return status, deviation, confidence


def _update_rate_status(conn, rate_id, status, deviation, confidence):
    conn.execute("""
        UPDATE rates SET validation_status=?, deviation_pct=?, confidence=?
        WHERE id=?
    """, (status, deviation, confidence, rate_id))


# ── NUDGE ENGINE ──────────────────────────────────────────────────────────────

def run_nudge_check(cycle_id):
    """
    For each rate in this cycle:
    1. Get agent overall_score
    2. Check deviation against benchmark_mid
    3. Apply nudge rules:
       - Score 70-84: nudge if 15-30% over, hard flag if >30%
       - Score >=85:  nudge if 15-35% over, hard flag if >35%
    4. Log to nudge_log
    Returns: (nudged, flagged) counts
    """
    conn = get_db()
    rates = conn.execute("""
        SELECT r.*, a.overall_score
        FROM rates r
        LEFT JOIN agent_scores a ON a.contact_id = r.contact_id
        WHERE r.cycle_id=? AND r.validation_status='valid' AND r.archived=0
    """, (cycle_id,)).fetchall()

    nudged = 0
    flagged = 0
    now = NOW()

    for rate in rates:
        contact_id   = rate['contact_id']
        agent_score  = rate['overall_score'] or 50
        deviation    = rate['deviation_pct'] or 0
        rate_id      = rate['id']

        if agent_score < 70:
            continue  # below threshold — ignore

        # Check if already nudged this cycle
        already_nudged = conn.execute("""
            SELECT id FROM nudge_log WHERE contact_id=? AND cycle_id=?
        """, (contact_id, cycle_id)).fetchone()
        if already_nudged:
            continue

        # Check if already flagged this cycle
        already_flagged = conn.execute("""
            SELECT id FROM rate_flags WHERE contact_id=? AND cycle_id=?
        """, (contact_id, cycle_id)).fetchone()
        if already_flagged:
            continue

        # Apply rules
        if 70 <= agent_score < 85:
            if 15 <= deviation <= 30:
                _send_nudge(conn, contact_id, cycle_id, rate_id, deviation, now)
                nudged += 1
            elif deviation > 30:
                _flag_agent(conn, contact_id, cycle_id, f'Score 70-84, deviation {deviation:.1f}% > 30%', now)
                flagged += 1

        elif agent_score >= 85:
            if 15 <= deviation <= 35:
                _send_nudge(conn, contact_id, cycle_id, rate_id, deviation, now)
                nudged += 1
            elif deviation > 35:
                _flag_agent(conn, contact_id, cycle_id, f'Score >=85, deviation {deviation:.1f}% > 35%', now)
                flagged += 1

    conn.commit()
    conn.close()
    return nudged, flagged


def _send_nudge(conn, contact_id, cycle_id, rate_id, deviation, now):
    conn.execute("""
        INSERT INTO nudge_log (contact_id, cycle_id, rate_id, deviation_pct, sent_at, response_type)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (contact_id, cycle_id, rate_id, deviation, now))
    update_negotiation_score(contact_id, 'ignored')  # assume ignored until proven otherwise


def _flag_agent(conn, contact_id, cycle_id, reason, now):
    conn.execute("""
        INSERT OR IGNORE INTO rate_flags (contact_id, cycle_id, reason, flagged_at)
        VALUES (?, ?, ?, ?)
    """, (contact_id, cycle_id, reason, now))
    update_negotiation_score(contact_id, 'flagged')


# ── NUDGE RESPONSE HANDLER ────────────────────────────────────────────────────

def handle_nudge_response(contact_id, cycle_id, new_rate_20ft=None, new_rate_40ft=None, responded=True):
    """
    Process agent response to nudge.
    responded=True with new rates → check if adjusted
    responded=True without new rates → no change
    responded=False → already logged as ignored
    """
    conn = get_db()
    nudge = conn.execute("""
        SELECT * FROM nudge_log WHERE contact_id=? AND cycle_id=?
    """, (contact_id, cycle_id)).fetchone()

    if not nudge:
        conn.close()
        return

    now = NOW()
    if not responded:
        conn.execute("""
            UPDATE nudge_log SET response_type='ignored', response_at=? WHERE id=?
        """, (now, nudge['id']))
        update_negotiation_score(contact_id, 'ignored')
        conn.commit()
        conn.close()
        return

    # Get original rate for comparison
    orig_rate = conn.execute("SELECT * FROM rates WHERE id=?", (nudge['rate_id'],)).fetchone()
    if not orig_rate:
        conn.close()
        return

    adjusted = False
    improved = False

    if new_rate_20ft and orig_rate['rate_20ft']:
        if new_rate_20ft < orig_rate['rate_20ft']:
            adjusted = True
            if new_rate_20ft <= orig_rate['rate_20ft'] * 1.15:
                improved = True

    response_type = 'responded_no_change'
    neg_event     = 'responded_no_change'

    if adjusted and improved:
        response_type = 'responded_adjusted'
        neg_event     = 'responded_adjusted'
        # Update rate with new value
        conn.execute("""
            UPDATE rates SET rate_20ft=?, rate_40ft=?, updated_at=?
            WHERE id=?
        """, (new_rate_20ft, new_rate_40ft, now, nudge['rate_id']))

    elif adjusted:
        response_type = 'responded_improved'
        neg_event     = 'responded_improved'
        conn.execute("""
            UPDATE rates SET rate_20ft=?, rate_40ft=?
            WHERE id=?
        """, (new_rate_20ft, new_rate_40ft, nudge['rate_id']))

    conn.execute("""
        UPDATE nudge_log
        SET response_type=?, response_at=?, adjusted_rate=?
        WHERE id=?
    """, (response_type, now, new_rate_20ft, nudge['id']))

    update_negotiation_score(contact_id, neg_event)
    conn.commit()
    conn.close()


# ── SELF-RECOVERY ─────────────────────────────────────────────────────────────

def check_self_recovery(cycle_id):
    """
    Check flagged agents for 2 consecutive clean submissions.
    Clean = rate submitted within benchmark range, no nudge triggered.
    Auto-unflag after 2 consecutive clean cycles.
    Returns count of recovered agents.
    """
    conn = get_db()
    flagged = conn.execute("""
        SELECT DISTINCT contact_id FROM rate_flags
        WHERE auto_recovered=0
    """).fetchall()

    recovered = 0
    for row in flagged:
        contact_id = row['contact_id']

        # Count recent clean cycles (no nudge, no new flags, rate within range)
        clean = conn.execute("""
            SELECT COUNT(DISTINCT r.cycle_id) as clean_count
            FROM rates r
            WHERE r.contact_id=?
              AND r.validation_status='valid'
              AND r.deviation_pct <= 15
              AND r.cycle_id > (
                  SELECT MAX(cycle_id) FROM rate_flags WHERE contact_id=?
              )
              AND r.id NOT IN (SELECT rate_id FROM nudge_log WHERE contact_id=?)
        """, (contact_id, contact_id, contact_id)).fetchone()

        clean_count = clean['clean_count'] if clean else 0

        # Update clean_cycles counter
        conn.execute("""
            UPDATE rate_flags SET clean_cycles=?
            WHERE contact_id=? AND auto_recovered=0
        """, (clean_count, contact_id))

        if clean_count >= 2:
            now = NOW()
            conn.execute("""
                UPDATE rate_flags
                SET auto_recovered=1, recovered_at=?
                WHERE contact_id=? AND auto_recovered=0
            """, (now, contact_id))
            update_negotiation_score(contact_id, 'clean_submission')
            recovered += 1

    conn.commit()
    conn.close()
    return recovered


# ── SMART MATCHER (internal only) ────────────────────────────────────────────

def get_best_match(origin, destination, carrier=None):
    """
    Return best agent + best carrier for a lane.
    Based on: price + transit + agent_score + reliability
    Internal use only — not exposed to agents.
    Tie-break: speed > price > consistency
    """
    conn = get_db()
    orig_lc = to_locode(origin)
    dest_lc = to_locode(destination)

    query = """
        SELECT r.*, a.overall_score, a.response_time_score, a.consistency_score,
               c.company_name, c.country
        FROM rates r
        JOIN agent_scores a ON a.contact_id = r.contact_id
        JOIN contacts c ON c.id = r.contact_id
        WHERE r.origin_locode=? AND r.dest_locode=?
          AND r.validation_status='valid'
          AND r.archived=0
          AND r.contact_id NOT IN (
              SELECT contact_id FROM rate_flags WHERE auto_recovered=0
          )
    """
    params = [orig_lc, dest_lc]
    if carrier:
        query += " AND r.carrier=?"
        params.append(carrier)

    rates = conn.execute(query, params).fetchall()
    conn.close()

    if not rates:
        return None

    def rank(r):
        score     = r['overall_score'] or 50
        price     = r['rate_20ft'] or 9999
        speed     = r['response_time_score'] or 50
        consist   = r['consistency_score'] or 50
        return (-speed, price, -consist, -score)

    best = sorted(rates, key=rank)[0]
    return {
        'contact_id':   best['contact_id'],
        'company_name': best['company_name'],
        'carrier':      best['carrier'],
        'rate_20ft':    best['rate_20ft'],
        'rate_40ft':    best['rate_40ft'],
        'agent_score':  best['overall_score'],
        'confidence':   best['confidence'],
    }


# ── TREND TRACKER ─────────────────────────────────────────────────────────────

def get_trend(origin, destination, carrier=None, days=30):
    """
    Track rate movement over 7/14/30 days.
    Returns: rising / falling / stable / insufficient_data
    Activates only after 2-3 cycles of data.
    """
    conn = get_db()
    orig_lc = to_locode(origin)
    dest_lc = to_locode(destination)
    cutoff  = (datetime.now() - timedelta(days=days)).isoformat()[:10]

    query = """
        SELECT rate_20ft, received_at FROM rates
        WHERE origin_locode=? AND dest_locode=?
          AND received_at >= ?
          AND validation_status='valid'
    """
    params = [orig_lc, dest_lc, cutoff]
    if carrier:
        query += " AND carrier=?"
        params.append(carrier)

    rows = conn.execute(query + " ORDER BY received_at", params).fetchall()
    conn.close()

    if len(rows) < 4:
        return 'insufficient_data'

    # Split into two halves and compare medians
    mid   = len(rows) // 2
    early = statistics.median([r['rate_20ft'] for r in rows[:mid] if r['rate_20ft']])
    late  = statistics.median([r['rate_20ft'] for r in rows[mid:] if r['rate_20ft']])

    if early == 0:
        return 'insufficient_data'

    change_pct = ((late - early) / early) * 100

    if change_pct > 5:
        return 'rising'
    elif change_pct < -5:
        return 'falling'
    else:
        return 'stable'


# ── ARCHIVE RATES ─────────────────────────────────────────────────────────────

def archive_cycle_rates(cycle_id):
    """
    Archive all rates from a completed cycle into rate_history.
    Never delete — archive forever.
    """
    conn = get_db()
    now = NOW()

    rates = conn.execute("""
        SELECT * FROM rates WHERE cycle_id=? AND archived=0
    """, (cycle_id,)).fetchall()

    for r in rates:
        conn.execute("""
            INSERT OR IGNORE INTO rate_history
            (rate_id, contact_id, cycle_id, origin_locode, dest_locode,
             carrier, rate_20ft, rate_40ft, validation_status, confidence,
             archived_at, win)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (r['id'], r['contact_id'], r['cycle_id'],
              r['origin_locode'], r['dest_locode'], r['carrier'],
              r['rate_20ft'], r['rate_40ft'], r['validation_status'],
              r['confidence'], now, r['win']))

        conn.execute("UPDATE rates SET archived=1 WHERE id=?", (r['id'],))

    conn.commit()
    conn.close()
    return len(rates)


# ── RFQ GAP FILLER ────────────────────────────────────────────────────────────

def get_rfq_candidates(missing_origin_locode, missing_dest_locode, carrier=None):
    """
    Find agents eligible for RFQ on a missing lane.
    Rules:
    - overall_score >= 70
    - not flagged (auto_recovered=0 flags excluded)
    - not contacted on this lane in last 7 days (cooldown)
    Returns: list of contact_ids ranked by score
    """
    conn = get_db()
    cooldown = (datetime.now() - timedelta(days=7)).isoformat()[:16]

    rows = conn.execute("""
        SELECT a.contact_id, a.overall_score, c.company_name, c.country
        FROM agent_scores a
        JOIN contacts c ON c.id = a.contact_id
        WHERE a.overall_score >= 70
          AND a.contact_id NOT IN (
              SELECT contact_id FROM rate_flags WHERE auto_recovered=0
          )
          AND a.contact_id NOT IN (
              SELECT DISTINCT contact_id FROM rate_outreach
              WHERE sent_at >= ?
          )
        ORDER BY a.overall_score DESC
    """, (cooldown,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ── CONFIDENCE LABEL ──────────────────────────────────────────────────────────

def confidence_label(score):
    """Convert numeric score to confidence label."""
    if score >= 80:
        return 'high'
    elif score >= 60:
        return 'medium'
    else:
        return 'low'


# ── FULL CYCLE RUN ────────────────────────────────────────────────────────────

def run_intelligence_cycle(cycle_id):
    """
    Run the full intelligence cycle for a given rate cycle.
    Called after rates are collected.
    """
    print(f"[RateEngineV2] Running intelligence cycle for cycle_id={cycle_id}")

    # 1. Calculate benchmarks
    n_benchmarks = calculate_benchmarks(cycle_id)
    print(f"  Benchmarks calculated: {n_benchmarks}")

    # 2. Validate all rates
    conn = get_db()
    rate_ids = [r['id'] for r in conn.execute(
        "SELECT id FROM rates WHERE cycle_id=? AND archived=0", (cycle_id,)
    ).fetchall()]
    conn.close()

    for rid in rate_ids:
        validate_rate(rid)
    print(f"  Rates validated: {len(rate_ids)}")

    # 3. Score all agents who submitted
    conn = get_db()
    agents = [r['contact_id'] for r in conn.execute(
        "SELECT DISTINCT contact_id FROM rates WHERE cycle_id=?", (cycle_id,)
    ).fetchall()]
    conn.close()

    for cid in agents:
        score_agent(cid)
    print(f"  Agents scored: {len(agents)}")

    # 4. Run nudge check
    nudged, flagged = run_nudge_check(cycle_id)
    print(f"  Nudged: {nudged} | Flagged: {flagged}")

    # 5. Check self-recovery
    recovered = check_self_recovery(cycle_id)
    print(f"  Auto-recovered: {recovered}")

    print(f"[RateEngineV2] Cycle {cycle_id} complete.")
    return {
        'benchmarks': n_benchmarks,
        'rates_validated': len(rate_ids),
        'agents_scored': len(agents),
        'nudged': nudged,
        'flagged': flagged,
        'recovered': recovered,
    }
