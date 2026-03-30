"""
AI Insights — Predictive ETA + Lane Scoring
Pure Python, no external ML libraries. Reads from SQLite via tms_db.get_db().
"""
import math
import datetime
from .tms_db import get_db


# ── ETA Prediction ────────────────────────────────────────────────────────────

def _transit_history(origin: str, destination: str, carrier_name: str = None, limit: int = 50):
    """Return list of actual transit days for completed shipments on this lane."""
    conn = get_db()
    if carrier_name:
        rows = conn.execute(
            """SELECT julianday(updated_at) - julianday(etd) AS transit_days
               FROM shipments
               WHERE origin_port=? AND destination_port=?
                 AND carrier_name=?
                 AND status='Delivered'
                 AND etd IS NOT NULL AND updated_at IS NOT NULL
               ORDER BY updated_at DESC LIMIT ?""",
            (origin, destination, carrier_name, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT julianday(updated_at) - julianday(etd) AS transit_days
               FROM shipments
               WHERE origin_port=? AND destination_port=?
                 AND status='Delivered'
                 AND etd IS NOT NULL AND updated_at IS NOT NULL
               ORDER BY updated_at DESC LIMIT ?""",
            (origin, destination, limit)
        ).fetchall()
    return [r[0] for r in rows if r[0] and 0 < r[0] < 120]


def _weighted_avg(values: list, decay: float = 0.9) -> float:
    """Exponentially weighted average — recent shipments count more."""
    if not values:
        return None
    total_w, total_v = 0.0, 0.0
    for i, v in enumerate(values):
        w = decay ** i
        total_w += w
        total_v += w * v
    return total_v / total_w


def predict_eta(origin: str, destination: str, etd_str: str,
                carrier_name: str = None) -> dict:
    """
    Predict ETA for a shipment.
    Returns: {predicted_eta, avg_transit_days, confidence, sample_size, on_time_pct}
    """
    history = _transit_history(origin, destination, carrier_name)
    fallback_used = False

    if len(history) < 3 and carrier_name:
        # Fall back to all carriers on this lane
        history = _transit_history(origin, destination)
        fallback_used = True

    if len(history) < 3:
        # Fall back to tms_lanes avg_transit_days
        conn = get_db()
        lane_code = f"{origin.upper()[:5]}-{destination.upper()[:5]}"
        row = conn.execute(
            "SELECT avg_transit_days FROM tms_lanes WHERE lane_code=?", (lane_code,)
        ).fetchone()
        avg_days = row[0] if row and row[0] else 21
        confidence = "low"
        sample_size = 0
        on_time_pct = None
    else:
        avg_days = _weighted_avg(history)
        stdev = math.sqrt(sum((x - avg_days) ** 2 for x in history) / len(history))
        sample_size = len(history)
        on_time_pct = round(
            100 * sum(1 for d in history if d <= avg_days * 1.1) / sample_size, 1
        )
        if sample_size >= 15 and stdev < 2:
            confidence = "high"
        elif sample_size >= 6:
            confidence = "medium"
        else:
            confidence = "low"

    try:
        etd = datetime.datetime.strptime(etd_str[:10], "%Y-%m-%d").date()
    except Exception:
        etd = datetime.date.today()

    predicted_eta = etd + datetime.timedelta(days=round(avg_days))

    return {
        "origin": origin,
        "destination": destination,
        "etd": etd_str,
        "avg_transit_days": round(avg_days, 1),
        "predicted_eta": predicted_eta.strftime("%Y-%m-%d"),
        "confidence": confidence,
        "sample_size": sample_size,
        "on_time_pct": on_time_pct,
        "carrier_specific": bool(carrier_name and not fallback_used),
    }


def get_late_risk(shipment_id: int) -> dict:
    """
    Score how likely a shipment is to arrive late.
    Returns: {risk_level: low/medium/high, risk_score: 0-100, reasons: []}
    """
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM shipments WHERE id=?", (shipment_id,)
    ).fetchone()
    if not row:
        return {"risk_level": "unknown", "risk_score": 0, "reasons": []}

    reasons = []
    score = 0

    # Factor 1: carrier on-time history on this lane
    history = _transit_history(
        row["origin_port"] or "", row["destination_port"] or "",
        row["carrier_name"]
    )
    if len(history) >= 5:
        avg = sum(history) / len(history)
        late_count = sum(1 for d in history if d > avg * 1.15)
        late_pct = late_count / len(history)
        if late_pct > 0.3:
            score += 35
            reasons.append(f"Carrier late {round(late_pct*100)}% of the time on this lane")
    else:
        score += 10
        reasons.append("Limited history — estimate only")

    # Factor 2: shipment already past ETA
    if row["eta"]:
        try:
            eta = datetime.datetime.strptime(str(row["eta"])[:10], "%Y-%m-%d").date()
            today = datetime.date.today()
            if today > eta and row["status"] not in ("Delivered", "POD Received"):
                days_late = (today - eta).days
                score += min(40, days_late * 8)
                reasons.append(f"{days_late} day(s) past ETA with status: {row['status']}")
        except Exception:
            pass

    # Factor 3: status stale (no events in 5+ days)
    last_event = conn.execute(
        "SELECT MAX(event_date) as last FROM shipment_events WHERE shipment_id=?",
        (shipment_id,)
    ).fetchone()
    if last_event and last_event["last"]:
        try:
            last_dt = datetime.datetime.fromisoformat(str(last_event["last"]))
            days_stale = (datetime.datetime.utcnow() - last_dt).days
            if days_stale > 7:
                score += 20
                reasons.append(f"No tracking update in {days_stale} days")
            elif days_stale > 3:
                score += 8
        except Exception:
            pass
    else:
        score += 15
        reasons.append("No tracking events recorded")

    score = min(100, score)
    if score >= 60:
        risk_level = "high"
    elif score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {"risk_level": risk_level, "risk_score": score, "reasons": reasons}


# ── Lane Scoring ──────────────────────────────────────────────────────────────

def score_lane(origin: str, destination: str) -> dict:
    """
    Score a lane 0–100 based on volume, on-time rate, revenue, and carrier coverage.
    Returns: {score, grade, volume_score, reliability_score, revenue_score,
              coverage_score, shipment_count, carrier_count, avg_revenue}
    """
    conn = get_db()

    # Volume (last 90 days)
    vol = conn.execute(
        """SELECT COUNT(*) as cnt, SUM(freight_rate) as rev
           FROM shipments
           WHERE origin_port=? AND destination_port=?
             AND created_at >= date('now','-90 days')""",
        (origin, destination)
    ).fetchone()

    shipment_count = vol["cnt"] or 0
    avg_revenue = (vol["rev"] / shipment_count) if shipment_count > 0 else 0

    # Volume score (log scale, 20 shipments = ~80pts)
    if shipment_count == 0:
        volume_score = 0
    else:
        volume_score = min(100, int(math.log(shipment_count + 1, 1.3) * 15))

    # Reliability: on-time delivered
    history = _transit_history(origin, destination)
    if len(history) >= 3:
        avg_t = sum(history) / len(history)
        on_time = sum(1 for d in history if d <= avg_t * 1.1) / len(history)
        reliability_score = int(on_time * 100)
    else:
        reliability_score = 50  # neutral when no data

    # Revenue score (normalize against $5000 avg as 100pt target)
    revenue_score = min(100, int((avg_revenue / 5000) * 100)) if avg_revenue else 0

    # Carrier coverage: how many distinct carriers on this lane
    carriers = conn.execute(
        """SELECT COUNT(DISTINCT carrier_name) as cnt
           FROM shipments WHERE origin_port=? AND destination_port=?""",
        (origin, destination)
    ).fetchone()
    carrier_count = carriers["cnt"] or 0
    coverage_score = min(100, carrier_count * 20)  # 5 carriers = 100

    overall = int(
        volume_score * 0.35 +
        reliability_score * 0.30 +
        revenue_score * 0.20 +
        coverage_score * 0.15
    )

    if overall >= 80:
        grade = "A"
    elif overall >= 65:
        grade = "B"
    elif overall >= 50:
        grade = "C"
    elif overall >= 35:
        grade = "D"
    else:
        grade = "F"

    return {
        "origin": origin,
        "destination": destination,
        "score": overall,
        "grade": grade,
        "volume_score": volume_score,
        "reliability_score": reliability_score,
        "revenue_score": revenue_score,
        "coverage_score": coverage_score,
        "shipment_count": shipment_count,
        "carrier_count": carrier_count,
        "avg_revenue": round(avg_revenue, 2),
    }


def get_top_lanes(limit: int = 10) -> list:
    """Return top N lanes by shipment count with scores."""
    conn = get_db()
    rows = conn.execute(
        """SELECT origin_port, destination_port, COUNT(*) as cnt
           FROM shipments
           WHERE origin_port IS NOT NULL AND destination_port IS NOT NULL
           GROUP BY origin_port, destination_port
           ORDER BY cnt DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    lanes = []
    for r in rows:
        s = score_lane(r["origin_port"], r["destination_port"])
        s["shipment_count"] = r["cnt"]
        lanes.append(s)
    lanes.sort(key=lambda x: x["score"], reverse=True)
    return lanes


# ── Carrier Performance Scoring ───────────────────────────────────────────────

def score_carrier(carrier_id: int) -> dict:
    """
    Score a carrier 0–100 across 4 dimensions.
    Returns: {score, grade, on_time_score, claim_score, coverage_score, volume_score}
    """
    conn = get_db()
    carrier = conn.execute(
        "SELECT * FROM tms_carriers WHERE id=?", (carrier_id,)
    ).fetchone()
    if not carrier:
        return {}

    # On-time: delivered shipments where actual <= ETA
    delivered = conn.execute(
        """SELECT COUNT(*) as total,
              SUM(CASE WHEN julianday(updated_at) <= julianday(eta)+1 THEN 1 ELSE 0 END) as ontime
           FROM shipments WHERE carrier_id=? AND status='Delivered' AND eta IS NOT NULL""",
        (carrier_id,)
    ).fetchone()
    total_del = delivered["total"] or 0
    on_time_score = (
        int((delivered["ontime"] / total_del) * 100) if total_del > 0 else 50
    )

    # Claims: freight_claims against this carrier
    claims = conn.execute(
        "SELECT COUNT(*) as cnt FROM freight_claims WHERE carrier_id=?", (carrier_id,)
    ).fetchone()
    claim_score = max(0, 100 - (claims["cnt"] or 0) * 10)

    # Coverage: distinct lanes
    lanes = conn.execute(
        """SELECT COUNT(DISTINCT origin_port||'-'||destination_port) as cnt
           FROM shipments WHERE carrier_id=?""",
        (carrier_id,)
    ).fetchone()
    coverage_score = min(100, (lanes["cnt"] or 0) * 10)

    # Volume: shipments last 90 days
    vol = conn.execute(
        """SELECT COUNT(*) as cnt FROM shipments
           WHERE carrier_id=? AND created_at >= date('now','-90 days')""",
        (carrier_id,)
    ).fetchone()
    volume_score = min(100, int(math.log((vol["cnt"] or 0) + 1, 1.3) * 15))

    overall = int(
        on_time_score * 0.40 +
        claim_score * 0.30 +
        coverage_score * 0.15 +
        volume_score * 0.15
    )
    grade = "A" if overall >= 80 else "B" if overall >= 65 else "C" if overall >= 50 else "D" if overall >= 35 else "F"

    return {
        "carrier_id": carrier_id,
        "carrier_name": carrier["name"],
        "score": overall,
        "grade": grade,
        "on_time_score": on_time_score,
        "claim_score": claim_score,
        "coverage_score": coverage_score,
        "volume_score": volume_score,
        "total_deliveries": total_del,
    }


# ── AI Dashboard ──────────────────────────────────────────────────────────────

def get_ai_dashboard() -> dict:
    """Aggregate data for the /tms/ai-insights page."""
    conn = get_db()

    # Active shipments with late risk
    active = conn.execute(
        """SELECT id, shipment_ref, carrier_name, origin_port, destination_port,
                  eta, status
           FROM shipments
           WHERE status NOT IN ('Delivered','Cancelled','Draft')
           ORDER BY eta ASC LIMIT 50"""
    ).fetchall()

    at_risk = []
    for s in active:
        risk = get_late_risk(s["id"])
        if risk["risk_level"] in ("medium", "high"):
            at_risk.append({**dict(s), **risk})
    at_risk.sort(key=lambda x: x["risk_score"], reverse=True)

    # Top lanes
    top_lanes = get_top_lanes(8)

    # Top carriers
    carriers = conn.execute(
        "SELECT id, name FROM tms_carriers WHERE active=1 ORDER BY name LIMIT 20"
    ).fetchall()
    carrier_scores = []
    for c in carriers:
        cs = score_carrier(c["id"])
        if cs:
            carrier_scores.append(cs)
    carrier_scores.sort(key=lambda x: x["score"], reverse=True)
    top_carriers = carrier_scores[:8]

    # Summary stats
    total_active = len(active)
    high_risk_count = sum(1 for x in at_risk if x["risk_level"] == "high")
    avg_lane_score = (
        round(sum(l["score"] for l in top_lanes) / len(top_lanes), 1)
        if top_lanes else 0
    )

    return {
        "at_risk_shipments": at_risk[:10],
        "top_lanes": top_lanes,
        "top_carriers": top_carriers,
        "total_active": total_active,
        "high_risk_count": high_risk_count,
        "avg_lane_score": avg_lane_score,
    }
