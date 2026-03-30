"""
Peer / Network Benchmarking
Compares your TMS rates and performance against market_rates data.
"""
import datetime
from .tms_db import get_db


# ── Market Rate Comparison ─────────────────────────────────────────────────────

def _get_market_rates(origin: str, destination: str) -> list:
    """Pull market rates for a lane from market_rates table."""
    conn = get_db()
    rows = conn.execute(
        """SELECT rate_20ft, rate_40ft, rate_40hc, carrier_name, effective_date
           FROM market_rates
           WHERE origin=? AND destination=?
             AND effective_date >= date('now','-90 days')
           ORDER BY effective_date DESC LIMIT 20""",
        (origin, destination)
    ).fetchall()
    return [dict(r) for r in rows]


def _percentile(values: list, pct: float) -> float:
    """Return the value at the given percentile (0–100)."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = (pct / 100) * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return round(s[lo] * (1 - frac) + s[hi] * frac, 2)


def benchmark_lane(origin: str, destination: str) -> dict:
    """
    Compare your contract rates vs. market for a lane.
    Returns percentile position, savings/overpay, and recommendation.
    """
    conn = get_db()

    # Your contract rates on this lane
    your_rates = conn.execute(
        """SELECT rate_20ft, rate_40ft, rate_40hc, currency
           FROM contract_rates
           WHERE origin=? AND destination=?
             AND valid_to >= date('now')
           ORDER BY valid_from DESC LIMIT 5""",
        (origin, destination)
    ).fetchall()

    # Market rates
    market = _get_market_rates(origin, destination)

    if not market:
        return {
            "origin": origin, "destination": destination,
            "status": "no_market_data",
            "message": "No market rate data available for this lane",
        }

    market_20ft = [r["rate_20ft"] for r in market if r["rate_20ft"]]
    market_40ft = [r["rate_40ft"] for r in market if r["rate_40ft"]]

    result = {
        "origin": origin,
        "destination": destination,
        "market_sample_size": len(market),
        "market_20ft_avg": round(sum(market_20ft) / len(market_20ft), 2) if market_20ft else None,
        "market_40ft_avg": round(sum(market_40ft) / len(market_40ft), 2) if market_40ft else None,
        "market_20ft_p25": _percentile(market_20ft, 25),
        "market_20ft_p75": _percentile(market_20ft, 75),
        "market_40ft_p25": _percentile(market_40ft, 25),
        "market_40ft_p75": _percentile(market_40ft, 75),
        "your_rates": [dict(r) for r in your_rates],
        "analysis": [],
        "status": "ok",
    }

    # Compare each contract rate
    if your_rates and market_20ft:
        for r in your_rates:
            if r["rate_20ft"]:
                mkt_avg = result["market_20ft_avg"]
                delta = r["rate_20ft"] - mkt_avg
                delta_pct = round((delta / mkt_avg) * 100, 1) if mkt_avg else 0

                # Percentile rank
                rank = sum(1 for m in market_20ft if m < r["rate_20ft"])
                percentile_rank = round((rank / len(market_20ft)) * 100)

                if delta_pct > 10:
                    verdict = "overpaying"
                    recommendation = f"You are paying {abs(delta_pct)}% above market. Renegotiate or shop carriers."
                elif delta_pct < -10:
                    verdict = "below_market"
                    recommendation = "Strong rate — protect this contract."
                else:
                    verdict = "market_rate"
                    recommendation = "Rate is competitive."

                result["analysis"].append({
                    "rate_20ft": r["rate_20ft"],
                    "market_avg_20ft": mkt_avg,
                    "delta_usd": round(delta, 2),
                    "delta_pct": delta_pct,
                    "percentile_rank": percentile_rank,
                    "verdict": verdict,
                    "recommendation": recommendation,
                })

    return result


def get_benchmark_dashboard() -> dict:
    """
    Full benchmark dashboard: top lanes comparison, overall position, carrier rate heat map.
    """
    conn = get_db()

    # Get active lanes from contract_rates
    lanes = conn.execute(
        """SELECT DISTINCT origin, destination
           FROM contract_rates
           WHERE valid_to >= date('now')
           ORDER BY origin, destination LIMIT 20"""
    ).fetchall()

    lane_benchmarks = []
    overpay_total = 0.0
    lanes_analyzed = 0
    below_market_count = 0
    overpaying_count = 0

    for lane in lanes:
        bm = benchmark_lane(lane["origin"], lane["destination"])
        if bm["status"] == "ok" and bm["analysis"]:
            lane_benchmarks.append(bm)
            lanes_analyzed += 1
            for a in bm["analysis"]:
                if a["verdict"] == "overpaying":
                    overpaying_count += 1
                    # Monthly overpay estimate (assume 4 shipments/month)
                    overpay_total += a["delta_usd"] * 4
                elif a["verdict"] == "below_market":
                    below_market_count += 1

    # Market rate trend (last 6 months from market_rates)
    trend = conn.execute(
        """SELECT strftime('%Y-%m', effective_date) as month,
                  AVG(rate_20ft) as avg_20ft, AVG(rate_40ft) as avg_40ft,
                  COUNT(*) as samples
           FROM market_rates
           WHERE effective_date >= date('now','-180 days')
           GROUP BY month ORDER BY month"""
    ).fetchall()

    # Your avg contract rate vs market avg by month
    your_trend = conn.execute(
        """SELECT strftime('%Y-%m', valid_from) as month,
                  AVG(rate_20ft) as avg_20ft, AVG(rate_40ft) as avg_40ft
           FROM contract_rates
           WHERE valid_from >= date('now','-180 days')
           GROUP BY month ORDER BY month"""
    ).fetchall()

    return {
        "lane_benchmarks": lane_benchmarks,
        "lanes_analyzed": lanes_analyzed,
        "overpaying_count": overpaying_count,
        "below_market_count": below_market_count,
        "estimated_monthly_overpay": round(overpay_total, 2),
        "market_trend": [dict(r) for r in trend],
        "your_trend": [dict(r) for r in your_trend],
    }


def get_carrier_rate_comparison(carrier_id: int) -> dict:
    """
    Compare a specific carrier's rates against all carriers on shared lanes.
    """
    conn = get_db()
    carrier = conn.execute(
        "SELECT id, name FROM tms_carriers WHERE id=?", (carrier_id,)
    ).fetchone()
    if not carrier:
        return {}

    # Lanes this carrier serves
    lanes = conn.execute(
        """SELECT DISTINCT origin_port as origin, destination_port as destination
           FROM shipments WHERE carrier_id=?""",
        (carrier_id,)
    ).fetchall()

    comparisons = []
    for lane in lanes:
        # Avg rate this carrier charges on this lane
        carrier_avg = conn.execute(
            """SELECT AVG(freight_rate) as avg_rate, COUNT(*) as cnt
               FROM shipments
               WHERE carrier_id=? AND origin_port=? AND destination_port=?
                 AND freight_rate > 0""",
            (carrier_id, lane["origin"], lane["destination"])
        ).fetchone()

        if not carrier_avg["avg_rate"]:
            continue

        # All carriers' avg on same lane
        all_avg = conn.execute(
            """SELECT AVG(freight_rate) as avg_rate, COUNT(DISTINCT carrier_id) as carriers
               FROM shipments
               WHERE origin_port=? AND destination_port=? AND freight_rate > 0""",
            (lane["origin"], lane["destination"])
        ).fetchone()

        if all_avg["avg_rate"]:
            delta_pct = round(
                ((carrier_avg["avg_rate"] - all_avg["avg_rate"]) / all_avg["avg_rate"]) * 100, 1
            )
            comparisons.append({
                "origin": lane["origin"],
                "destination": lane["destination"],
                "carrier_avg_rate": round(carrier_avg["avg_rate"], 2),
                "market_avg_rate": round(all_avg["avg_rate"], 2),
                "delta_pct": delta_pct,
                "carrier_shipments": carrier_avg["cnt"],
                "total_carriers_on_lane": all_avg["carriers"],
                "verdict": "expensive" if delta_pct > 10 else "cheap" if delta_pct < -10 else "fair",
            })

    return {
        "carrier_id": carrier_id,
        "carrier_name": carrier["name"],
        "lane_comparisons": comparisons,
        "lanes_analyzed": len(comparisons),
    }
