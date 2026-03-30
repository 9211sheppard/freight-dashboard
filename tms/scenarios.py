import json
import math

from .tms_db import get_db


KM_PER_MILE = 1.60934
KG_PER_LB = 0.45359237
LBS_PER_SHORT_TON = 2000.0
ROUTE_CHANGE_CO2_KG_PER_KM = 0.161
ROUTE_CHANGE_SPEED_MPH = 50.0

SCENARIO_LABELS = {
    "carrier_switch": "Carrier Switch",
    "route_change": "Route Change",
    "mode_shift": "Mode Shift",
    "volume_commitment": "Volume Commitment",
}

MODE_SHIFT_COST_PER_TON_MILE = {
    "TL": 0.18,
    "LTL": 0.28,
    "Rail": 0.10,
    "Air": 1.35,
}
MODE_SHIFT_CO2_PER_TONNE_KM = {
    "TL": 0.096,
    "LTL": 0.120,
    "Rail": 0.028,
    "Air": 0.602,
}
MODE_SHIFT_SPEED_KM_PER_DAY = {
    "TL": 900,
    "LTL": 700,
    "Rail": 550,
    "Air": 3200,
}
MODE_SHIFT_MIN_DAYS = {
    "TL": 2,
    "LTL": 3,
    "Rail": 4,
    "Air": 1,
}


def _ensure_saved_scenarios_table(conn=None):
    owns_connection = conn is None
    conn = conn or get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                scenario_type TEXT NOT NULL,
                inputs_json TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        if owns_connection:
            conn.close()


def _clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _clean_number(value):
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return int(rounded)
    return rounded


def _require_text(value, label):
    clean = _clean_text(value)
    if not clean:
        raise ValueError(f"{label} is required.")
    return clean


def _require_number(value, label, *, allow_zero=False):
    clean = _clean_text(value)
    if not clean:
        raise ValueError(f"{label} is required.")
    try:
        parsed = float(clean)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if allow_zero:
        if parsed < 0:
            raise ValueError(f"{label} must be 0 or greater.")
    elif parsed <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return parsed


def _normalize_mode(value, label):
    clean = _clean_text(value).upper()
    mapping = {
        "TL": "TL",
        "TRUCKLOAD": "TL",
        "FTL": "TL",
        "LTL": "LTL",
        "RAIL": "Rail",
        "INTERMODAL": "Rail",
        "AIR": "Air",
        "AIRFREIGHT": "Air",
    }
    mode = mapping.get(clean)
    if not mode:
        raise ValueError(f"{label} must be one of TL, LTL, Rail, or Air.")
    return mode


def _currency(value):
    return f"${value:,.2f}"


def _miles(value):
    return f"{value:,.0f} mi"


def _hours(value):
    return f"{value:,.1f} hrs"


def _days(value):
    return f"{value:,.1f} days" if isinstance(value, float) and not float(value).is_integer() else f"{value:,.0f} days"


def _kg(value):
    return f"{value:,.1f} kg"


def _loads(value):
    return f"{value:,.0f} loads"


def _percent(value):
    return f"{value:,.1f}%"


def _signed_display(value, formatter):
    if abs(value) < 0.005:
        return formatter(0)
    prefix = "+" if value > 0 else "-"
    return f"{prefix}{formatter(abs(value))}"


def _delta_class(delta, favorable_when="decrease"):
    if abs(delta) < 0.005:
        return "neutral"
    if favorable_when == "decrease":
        return "good" if delta < 0 else "bad"
    return "good" if delta > 0 else "bad"


def _comparison_row(label, current_value, new_value, formatter, *, favorable_when="decrease"):
    delta_value = round(new_value - current_value, 2)
    return {
        "label": label,
        "current_value": round(current_value, 2),
        "new_value": round(new_value, 2),
        "delta_value": delta_value,
        "current_display": formatter(current_value),
        "new_display": formatter(new_value),
        "delta_display": _signed_display(delta_value, formatter),
        "delta_class": _delta_class(delta_value, favorable_when=favorable_when),
    }


def _summary_metric(label, value, tone="neutral"):
    return {
        "label": label,
        "value": value,
        "tone": tone,
    }


def _metric_tone_from_positive(value):
    if value > 0:
        return "good"
    if value < 0:
        return "bad"
    return "neutral"


def _metric_tone_from_negative(value):
    if value < 0:
        return "good"
    if value > 0:
        return "bad"
    return "neutral"


def _mode_shift_metrics(weight_lbs, distance_miles, mode):
    short_tons = weight_lbs / LBS_PER_SHORT_TON
    metric_tonnes = weight_lbs * KG_PER_LB / 1000.0
    distance_km = distance_miles * KM_PER_MILE
    transit_days = max(
        MODE_SHIFT_MIN_DAYS[mode],
        math.ceil(distance_km / MODE_SHIFT_SPEED_KM_PER_DAY[mode]),
    )
    return {
        "mode": mode,
        "cost": round(short_tons * distance_miles * MODE_SHIFT_COST_PER_TON_MILE[mode], 2),
        "transit_days": float(transit_days),
        "co2_kg": round(metric_tonnes * distance_km * MODE_SHIFT_CO2_PER_TONNE_KM[mode], 2),
        "cost_per_ton_mile": MODE_SHIFT_COST_PER_TON_MILE[mode],
        "co2_per_tonne_km": MODE_SHIFT_CO2_PER_TONNE_KM[mode],
    }


def _run_carrier_switch(inputs_dict):
    lane = _require_text(inputs_dict.get("lane"), "Lane")
    current_rate = _require_number(inputs_dict.get("current_rate"), "Current rate")
    new_rate = _require_number(inputs_dict.get("new_rate"), "New rate")
    annual_volume = _require_number(inputs_dict.get("annual_volume"), "Annual volume")

    current_spend = current_rate * annual_volume
    new_spend = new_rate * annual_volume
    annual_savings = round(current_spend - new_spend, 2)
    rate_delta_pct = round(((new_rate - current_rate) / current_rate) * 100, 2)
    risk_score = max(1, min(10, int(math.ceil(abs(rate_delta_pct) / 2.5)) or 1))
    payback_period_months = 0 if annual_savings > 0 else None

    normalized_inputs = {
        "lane": lane,
        "current_rate": _clean_number(current_rate),
        "new_rate": _clean_number(new_rate),
        "annual_volume": _clean_number(annual_volume),
    }

    return {
        "scenario_type": "carrier_switch",
        "title": SCENARIO_LABELS["carrier_switch"],
        "name_suggestion": f"Carrier switch - {lane}",
        "inputs": normalized_inputs,
        "summary_metrics": [
            _summary_metric("Annual savings", _currency(annual_savings), _metric_tone_from_positive(annual_savings)),
            _summary_metric("Payback", "Immediate" if payback_period_months == 0 else "No payback", "neutral"),
            _summary_metric("Risk score", f"{risk_score}/10", "warn" if risk_score >= 7 else "neutral"),
        ],
        "comparison_rows": [
            _comparison_row("Rate per shipment", current_rate, new_rate, _currency),
            _comparison_row("Annual freight spend", current_spend, new_spend, _currency),
            _comparison_row("Annual shipment volume", annual_volume, annual_volume, _loads),
        ],
        "assumptions": [
            "Payback is immediate because no upfront switching cost was provided.",
            "Risk score scales from the absolute rate delta percentage.",
            f"Rate delta: {_signed_display(rate_delta_pct, _percent)}.",
        ],
        "annual_savings": annual_savings,
        "payback_period_months": payback_period_months,
        "risk_score": risk_score,
        "rate_delta_pct": rate_delta_pct,
    }


def _run_route_change(inputs_dict):
    current_miles = _require_number(inputs_dict.get("current_miles"), "Current miles")
    new_miles = _require_number(inputs_dict.get("new_miles"), "New miles")
    fuel_rate = _require_number(inputs_dict.get("fuel_rate"), "Fuel rate", allow_zero=True)
    driver_rate_per_mile = _require_number(
        inputs_dict.get("driver_rate_per_mile"),
        "Driver rate per mile",
        allow_zero=True,
    )

    variable_rate = fuel_rate + driver_rate_per_mile
    current_cost = current_miles * variable_rate
    new_cost = new_miles * variable_rate
    current_co2 = current_miles * KM_PER_MILE * ROUTE_CHANGE_CO2_KG_PER_KM
    new_co2 = new_miles * KM_PER_MILE * ROUTE_CHANGE_CO2_KG_PER_KM
    current_hours = current_miles / ROUTE_CHANGE_SPEED_MPH
    new_hours = new_miles / ROUTE_CHANGE_SPEED_MPH

    cost_delta = round(new_cost - current_cost, 2)
    co2_delta = round(new_co2 - current_co2, 2)
    time_delta = round(new_hours - current_hours, 2)

    normalized_inputs = {
        "current_miles": _clean_number(current_miles),
        "new_miles": _clean_number(new_miles),
        "fuel_rate": _clean_number(fuel_rate),
        "driver_rate_per_mile": _clean_number(driver_rate_per_mile),
    }

    return {
        "scenario_type": "route_change",
        "title": SCENARIO_LABELS["route_change"],
        "name_suggestion": f"Route change - {int(current_miles)} to {int(new_miles)} mi",
        "inputs": normalized_inputs,
        "summary_metrics": [
            _summary_metric("Cost delta", _signed_display(cost_delta, _currency), _metric_tone_from_negative(cost_delta)),
            _summary_metric("CO2 delta", _signed_display(co2_delta, _kg), _metric_tone_from_negative(co2_delta)),
            _summary_metric("Time delta", _signed_display(time_delta, _hours), _metric_tone_from_negative(time_delta)),
        ],
        "comparison_rows": [
            _comparison_row("Route distance", current_miles, new_miles, _miles),
            _comparison_row("Variable trip cost", current_cost, new_cost, _currency),
            _comparison_row("CO2 estimate", current_co2, new_co2, _kg),
            _comparison_row("Transit time", current_hours, new_hours, _hours),
        ],
        "assumptions": [
            "Fuel rate is treated as cost per mile.",
            "Transit time uses a 50 mph planning speed.",
            "CO2 uses the provided 0.161 kg/km factor.",
        ],
        "cost_delta": cost_delta,
        "co2_delta": co2_delta,
        "time_delta": time_delta,
    }


def _run_mode_shift(inputs_dict):
    current_mode = _normalize_mode(inputs_dict.get("current_mode"), "Current mode")
    new_mode = _normalize_mode(inputs_dict.get("new_mode"), "New mode")
    weight_lbs = _require_number(inputs_dict.get("weight_lbs"), "Weight")
    distance = _require_number(inputs_dict.get("distance"), "Distance")

    current_metrics = _mode_shift_metrics(weight_lbs, distance, current_mode)
    new_metrics = _mode_shift_metrics(weight_lbs, distance, new_mode)
    mode_table = []
    for mode in ("TL", "LTL", "Rail", "Air"):
        metrics = _mode_shift_metrics(weight_lbs, distance, mode)
        mode_table.append(
            {
                "mode": mode,
                "cost": metrics["cost"],
                "transit_days": metrics["transit_days"],
                "co2_kg": metrics["co2_kg"],
                "cost_display": _currency(metrics["cost"]),
                "transit_days_display": _days(metrics["transit_days"]),
                "co2_display": _kg(metrics["co2_kg"]),
                "is_current": mode == current_mode,
                "is_new": mode == new_mode,
            }
        )

    cost_delta = round(new_metrics["cost"] - current_metrics["cost"], 2)
    transit_delta = round(new_metrics["transit_days"] - current_metrics["transit_days"], 2)
    co2_delta = round(new_metrics["co2_kg"] - current_metrics["co2_kg"], 2)

    normalized_inputs = {
        "current_mode": current_mode,
        "new_mode": new_mode,
        "weight_lbs": _clean_number(weight_lbs),
        "distance": _clean_number(distance),
    }

    return {
        "scenario_type": "mode_shift",
        "title": SCENARIO_LABELS["mode_shift"],
        "name_suggestion": f"Mode shift - {current_mode} to {new_mode}",
        "inputs": normalized_inputs,
        "summary_metrics": [
            _summary_metric("Cost delta", _signed_display(cost_delta, _currency), _metric_tone_from_negative(cost_delta)),
            _summary_metric("Transit delta", _signed_display(transit_delta, _days), _metric_tone_from_negative(transit_delta)),
            _summary_metric("CO2 delta", _signed_display(co2_delta, _kg), _metric_tone_from_negative(co2_delta)),
        ],
        "comparison_rows": [
            _comparison_row("Estimated freight cost", current_metrics["cost"], new_metrics["cost"], _currency),
            _comparison_row("Transit time", current_metrics["transit_days"], new_metrics["transit_days"], _days),
            _comparison_row("CO2 estimate", current_metrics["co2_kg"], new_metrics["co2_kg"], _kg),
        ],
        "mode_table": mode_table,
        "assumptions": [
            "Distance is modeled in miles.",
            "Cost uses benchmark cost-per-ton-mile assumptions by mode.",
            "Transit time uses fixed speed and minimum-day assumptions by mode.",
        ],
        "cost_delta": cost_delta,
        "transit_delta": transit_delta,
        "co2_delta": co2_delta,
    }


def _run_volume_commitment(inputs_dict):
    committed_volume = _require_number(inputs_dict.get("committed_volume"), "Committed volume", allow_zero=True)
    spot_volume = _require_number(inputs_dict.get("spot_volume"), "Spot volume", allow_zero=True)
    contract_rate = _require_number(inputs_dict.get("contract_rate"), "Contract rate")
    spot_rate = _require_number(inputs_dict.get("spot_rate"), "Spot rate")

    total_volume = committed_volume + spot_volume
    if total_volume <= 0:
        raise ValueError("Committed volume and spot volume cannot both be 0.")

    total_cost = round((committed_volume * contract_rate) + (spot_volume * spot_rate), 2)
    all_spot_cost = round(total_volume * spot_rate, 2)
    blended_rate = round(total_cost / total_volume, 2)
    savings_vs_all_spot = round(all_spot_cost - total_cost, 2)
    committed_share = round((committed_volume / total_volume) * 100, 2)

    normalized_inputs = {
        "committed_volume": _clean_number(committed_volume),
        "spot_volume": _clean_number(spot_volume),
        "contract_rate": _clean_number(contract_rate),
        "spot_rate": _clean_number(spot_rate),
    }

    return {
        "scenario_type": "volume_commitment",
        "title": SCENARIO_LABELS["volume_commitment"],
        "name_suggestion": f"Volume commitment - {int(total_volume)} loads",
        "inputs": normalized_inputs,
        "summary_metrics": [
            _summary_metric("Blended rate", _currency(blended_rate), "neutral"),
            _summary_metric("Total cost", _currency(total_cost), "neutral"),
            _summary_metric("Savings vs all-spot", _currency(savings_vs_all_spot), _metric_tone_from_positive(savings_vs_all_spot)),
        ],
        "comparison_rows": [
            _comparison_row("Average rate per load", spot_rate, blended_rate, _currency),
            _comparison_row("Total freight cost", all_spot_cost, total_cost, _currency),
            _comparison_row("Covered shipment volume", 0, committed_volume, _loads, favorable_when="increase"),
        ],
        "assumptions": [
            f"Committed share: {_percent(committed_share)} of total volume.",
            "Savings are measured against an all-spot baseline.",
        ],
        "blended_rate": blended_rate,
        "total_cost": total_cost,
        "savings_vs_all_spot": savings_vs_all_spot,
        "committed_share_pct": committed_share,
    }


def run_scenario(scenario_type, inputs_dict):
    clean_type = _clean_text(scenario_type)
    handlers = {
        "carrier_switch": _run_carrier_switch,
        "route_change": _run_route_change,
        "mode_shift": _run_mode_shift,
        "volume_commitment": _run_volume_commitment,
    }
    handler = handlers.get(clean_type)
    if handler is None:
        raise ValueError("Scenario type is invalid.")
    return handler(inputs_dict or {})


def save_scenario(name, scenario_type, inputs, results):
    clean_name = _require_text(name, "Scenario name")
    clean_type = _clean_text(scenario_type)
    if clean_type not in SCENARIO_LABELS:
        raise ValueError("Scenario type is invalid.")
    if not isinstance(inputs, dict) or not inputs:
        raise ValueError("Scenario inputs are missing.")
    if not isinstance(results, dict) or not results:
        raise ValueError("Scenario results are missing.")

    conn = get_db()
    try:
        _ensure_saved_scenarios_table(conn)
        cursor = conn.execute(
            """
            INSERT INTO saved_scenarios (name, scenario_type, inputs_json, results_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                clean_name,
                clean_type,
                json.dumps(inputs, ensure_ascii=True, sort_keys=True),
                json.dumps(results, ensure_ascii=True, sort_keys=True),
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT id, name, scenario_type, inputs_json, results_json, created_at
            FROM saved_scenarios
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
        return _deserialize_saved_row(row)
    finally:
        conn.close()


def _deserialize_saved_row(row):
    if row is None:
        return None
    saved = dict(row)
    try:
        saved["inputs"] = json.loads(saved.get("inputs_json") or "{}")
    except json.JSONDecodeError:
        saved["inputs"] = {}
    try:
        saved["results"] = json.loads(saved.get("results_json") or "{}")
    except json.JSONDecodeError:
        saved["results"] = {}
    return saved


def get_saved_scenarios():
    conn = get_db()
    try:
        _ensure_saved_scenarios_table(conn)
        rows = conn.execute(
            """
            SELECT id, name, scenario_type, inputs_json, results_json, created_at
            FROM saved_scenarios
            ORDER BY datetime(created_at) DESC, id DESC
            """
        ).fetchall()
        return [_deserialize_saved_row(row) for row in rows]
    finally:
        conn.close()
