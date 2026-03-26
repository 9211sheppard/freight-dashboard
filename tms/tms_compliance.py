import csv
import os
import re
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BLOCKLIST_CSV_PATH = os.path.join(DATA_DIR, "denied_party_blocklist.csv")
DUAL_USE_RULES_CSV_PATH = os.path.join(DATA_DIR, "dual_use_hs_prefixes.csv")


def normalize_party_name(value):
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", (value or "").lower())
    return " ".join(cleaned.split())


def normalize_hs_code(value):
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (value or "").upper())
    return cleaned


def parse_declared_value(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None
    parsed = round(float(value), 2)
    if parsed <= 0:
        raise ValueError("Declared value must be greater than 0.")
    return parsed


def default_customs_declaration(shipment):
    shipment = shipment or {}
    return {
        "shipment_ref": shipment.get("shipment_ref", ""),
        "hs_code": "",
        "country_of_origin": "",
        "declared_value": None,
        "currency": shipment.get("currency", "USD") or "USD",
        "export_license_required": 0,
        "screened_at": "",
        "status": "Pending",
    }


def load_denied_party_blocklist(path=BLOCKLIST_CSV_PATH):
    if not os.path.exists(path):
        return []

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        name_field = None
        if reader.fieldnames:
            for candidate in ("name", "party_name", "entity_name"):
                if candidate in reader.fieldnames:
                    name_field = candidate
                    break

        if not name_field:
            return []

        entries = []
        for row in reader:
            name = (row.get(name_field) or "").strip()
            if not name:
                continue
            entries.append(
                {
                    "name": name,
                    "normalized_name": normalize_party_name(name),
                }
            )
        return entries


def load_dual_use_rules(path=DUAL_USE_RULES_CSV_PATH):
    if not os.path.exists(path):
        return []

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []

        prefix_field = "hs_prefix" if "hs_prefix" in reader.fieldnames else None
        reason_field = "reason" if "reason" in reader.fieldnames else None
        if not prefix_field:
            return []

        rules = []
        for row in reader:
            prefix = normalize_hs_code(row.get(prefix_field))
            if not prefix:
                continue
            rules.append(
                {
                    "hs_prefix": prefix,
                    "reason": (row.get(reason_field) or "").strip() if reason_field else "",
                }
            )
        return rules


def _name_matches(candidate_name, blocked_name):
    if not candidate_name or not blocked_name:
        return False
    if candidate_name == blocked_name:
        return True
    padded_candidate = f" {candidate_name} "
    padded_blocked = f" {blocked_name} "
    return padded_blocked in padded_candidate


def screen_party(name, blocklist_entries):
    normalized_name = normalize_party_name(name)
    match = next(
        (
            entry
            for entry in blocklist_entries
            if _name_matches(normalized_name, entry["normalized_name"])
        ),
        None,
    )
    return {
        "name": name or "",
        "normalized_name": normalized_name,
        "matched": match is not None,
        "matched_name": match["name"] if match else "",
    }


def check_export_license(hs_code, rules):
    normalized_hs_code = normalize_hs_code(hs_code)
    if not normalized_hs_code:
        return {
            "required": False,
            "matched_prefix": "",
            "reason": "",
        }

    match = next(
        (rule for rule in rules if normalized_hs_code.startswith(rule["hs_prefix"])),
        None,
    )
    return {
        "required": match is not None,
        "matched_prefix": match["hs_prefix"] if match else "",
        "reason": match["reason"] if match else "",
    }


def _is_complete(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value > 0
    return value is not None


def evaluate_compliance(shipment, declaration, *, blocklist_path=BLOCKLIST_CSV_PATH, rules_path=DUAL_USE_RULES_CSV_PATH):
    shipment = dict(shipment or {})
    declaration = {**default_customs_declaration(shipment), **dict(declaration or {})}

    blocklist_entries = load_denied_party_blocklist(blocklist_path)
    dual_use_rules = load_dual_use_rules(rules_path)

    screening = {
        "shipper": screen_party(shipment.get("shipper_name"), blocklist_entries),
        "consignee": screen_party(shipment.get("consignee_name"), blocklist_entries),
    }
    screening_matches = [result for result in screening.values() if result["matched"]]

    export_license = check_export_license(declaration.get("hs_code"), dual_use_rules)

    checklist = [
        {"key": "shipper_name", "label": "Shipper name", "complete": _is_complete(shipment.get("shipper_name"))},
        {"key": "shipper_address", "label": "Shipper address", "complete": _is_complete(shipment.get("shipper_address"))},
        {"key": "consignee_name", "label": "Consignee name", "complete": _is_complete(shipment.get("consignee_name"))},
        {"key": "consignee_address", "label": "Consignee address", "complete": _is_complete(shipment.get("consignee_address"))},
        {"key": "origin_port", "label": "Origin port", "complete": _is_complete(shipment.get("origin_port"))},
        {"key": "destination_port", "label": "Destination port", "complete": _is_complete(shipment.get("destination_port"))},
        {"key": "cargo_description", "label": "Cargo description", "complete": _is_complete(shipment.get("cargo_description"))},
        {"key": "containers", "label": "Containers", "complete": _is_complete(shipment.get("containers"))},
        {"key": "weight_kg", "label": "Weight", "complete": _is_complete(shipment.get("weight_kg"))},
        {"key": "currency", "label": "Currency", "complete": _is_complete(declaration.get("currency") or shipment.get("currency"))},
        {"key": "incoterm", "label": "Incoterm", "complete": _is_complete(shipment.get("incoterm"))},
        {"key": "hs_code", "label": "HS code", "complete": _is_complete(declaration.get("hs_code"))},
        {"key": "country_of_origin", "label": "Country of origin", "complete": _is_complete(declaration.get("country_of_origin"))},
        {"key": "declared_value", "label": "Declared value", "complete": _is_complete(declaration.get("declared_value"))},
    ]
    missing_fields = [item["label"] for item in checklist if not item["complete"]]

    if screening_matches:
        status = "Blocked"
    elif missing_fields:
        status = "Pending"
    elif export_license["required"]:
        status = "License Review"
    else:
        status = "Clear"

    return {
        "checklist": checklist,
        "missing_fields": missing_fields,
        "missing_count": len(missing_fields),
        "screening": screening,
        "screening_matches": screening_matches,
        "blocked": bool(screening_matches),
        "screened_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "export_license_required": export_license["required"],
        "matched_prefix": export_license["matched_prefix"],
        "license_reason": export_license["reason"],
        "status": status,
        "ready_for_booking": status == "Clear",
    }
