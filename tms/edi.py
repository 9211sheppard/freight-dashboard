from __future__ import annotations

import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path


X12_TRANSACTION_TYPES = {"204", "210", "211", "214", "215", "850", "856", "990", "997"}
EDIFACT_MESSAGE_TYPES = {"IFTMIN", "IFTSTA", "INVOIC"}
SUPPORTED_TRANSACTION_TYPES = X12_TRANSACTION_TYPES | EDIFACT_MESSAGE_TYPES
AUTO_APPLY_TRANSACTION_TYPES = {
    "204",
    "210",
    "211",
    "214",
    "215",
    "850",
    "856",
    "990",
    "IFTMIN",
    "IFTSTA",
    "INVOIC",
}

REFERENCE_PRIORITY = ("CN", "SI", "BM", "PO", "SN", "2I", "11", "ZZ")
ORIGIN_ENTITY_CODES = {"SH", "SF", "OR", "WH", "PL", "CZ"}
DESTINATION_ENTITY_CODES = {"CN", "ST", "BT", "UC", "UD"}
CARRIER_ENTITY_CODES = {"CA"}
EDIFACT_PARTY_CODES = {
    "shipper": {"CZ", "SF", "FW"},
    "consignee": {"CN", "UC"},
    "carrier": {"CA", "MS"},
}

AT7_STATUS_MAP = {
    "AF": {"status": "In Transit", "label": "Departed pickup"},
    "AG": {"status": "In Transit", "label": "Estimated delivery updated"},
    "CA": {"status": "Cancelled", "label": "Shipment cancelled"},
    "CP": {"status": "Booked", "label": "Pickup appointment set"},
    "D1": {"status": "Delivered", "label": "Delivered"},
    "P1": {"status": "In Transit", "label": "Departed terminal"},
    "SD": {"status": "Active", "label": "Scheduled for delivery"},
    "X1": {"status": "Active", "label": "Arrived at pickup"},
    "X3": {"status": "Delivered", "label": "Arrived at delivery"},
    "X6": {"status": "In Transit", "label": "En route"},
}

Q7_STATUS_MAP = {
    "AF": {"status": "In Transit", "label": "Ocean departure confirmed"},
    "CA": {"status": "Cancelled", "label": "Ocean shipment cancelled"},
    "D1": {"status": "Delivered", "label": "Ocean shipment delivered"},
    "X3": {"status": "Delivered", "label": "Arrived at destination port"},
    "X6": {"status": "In Transit", "label": "Ocean shipment in transit"},
}

STATUS_TO_AT7 = {
    "ACTIVE": "X1",
    "BOOKED": "CP",
    "IN TRANSIT": "X6",
    "DELIVERED": "D1",
    "CANCELLED": "CA",
    "DRAFT": "AG",
}

STATUS_TO_Q7 = {
    "ACTIVE": "AF",
    "BOOKED": "AF",
    "IN TRANSIT": "X6",
    "DELIVERED": "D1",
    "CANCELLED": "CA",
    "DRAFT": "AF",
}

TENDER_RESPONSE_MAP = {
    "A": {"accepted": True, "status": "Active", "label": "Tender accepted"},
    "D": {"accepted": False, "status": "Cancelled", "label": "Tender declined"},
    "R": {"accepted": False, "status": "Cancelled", "label": "Tender rejected"},
}

EDIFACT_STATUS_MAP = {
    "ACT": {"status": "Active", "label": "Shipment active"},
    "BKD": {"status": "Booked", "label": "Shipment booked"},
    "DEP": {"status": "In Transit", "label": "Shipment departed"},
    "INT": {"status": "In Transit", "label": "Shipment in transit"},
    "DEL": {"status": "Delivered", "label": "Shipment delivered"},
    "CAN": {"status": "Cancelled", "label": "Shipment cancelled"},
}

EDI_INBOX_DIR = Path(__file__).resolve().parent / "edi_inbox"
EDI_ARCHIVE_DIR = EDI_INBOX_DIR / "archive"
EDI_FAILED_DIR = EDI_INBOX_DIR / "failed"
INBOX_EXTENSIONS = {".edi", ".x12", ".txt", ".dat"}
WATCHER_POLL_SECONDS = 15
_WATCHER_LOCK = threading.Lock()
_WATCHER_THREAD = None
_WATCHER_STOP = threading.Event()


def _clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def _segment_text(value):
    text = _clean_text(value)
    return text.replace("*", " ").replace("~", " ").replace(">", " ").replace("+", " ").replace("'", " ")


def _element(elements, position):
    return elements[position] if len(elements) > position else ""


def _first_present(*values):
    for value in values:
        if _clean_text(value):
            return _clean_text(value)
    return ""


def _parse_number(value):
    raw = _clean_text(value).replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_x12_date(value):
    raw = _clean_text(value)
    if len(raw) != 8 or not raw.isdigit():
        return ""
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _parse_x12_time(value):
    raw = _clean_text(value)
    if not raw.isdigit() or len(raw) < 4:
        return ""
    raw = raw[:6].ljust(6, "0")
    return f"{raw[:2]}:{raw[2:4]}:{raw[4:6]}"


def _parse_edifact_date(value, format_code=""):
    raw = _clean_text(value)
    fmt = _clean_text(format_code)
    if fmt == "102" and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if fmt in {"203", "204"} and len(raw) >= 12 and raw[:12].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T{raw[8:10]}:{raw[10:12]}"
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def _combine_date_time(date_value, time_value=""):
    clean_date = _clean_text(date_value)
    if not clean_date:
        return ""
    clean_time = _clean_text(time_value)
    if not clean_time:
        return clean_date
    return f"{clean_date}T{clean_time}"


def _format_outbound_date(value):
    raw = _clean_text(value)
    if not raw:
        return ""
    return raw[:10].replace("-", "")


def _format_outbound_time(value):
    raw = _clean_text(value)
    if not raw:
        return ""
    if "T" in raw:
        raw = raw.split("T", 1)[1]
    raw = raw.replace(":", "")
    return raw[:4] if raw else ""


def _convert_weight_to_kg(value, unit_code):
    amount = _parse_number(value)
    if amount is None:
        return None
    unit = _clean_text(unit_code).upper()
    if unit in {"LB", "L"}:
        return round(amount * 0.45359237, 2)
    return round(amount, 2)


def _convert_volume_to_cbm(value, unit_code):
    amount = _parse_number(value)
    if amount is None:
        return None
    unit = _clean_text(unit_code).upper()
    if unit in {"CF", "E"}:
        return round(amount * 0.0283168, 3)
    return round(amount, 3)


def _split_location(value):
    text = _clean_text(value)
    if not text:
        return {"city": "", "state": "", "postal": "", "country": ""}
    if "," not in text:
        return {"city": text, "state": "", "postal": "", "country": ""}

    city, remainder = [part.strip() for part in text.split(",", 1)]
    remainder_parts = remainder.split()
    state = remainder_parts[0] if remainder_parts else ""
    postal = remainder_parts[1] if len(remainder_parts) > 1 else ""
    country = remainder_parts[2] if len(remainder_parts) > 2 else ""
    return {"city": city, "state": state, "postal": postal, "country": country}


def _location_label(party):
    if not party:
        return ""
    city = _clean_text(party.get("city"))
    state = _clean_text(party.get("state"))
    name = _clean_text(party.get("name"))
    if city and state:
        return f"{city}, {state}"
    return city or name


def _address_label(party):
    if not party:
        return ""
    pieces = [
        _clean_text(party.get("address_line_1")),
        _clean_text(party.get("address_line_2")),
        _location_label(party),
        _clean_text(party.get("postal_code")),
        _clean_text(party.get("country")),
    ]
    return ", ".join(piece for piece in pieces if piece)


def _choose_reference(references, *qualifiers):
    for qualifier in qualifiers:
        values = references.get(qualifier, [])
        if values:
            return values[0]
    for qualifier in REFERENCE_PRIORITY:
        values = references.get(qualifier, [])
        if values:
            return values[0]
    return ""


def _candidate_parties(stops, codes, from_end=False):
    iterable = reversed(stops) if from_end else stops
    for stop in iterable:
        parties = stop.get("parties", {})
        for code in codes:
            if parties.get(code):
                return stop, parties[code]
        for party in parties.values():
            return stop, party
    return None, None


def _party_lookup(parties, codes):
    for code in codes:
        if parties.get(code):
            return parties[code]
    return next(iter(parties.values()), None)


def _stop_date(stops, from_end=False, qualifiers=()):
    iterable = reversed(stops) if from_end else stops
    for stop in iterable:
        for item in stop.get("dates", []):
            if item["qualifier"] in qualifiers and item["value"]:
                return item["value"]
    return ""


def _transaction_segment_count(segments):
    return len(segments) + 1


def _component(elements, position):
    value = _clean_text(_element(elements, position))
    if not value:
        return []
    return [part.strip() for part in value.split(":")]


def _edifact_component(value, index):
    parts = [part.strip() for part in _clean_text(value).split(":")]
    return parts[index] if len(parts) > index else ""


def _next_unique(values):
    seen = set()
    result = []
    for value in values:
        clean = _clean_text(value)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _infer_location_for_status(shipment, status):
    clean_status = _clean_text(status).lower()
    if clean_status == "delivered":
        return _clean_text(shipment.get("destination_port"))
    if clean_status in {"cancelled", "canceled"}:
        return _first_present(shipment.get("origin_port"), shipment.get("destination_port"))
    return _first_present(shipment.get("origin_port"), shipment.get("destination_port"))


def _status_to_at7_code(status):
    clean_status = _clean_text(status).upper()
    return STATUS_TO_AT7.get(clean_status, "AG")


def _status_to_q7_code(status):
    clean_status = _clean_text(status).upper()
    return STATUS_TO_Q7.get(clean_status, "AF")


def _decode_edi_bytes(payload):
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return payload.decode("latin-1", errors="replace")


def make_control_number(length=9):
    digits = datetime.now(timezone.utc).strftime("%H%M%S%f")
    return digits[-length:].zfill(length)


def _build_isa_segment(sender_id, receiver_id, control_number, current_dt=None, usage_indicator="T"):
    current_dt = current_dt or datetime.now(timezone.utc)
    return "*".join(
        [
            "ISA",
            "00",
            "".ljust(10),
            "00",
            "".ljust(10),
            "ZZ",
            _segment_text(sender_id)[:15].ljust(15),
            "ZZ",
            _segment_text(receiver_id)[:15].ljust(15),
            current_dt.strftime("%y%m%d"),
            current_dt.strftime("%H%M"),
            "^",
            "00501",
            str(control_number).zfill(9),
            "0",
            usage_indicator,
            ">",
        ]
    )


def _serialize_segments(segment_rows, segment_terminator="~"):
    return segment_terminator.join(segment_rows) + segment_terminator


def _build_x12_envelope(
    functional_id,
    transaction_type,
    sender_id,
    receiver_id,
    body_segments,
    *,
    control_numbers=None,
    current_dt=None,
    version="005010",
):
    control_numbers = control_numbers or {}
    current_dt = current_dt or datetime.now(timezone.utc)
    isa_control = str(control_numbers.get("isa") or make_control_number(9)).zfill(9)
    gs_control = str(control_numbers.get("gs") or make_control_number(9)).lstrip("0") or "1"
    st_control = str(control_numbers.get("st") or make_control_number(4)).zfill(4)
    sender_code = _segment_text(sender_id)[:15]
    receiver_code = _segment_text(receiver_id)[:15]
    segments = [
        _build_isa_segment(sender_id, receiver_id, isa_control, current_dt=current_dt),
        f"GS*{functional_id}*{sender_code}*{receiver_code}*{current_dt.strftime('%Y%m%d')}*{current_dt.strftime('%H%M')}*{gs_control}*X*{version}",
        f"ST*{transaction_type}*{st_control}*{version}",
    ]
    segments.extend(body_segments)
    segments.append(f"SE*{_transaction_segment_count(segments[2:])}*{st_control}")
    segments.append(f"GE*1*{gs_control}")
    segments.append(f"IEA*1*{isa_control}")
    return _serialize_segments(segments)


def _build_unb(sender_id, receiver_id, control_number, current_dt=None):
    current_dt = current_dt or datetime.now(timezone.utc)
    return (
        f"UNB+UNOA:1+{_segment_text(sender_id)[:35]}+{_segment_text(receiver_id)[:35]}"
        f"+{current_dt.strftime('%y%m%d')}:{current_dt.strftime('%H%M')}+{control_number}"
    )


def _serialize_edifact_segments(segment_rows):
    return "'".join(segment_rows) + "'"


def _parse_party_segment(elements):
    return {
        "entity_code": _clean_text(_element(elements, 1)),
        "name": _clean_text(_element(elements, 2)),
        "id_qualifier": _clean_text(_element(elements, 3)),
        "id_code": _clean_text(_element(elements, 4)),
        "address_line_1": "",
        "address_line_2": "",
        "city": "",
        "state": "",
        "postal_code": "",
        "country": "",
    }


def _parse_edifact_party_segment(elements):
    return {
        "entity_code": _clean_text(_element(elements, 1)),
        "name": _first_present(
            _clean_text(_element(elements, 4)),
            _edifact_component(_element(elements, 2), 0),
        ),
        "id_qualifier": _edifact_component(_element(elements, 2), 2),
        "id_code": _edifact_component(_element(elements, 2), 0),
        "address_line_1": _clean_text(_element(elements, 5)),
        "address_line_2": _clean_text(_element(elements, 6)),
        "city": _clean_text(_element(elements, 7)),
        "state": _clean_text(_element(elements, 8)),
        "postal_code": _clean_text(_element(elements, 9)),
        "country": _clean_text(_element(elements, 10)),
    }


def parse_x12_document(raw_document):
    text = _clean_text(raw_document)
    if not text:
        raise ValueError("EDI document is empty.")

    segments = [
        segment.strip()
        for segment in re.split(r"~\s*", text.replace("\r", "").replace("\n", ""))
        if segment.strip()
    ]
    if not segments:
        raise ValueError("EDI document does not contain any segments.")

    interchange = {}
    group = {}
    transaction_segments = []
    raw_transaction_segments = []
    transactions = []

    for segment in segments:
        parts = segment.split("*")
        tag = parts[0].upper()

        if tag == "ISA":
            interchange = _parser_parse_isa(parts)
            continue
        if tag == "GS":
            group = _parser_parse_gs(parts)
            continue
        if tag == "ST":
            transaction_segments = [parts]
            raw_transaction_segments = [segment]
            continue

        if transaction_segments:
            transaction_segments.append(parts)
            raw_transaction_segments.append(segment)
            if tag == "SE":
                transactions.append(
                    _parser_parse_transaction(
                        interchange,
                        group,
                        transaction_segments,
                        raw_transaction_segments,
                    )
                )
                transaction_segments = []
                raw_transaction_segments = []

    if transaction_segments:
        raise ValueError("EDI transaction is missing a closing SE segment.")
    if not transactions:
        raise ValueError("EDI document does not contain any transaction sets.")
    return transactions


def generate_204(
    shipment,
    *,
    sender_id="SENDER",
    receiver_id="RECEIVER",
    control_numbers=None,
    current_dt=None,
):
    shipment = shipment or {}
    current_dt = _parser_coerce_datetime(current_dt)
    control_numbers = control_numbers or {}
    carrier_scac = _parser_clean(shipment.get("carrier_scac")) or _parser_edi_id(shipment.get("carrier_name"))
    carrier_name = _parser_clean(shipment.get("carrier_name")) or "Carrier"
    shipment_ref = _parser_clean(shipment.get("shipment_ref")) or "LOAD-0001"

    body_segments = [
        f"B2**{carrier_scac}**{shipment_ref}",
        "B2A*00*LT",
    ]

    shipper_name = _parser_clean(shipment.get("shipper_name"))
    if shipper_name:
        body_segments.extend(
            _parser_party_segments("SH", shipper_name, shipment.get("shipper_address"), shipment.get("origin_port"))
        )

    etd_value = _parser_format_x12_date_value(shipment.get("etd"))
    if etd_value:
        body_segments.append(f"G62*10*{etd_value}")

    consignee_name = _parser_clean(shipment.get("consignee_name"))
    if consignee_name:
        body_segments.extend(
            _parser_party_segments("CN", consignee_name, shipment.get("consignee_address"), shipment.get("destination_port"))
        )

    eta_value = _parser_format_x12_date_value(shipment.get("eta"))
    if eta_value:
        body_segments.append(f"G62*17*{eta_value}")

    body_segments.append(f"N1*CA*{carrier_name}*2*{carrier_scac}")

    weight_value = _parser_clean_number(shipment.get("weight_kg"))
    volume_value = _parser_clean_number(shipment.get("volume_cbm"))
    if weight_value or volume_value:
        body_segments.append(f"AT8*G*K*{weight_value or ''}***V*{volume_value or ''}")

    cargo_description = _parser_clean(shipment.get("cargo_description"))
    if cargo_description:
        body_segments.append(f"L5*1*{cargo_description}")

    notes = _parser_clean(shipment.get("notes"))
    if notes:
        body_segments.append(f"NTE*ADD*{notes}")

    return _build_x12_envelope(
        "SM",
        "204",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_997(parsed_transaction, *, control_numbers=None, current_dt=None):
    parsed_transaction = parsed_transaction or {}
    current_dt = _parser_coerce_datetime(current_dt)
    control_numbers = control_numbers or {}
    interchange = parsed_transaction.get("interchange") or {}
    group = parsed_transaction.get("group") or {}
    sender_id = interchange.get("receiver_id") or group.get("receiver_code") or "RECEIVER"
    receiver_id = interchange.get("sender_id") or group.get("sender_code") or "SENDER"
    transaction_type = parsed_transaction.get("type") or "UNKNOWN"
    inbound_control = parsed_transaction.get("transaction_set_control_number") or "0001"
    functional_id = group.get("functional_id") or "SM"
    group_control = group.get("control_number") or "1"

    body_segments = [
        f"AK1*{functional_id}*{group_control}",
        f"AK2*{transaction_type}*{inbound_control}",
        "AK5*A",
        "AK9*A*1*1*1",
    ]

    return _build_x12_envelope(
        "FA",
        "997",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def _parser_parse_transaction(interchange, group, transaction_segments, raw_transaction_segments):
    transaction_type = transaction_segments[0][1] if len(transaction_segments[0]) > 1 else ""
    transaction = {
        "type": transaction_type,
        "transaction_set_control_number": transaction_segments[0][2] if len(transaction_segments[0]) > 2 else "",
        "interchange": dict(interchange or {}),
        "group": dict(group or {}),
        "references": {},
        "shipment": {},
        "parties": {},
        "events": [],
        "carrier": {},
        "response": {},
        "raw_transaction": "~".join(raw_transaction_segments) + "~",
    }

    if transaction_type == "204":
        transaction.update(_parser_parse_204(transaction_segments))
    elif transaction_type == "214":
        transaction.update(_parser_parse_214(transaction_segments))
    elif transaction_type == "990":
        transaction.update(_parser_parse_990(transaction_segments))

    return transaction


def _parser_parse_204(transaction_segments):
    shipment = {"status": "Booked"}
    references = {}
    parties = {}
    current_party_key = None

    for parts in transaction_segments[1:]:
        tag = parts[0].upper()
        if tag == "B2":
            shipment["carrier_scac"] = _parser_clean(parts[2] if len(parts) > 2 else "")
            shipment["shipment_ref"] = _parser_clean(parts[4] if len(parts) > 4 else "")
            references["shipment_ref"] = shipment.get("shipment_ref", "")
        elif tag == "L11":
            if len(parts) > 2 and _parser_clean(parts[2]).upper() == "CN":
                references["shipment_ref"] = _parser_clean(parts[1] if len(parts) > 1 else "")
                shipment["shipment_ref"] = references["shipment_ref"]
        elif tag == "N1":
            entity_code = _parser_clean(parts[1] if len(parts) > 1 else "").upper()
            current_party_key = _parser_party_key(entity_code)
            if not current_party_key:
                continue
            party = parties.setdefault(current_party_key, {})
            party["name"] = _parser_clean(parts[2] if len(parts) > 2 else "")
            if len(parts) > 4 and _parser_clean(parts[3]).upper() == "2":
                party["scac"] = _parser_clean(parts[4])
            if current_party_key == "carrier":
                shipment["carrier_name"] = party.get("name", "")
                shipment["carrier_scac"] = party.get("scac", shipment.get("carrier_scac", ""))
        elif tag == "N3" and current_party_key:
            party = parties.setdefault(current_party_key, {})
            address_parts = [_parser_clean(value) for value in parts[1:] if _parser_clean(value)]
            party["address"] = ", ".join(address_parts)
        elif tag == "N4" and current_party_key:
            party = parties.setdefault(current_party_key, {})
            party["city"] = _parser_clean(parts[1] if len(parts) > 1 else "")
            party["state"] = _parser_clean(parts[2] if len(parts) > 2 else "")
            party["postal_code"] = _parser_clean(parts[3] if len(parts) > 3 else "")
        elif tag == "G62":
            qualifier = _parser_clean(parts[1] if len(parts) > 1 else "")
            value = _parser_format_iso_date(_parser_clean(parts[2] if len(parts) > 2 else ""))
            if qualifier == "10":
                shipment["etd"] = value
            elif qualifier == "17":
                shipment["eta"] = value
        elif tag == "AT8":
            shipment["weight_kg"] = _parser_parse_float(parts[3] if len(parts) > 3 else "")
            shipment["volume_cbm"] = _parser_parse_float(parts[7] if len(parts) > 7 else "")
        elif tag == "L5":
            shipment["cargo_description"] = _parser_clean(parts[2] if len(parts) > 2 else "")
        elif tag == "NTE":
            shipment["notes"] = _parser_clean(parts[2] if len(parts) > 2 else "")

    shipper = parties.get("shipper", {})
    consignee = parties.get("consignee", {})
    carrier = parties.get("carrier", {})
    shipment["shipment_ref"] = shipment.get("shipment_ref") or references.get("shipment_ref", "")
    shipment["shipper_name"] = shipper.get("name", "")
    shipment["shipper_address"] = shipper.get("address", "")
    shipment["consignee_name"] = consignee.get("name", "")
    shipment["consignee_address"] = consignee.get("address", "")
    shipment["origin_port"] = _parser_party_location(shipper)
    shipment["destination_port"] = _parser_party_location(consignee)
    shipment["carrier_name"] = shipment.get("carrier_name") or carrier.get("name", "")
    shipment["carrier_scac"] = shipment.get("carrier_scac") or carrier.get("scac", "")

    return {
        "shipment": shipment,
        "references": references,
        "parties": parties,
        "carrier": {"scac": shipment.get("carrier_scac", ""), "name": shipment.get("carrier_name", "")},
    }


def _parser_parse_214(transaction_segments):
    shipment = {"status": "In Transit"}
    references = {}
    carrier = {}
    events = []
    current_event = None

    for parts in transaction_segments[1:]:
        tag = parts[0].upper()
        if tag == "B10":
            references["pro_number"] = _parser_clean(parts[1] if len(parts) > 1 else "")
            references["shipment_ref"] = _parser_clean(parts[2] if len(parts) > 2 else "")
            shipment["shipment_ref"] = references["shipment_ref"]
            shipment["carrier_scac"] = _parser_clean(parts[3] if len(parts) > 3 else "")
            carrier["scac"] = shipment["carrier_scac"]
        elif tag == "N1":
            entity_code = _parser_clean(parts[1] if len(parts) > 1 else "").upper()
            if entity_code == "CA":
                carrier["name"] = _parser_clean(parts[2] if len(parts) > 2 else "")
                if len(parts) > 4 and _parser_clean(parts[3]).upper() == "2":
                    carrier["scac"] = _parser_clean(parts[4])
                    shipment["carrier_scac"] = carrier["scac"]
        elif tag == "LX":
            if current_event:
                events.append(current_event)
            current_event = {}
        elif tag == "AT7":
            status_code = _parser_clean(parts[1] if len(parts) > 1 else "").upper()
            status_meta = AT7_STATUS_MAP.get(status_code, {"status": "In Transit", "label": f"Status {status_code or 'UNKNOWN'}"})
            current_event = current_event or {}
            current_event["status"] = status_meta["status"]
            current_event["description"] = status_meta["label"]
            current_event["event_date"] = _parser_combine_x12_datetime(
                parts[4] if len(parts) > 4 else "",
                parts[5] if len(parts) > 5 else "",
            )
        elif tag == "MS1":
            current_event = current_event or {}
            current_event["location"] = _parser_location_label(
                _parser_clean(parts[1] if len(parts) > 1 else ""),
                _parser_clean(parts[2] if len(parts) > 2 else ""),
            )

    if current_event:
        events.append(current_event)

    if events:
        shipment["status"] = events[-1].get("status", shipment["status"])

    return {
        "shipment": shipment,
        "references": references,
        "carrier": carrier,
        "events": events,
    }


def _parser_parse_990(transaction_segments):
    shipment = {}
    references = {}
    carrier = {}
    response = {}

    for parts in transaction_segments[1:]:
        tag = parts[0].upper()
        if tag == "B1":
            carrier["scac"] = _parser_clean(parts[1] if len(parts) > 1 else "")
            references["shipment_ref"] = _parser_clean(parts[2] if len(parts) > 2 else "")
            shipment["shipment_ref"] = references["shipment_ref"]
            shipment["carrier_scac"] = carrier.get("scac", "")
            response_code = _parser_clean(parts[4] if len(parts) > 4 else (parts[-1] if len(parts) > 1 else "")).upper()
            response_meta = TENDER_RESPONSE_MAP.get(
                response_code,
                {"accepted": False, "status": "Draft", "label": "Tender response received"},
            )
            response = {
                "code": response_code,
                "accepted": response_meta["accepted"],
                "status": response_meta["status"],
                "label": response_meta["label"],
            }
            shipment["status"] = response_meta["status"]

    return {
        "shipment": shipment,
        "references": references,
        "carrier": carrier,
        "response": response,
    }


def _parser_parse_isa(parts):
    return {
        "sender_id": _parser_clean(parts[6] if len(parts) > 6 else ""),
        "receiver_id": _parser_clean(parts[8] if len(parts) > 8 else ""),
        "date": _parser_clean(parts[9] if len(parts) > 9 else ""),
        "time": _parser_clean(parts[10] if len(parts) > 10 else ""),
        "control_number": _parser_clean(parts[13] if len(parts) > 13 else ""),
    }


def _parser_parse_gs(parts):
    return {
        "functional_id": _parser_clean(parts[1] if len(parts) > 1 else ""),
        "sender_code": _parser_clean(parts[2] if len(parts) > 2 else ""),
        "receiver_code": _parser_clean(parts[3] if len(parts) > 3 else ""),
        "date": _parser_clean(parts[4] if len(parts) > 4 else ""),
        "time": _parser_clean(parts[5] if len(parts) > 5 else ""),
        "control_number": _parser_clean(parts[6] if len(parts) > 6 else ""),
        "version": _parser_clean(parts[8] if len(parts) > 8 else ""),
    }


def _parser_coerce_datetime(current_dt):
    if current_dt is None:
        return datetime.now(timezone.utc)
    if current_dt.tzinfo is None:
        return current_dt.replace(tzinfo=timezone.utc)
    return current_dt.astimezone(timezone.utc)


def _parser_party_segments(entity_code, name, address, location):
    segments = [f"N1*{entity_code}*{_parser_clean(name)}"]
    address_value = _parser_clean(address)
    if address_value:
        segments.append(f"N3*{address_value}")
    city, state = _parser_split_location(location)
    if city or state:
        segments.append(f"N4*{city}*{state}*")
    return segments


def _parser_format_iso_date(raw_value):
    value = _parser_clean(raw_value)
    if len(value) == 8 and value.isdigit():
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _parser_format_x12_date_value(raw_value):
    value = _parser_clean(raw_value)
    if not value:
        return ""
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[0:4] + value[5:7] + value[8:10]
    return re.sub(r"[^0-9]", "", value)[:8]


def _parser_combine_x12_datetime(date_value, time_value):
    iso_date = _parser_format_iso_date(date_value)
    clean_time = re.sub(r"[^0-9]", "", _parser_clean(time_value))
    if not iso_date:
        return ""
    if len(clean_time) >= 4:
        return f"{iso_date} {clean_time[0:2]}:{clean_time[2:4]}:00"
    return f"{iso_date} 00:00:00"


def _parser_clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _parser_clean_number(value):
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _parser_clean(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.2f}".rstrip("0").rstrip(".")


def _parser_parse_float(value):
    clean_value = _parser_clean(value)
    if not clean_value:
        return None
    try:
        return float(clean_value)
    except ValueError:
        return None


def _parser_edi_id(value):
    return (_parser_clean(value).upper() or "UNKNOWN")[:15]


def _parser_party_key(entity_code):
    return {
        "SH": "shipper",
        "SF": "shipper",
        "CN": "consignee",
        "ST": "consignee",
        "CA": "carrier",
    }.get(entity_code)


def _parser_party_location(party):
    return _parser_location_label(party.get("city", ""), party.get("state", ""))


def _parser_location_label(city, state):
    city = _parser_clean(city)
    state = _parser_clean(state)
    if city and state:
        return f"{city}, {state}"
    return city or state


def _parser_split_location(value):
    location = _parser_clean(value)
    if not location:
        return "", ""
    if "," in location:
        city, state = location.split(",", 1)
        return city.strip(), state.strip().split()[0]
    return location, ""


def detect_edi_format(raw_text):
    text = (raw_text or "").replace("\ufeff", "").lstrip()
    if text.startswith("ISA"):
        return "X12"
    if text.startswith("UNA") or text.startswith("UNB"):
        return "EDIFACT"
    raise ValueError("Unable to detect EDI format. Expected X12 ISA or EDIFACT UNB/UNA envelope.")


def detect_x12_delimiters(raw_text):
    text = (raw_text or "").replace("\ufeff", "")
    isa_index = text.find("ISA")
    if isa_index == -1:
        raise ValueError("ISA segment not found.")
    text = text[isa_index:]
    if len(text) < 4:
        raise ValueError("Incomplete ISA segment.")

    element_separator = text[3]
    component_separator = text[104] if len(text) > 104 else ">"
    segment_terminator = text[105] if len(text) > 105 else ""

    if segment_terminator in {"", "\r", "\n"}:
        for candidate in ("~", "\n", "\r"):
            if candidate in text:
                segment_terminator = candidate
                break

    if not segment_terminator:
        raise ValueError("Unable to determine the segment terminator.")

    return {
        "element": element_separator,
        "component": component_separator,
        "segment": segment_terminator,
    }


def split_x12_segments(raw_text, delimiters=None):
    delimiters = delimiters or detect_x12_delimiters(raw_text)
    segment_terminator = delimiters["segment"]
    segment_strings = []
    for chunk in raw_text.replace("\ufeff", "").split(segment_terminator):
        cleaned = chunk.strip()
        if cleaned:
            segment_strings.append(cleaned)
    return segment_strings


def parse_x12_document(raw_text):
    delimiters = detect_x12_delimiters(raw_text)
    segment_strings = split_x12_segments(raw_text, delimiters)
    element_separator = delimiters["element"]
    segment_objects = []
    for raw_segment in segment_strings:
        elements = raw_segment.split(element_separator)
        segment_objects.append(
            {
                "raw": raw_segment,
                "tag": elements[0],
                "elements": elements,
            }
        )

    transactions = []
    isa_segment = None
    gs_segment = None
    current = None

    for segment in segment_objects:
        tag = segment["tag"]
        if tag == "ISA":
            isa_segment = segment
            continue
        if tag == "GS":
            gs_segment = segment
            continue
        if tag == "ST":
            current = {
                "delimiters": delimiters,
                "isa": isa_segment,
                "gs": gs_segment,
                "segments": [segment],
            }
            continue
        if current is None:
            continue

        current["segments"].append(segment)
        if tag == "SE":
            transactions.append(_parse_x12_transaction(current))
            current = None

    if not transactions:
        raise ValueError("No transaction set was found in the EDI payload.")
    return transactions


def _base_transaction(edi_format, transaction_type, *, delimiters=None, interchange=None, group=None, transaction=None, raw_transaction=""):
    return {
        "format": edi_format,
        "type": transaction_type,
        "delimiters": delimiters or {},
        "interchange": interchange or {},
        "group": group or {},
        "transaction": transaction or {},
        "shipment": {},
        "references": {"shipment_ref": "", "qualifiers": {}},
        "carrier": {},
        "parties": {},
        "events": [],
        "response": {},
        "invoice": {},
        "line_items": [],
        "document": {},
        "stops": [],
        "raw_transaction": raw_transaction,
    }


def _parse_x12_transaction(bundle):
    isa = bundle.get("isa") or {"elements": []}
    gs = bundle.get("gs") or {"elements": []}
    segments = bundle["segments"]
    st = segments[0]["elements"]
    transaction_type = _clean_text(_element(st, 1))

    parsed = _base_transaction(
        "X12",
        transaction_type,
        delimiters=bundle["delimiters"],
        interchange={
            "sender_id": _clean_text(_element(isa["elements"], 6)),
            "receiver_id": _clean_text(_element(isa["elements"], 8)),
            "control_number": _clean_text(_element(isa["elements"], 13)),
            "usage_indicator": _clean_text(_element(isa["elements"], 15)),
        },
        group={
            "functional_id": _clean_text(_element(gs["elements"], 1)),
            "sender_code": _clean_text(_element(gs["elements"], 2)),
            "receiver_code": _clean_text(_element(gs["elements"], 3)),
            "control_number": _clean_text(_element(gs["elements"], 6)),
            "version": _clean_text(_element(gs["elements"], 8)),
        },
        transaction={
            "control_number": _clean_text(_element(st, 2)),
            "version": _clean_text(_element(st, 3)),
        },
        raw_transaction=_serialize_segments(
            [segment["raw"] for segment in segments],
            bundle["delimiters"]["segment"],
        ),
    )

    parser = {
        "204": _parse_204,
        "210": _parse_210,
        "211": _parse_211,
        "214": _parse_214,
        "215": _parse_215,
        "850": _parse_850,
        "856": _parse_856,
        "990": _parse_990,
        "997": _parse_997,
    }.get(transaction_type)
    if parser:
        parsed.update(parser(segments))
    else:
        parsed["response"] = {"label": "Unsupported transaction"}

    return parsed


def _parse_204(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Booked",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "etd": "",
        "eta": "",
        "cargo_description": "",
        "carrier_scac": "",
        "carrier_name": "",
        "containers": "",
        "weight_kg": None,
        "volume_cbm": None,
        "notes": "",
        "mode": "FTL",
    }
    references = {}
    parties = {}
    stops = []
    shipment_dates = []
    notes = []
    cargo_lines = []
    current_stop = None
    current_party = None

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]

        if tag == "B2":
            shipment["carrier_scac"] = _first_present(_element(elements, 2), shipment["carrier_scac"])
            shipment["shipment_ref"] = _first_present(_element(elements, 4), _element(elements, 3), shipment["shipment_ref"])
        elif tag == "B2A":
            if _clean_text(_element(elements, 1)) == "01":
                shipment["status"] = "Cancelled"
        elif tag == "L11":
            qualifier = _clean_text(_element(elements, 2)) or "UN"
            value = _clean_text(_element(elements, 1))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "S5":
            current_stop = {
                "stop_number": _clean_text(_element(elements, 1)),
                "stop_reason": _clean_text(_element(elements, 2)),
                "parties": {},
                "dates": [],
            }
            stops.append(current_stop)
            current_party = None
        elif tag == "N1":
            current_party = _parse_party_segment(elements)
            container = current_stop["parties"] if current_stop else parties
            container[current_party["entity_code"] or f"PARTY{len(container) + 1}"] = current_party
            if current_party["entity_code"] in CARRIER_ENTITY_CODES:
                shipment["carrier_name"] = _first_present(current_party["name"], shipment["carrier_name"])
                shipment["carrier_scac"] = _first_present(current_party["id_code"], shipment["carrier_scac"])
        elif tag == "N3" and current_party:
            current_party["address_line_1"] = _clean_text(_element(elements, 1))
            current_party["address_line_2"] = _clean_text(_element(elements, 2))
        elif tag == "N4" and current_party:
            current_party["city"] = _clean_text(_element(elements, 1))
            current_party["state"] = _clean_text(_element(elements, 2))
            current_party["postal_code"] = _clean_text(_element(elements, 3))
            current_party["country"] = _clean_text(_element(elements, 4))
        elif tag == "G62":
            date_value = _parse_x12_date(_element(elements, 2))
            time_value = _parse_x12_time(_element(elements, 4) or _element(elements, 3))
            record = {
                "qualifier": _clean_text(_element(elements, 1)),
                "value": _combine_date_time(date_value, time_value),
            }
            if current_stop:
                current_stop["dates"].append(record)
            else:
                shipment_dates.append(record)
        elif tag == "AT8":
            shipment["weight_kg"] = shipment["weight_kg"] or _convert_weight_to_kg(
                _element(elements, 3),
                _element(elements, 2),
            )
            shipment["volume_cbm"] = shipment["volume_cbm"] or _convert_volume_to_cbm(
                _element(elements, 7),
                _element(elements, 6),
            )
        elif tag == "L5":
            description = _clean_text(_element(elements, 2))
            if description:
                cargo_lines.append(description)
        elif tag == "N7" and not shipment["containers"]:
            parts = [_clean_text(value) for value in elements[1:] if _clean_text(value)]
            shipment["containers"] = " ".join(parts[:3])
        elif tag == "NTE":
            note = _clean_text(_element(elements, 2))
            if note:
                notes.append(note)

    origin_party = (_candidate_parties(stops, ORIGIN_ENTITY_CODES, from_end=False)[1]) or _party_lookup(parties, ORIGIN_ENTITY_CODES)
    destination_party = (_candidate_parties(stops, DESTINATION_ENTITY_CODES, from_end=True)[1]) or _party_lookup(parties, DESTINATION_ENTITY_CODES)
    carrier_party = _party_lookup(parties, CARRIER_ENTITY_CODES)

    shipment["shipment_ref"] = _first_present(
        shipment["shipment_ref"],
        _choose_reference(references, "CN", "SI", "BM", "PO"),
    )
    shipment["shipper_name"] = _clean_text(origin_party.get("name") if origin_party else "")
    shipment["shipper_address"] = _address_label(origin_party)
    shipment["consignee_name"] = _clean_text(destination_party.get("name") if destination_party else "")
    shipment["consignee_address"] = _address_label(destination_party)
    shipment["origin_port"] = _location_label(origin_party)
    shipment["destination_port"] = _location_label(destination_party)
    shipment["etd"] = _first_present(
        _stop_date(stops, from_end=False, qualifiers={"10", "37", "38", "64", "86"}),
        next((item["value"] for item in shipment_dates if item["qualifier"] in {"10", "37", "38", "64", "86"} and item["value"]), ""),
    )
    shipment["eta"] = _first_present(
        _stop_date(stops, from_end=True, qualifiers={"17", "54", "63", "69", "70"}),
        next((item["value"] for item in shipment_dates if item["qualifier"] in {"17", "54", "63", "69", "70"} and item["value"]), ""),
    )
    shipment["cargo_description"] = ", ".join(_next_unique(cargo_lines))
    shipment["carrier_name"] = _first_present(shipment["carrier_name"], carrier_party.get("name") if carrier_party else "")
    shipment["carrier_scac"] = _first_present(shipment["carrier_scac"], carrier_party.get("id_code") if carrier_party else "")
    shipment["notes"] = " | ".join(_next_unique(notes))

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "carrier": {"scac": shipment["carrier_scac"], "name": shipment["carrier_name"]},
        "parties": {"shipper": origin_party or {}, "consignee": destination_party or {}, "carrier": carrier_party or {}},
        "events": [],
        "response": {"label": "Load tender received"},
        "stops": stops,
    }


def _parse_210(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Active",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "cargo_description": "",
        "carrier_scac": "",
        "carrier_name": "",
        "weight_kg": None,
        "notes": "",
    }
    invoice = {"invoice_number": "", "amount": None, "currency": "USD", "invoice_date": ""}
    references = {}
    parties = {}
    cargo_lines = []
    current_party = None

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "B3":
            invoice["invoice_number"] = _clean_text(_element(elements, 1))
            shipment["shipment_ref"] = _first_present(_element(elements, 2), _element(elements, 3), _element(elements, 4), shipment["shipment_ref"])
            invoice["invoice_date"] = _parse_x12_date(_first_present(_element(elements, 6), _element(elements, 5)))
            invoice["amount"] = _parse_number(_first_present(_element(elements, 7), _element(elements, 8), _element(elements, 6)))
            currency = _first_present(_element(elements, 8), _element(elements, 9))
            if len(currency) == 3 and currency.isalpha():
                invoice["currency"] = currency.upper()
            shipment["carrier_scac"] = _first_present(_element(elements, 11), shipment["carrier_scac"])
        elif tag == "L11":
            qualifier = _clean_text(_element(elements, 2)) or "UN"
            value = _clean_text(_element(elements, 1))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "N1":
            current_party = _parse_party_segment(elements)
            parties[current_party["entity_code"] or f"PARTY{len(parties) + 1}"] = current_party
            if current_party["entity_code"] in CARRIER_ENTITY_CODES:
                shipment["carrier_name"] = _first_present(current_party["name"], shipment["carrier_name"])
                shipment["carrier_scac"] = _first_present(current_party["id_code"], shipment["carrier_scac"])
        elif tag == "N3" and current_party:
            current_party["address_line_1"] = _clean_text(_element(elements, 1))
            current_party["address_line_2"] = _clean_text(_element(elements, 2))
        elif tag == "N4" and current_party:
            current_party["city"] = _clean_text(_element(elements, 1))
            current_party["state"] = _clean_text(_element(elements, 2))
            current_party["postal_code"] = _clean_text(_element(elements, 3))
            current_party["country"] = _clean_text(_element(elements, 4))
        elif tag == "L5":
            description = _clean_text(_element(elements, 2))
            if description:
                cargo_lines.append(description)
        elif tag == "AT8":
            shipment["weight_kg"] = shipment["weight_kg"] or _convert_weight_to_kg(_element(elements, 3), _element(elements, 2))
        elif tag == "NTE":
            note = _clean_text(_element(elements, 2))
            if note:
                shipment["notes"] = " | ".join(_next_unique([shipment["notes"], note]))

    shipper = _party_lookup(parties, ORIGIN_ENTITY_CODES)
    consignee = _party_lookup(parties, DESTINATION_ENTITY_CODES)
    carrier = _party_lookup(parties, CARRIER_ENTITY_CODES)

    shipment["shipment_ref"] = _first_present(shipment["shipment_ref"], _choose_reference(references, "CN", "SI", "BM", "PO"))
    shipment["shipper_name"] = _clean_text(shipper.get("name") if shipper else "")
    shipment["shipper_address"] = _address_label(shipper)
    shipment["consignee_name"] = _clean_text(consignee.get("name") if consignee else "")
    shipment["consignee_address"] = _address_label(consignee)
    shipment["origin_port"] = _location_label(shipper)
    shipment["destination_port"] = _location_label(consignee)
    shipment["carrier_name"] = _first_present(shipment["carrier_name"], carrier.get("name") if carrier else "")
    shipment["carrier_scac"] = _first_present(shipment["carrier_scac"], carrier.get("id_code") if carrier else "")
    shipment["cargo_description"] = ", ".join(_next_unique(cargo_lines))

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "carrier": {"scac": shipment["carrier_scac"], "name": shipment["carrier_name"]},
        "parties": {"shipper": shipper or {}, "consignee": consignee or {}, "carrier": carrier or {}},
        "events": [],
        "response": {"label": "Freight invoice received"},
        "invoice": invoice,
        "stops": [],
    }


def generate_204(shipment, sender_id="SENDER", receiver_id="RECEIVER", control_numbers=None, current_dt=None):
    shipment = shipment or {}
    carrier_scac = _clean_text(shipment.get("carrier_scac"))
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    carrier_name = _clean_text(shipment.get("carrier_name"))
    receiver = _clean_text(receiver_id) or carrier_scac or "RECEIVER"

    body_segments = [
        f"B2**{carrier_scac}**{shipment_ref}",
        "B2A*00*LT",
    ]
    if shipment.get("shipper_name"):
        body_segments.append(f"N1*SH*{_segment_text(shipment.get('shipper_name'))}")
    if shipment.get("shipper_address"):
        body_segments.append(f"N3*{_segment_text(shipment.get('shipper_address'))}")
    if shipment.get("origin_port"):
        location = _split_location(shipment.get("origin_port"))
        body_segments.append(
            f"N4*{_segment_text(location.get('city'))}*{_segment_text(location.get('state'))}*{_segment_text(location.get('postal'))}"
        )
    if shipment.get("consignee_name"):
        body_segments.append(f"N1*CN*{_segment_text(shipment.get('consignee_name'))}")
    if shipment.get("consignee_address"):
        body_segments.append(f"N3*{_segment_text(shipment.get('consignee_address'))}")
    if shipment.get("destination_port"):
        location = _split_location(shipment.get("destination_port"))
        body_segments.append(
            f"N4*{_segment_text(location.get('city'))}*{_segment_text(location.get('state'))}*{_segment_text(location.get('postal'))}"
        )
    if carrier_name or carrier_scac:
        body_segments.append(f"N1*CA*{_segment_text(carrier_name)}*2*{carrier_scac}")
    if shipment.get("etd"):
        body_segments.append(f"G62*10*{_format_outbound_date(shipment.get('etd'))}")
    if shipment.get("eta"):
        body_segments.append(f"G62*17*{_format_outbound_date(shipment.get('eta'))}")
    if shipment.get("cargo_description"):
        body_segments.append(f"L5*1*{_segment_text(shipment.get('cargo_description'))}")
    if shipment.get("weight_kg"):
        body_segments.append(f"AT8*G*KG*{int(round(float(shipment.get('weight_kg') or 0)))}")
    if shipment.get("notes"):
        body_segments.append(f"NTE*GEN*{_segment_text(shipment.get('notes'))}")

    return _build_x12_envelope(
        "SM",
        "204",
        sender_id,
        receiver,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_997(parsed_transaction, sender_id="", receiver_id="", control_numbers=None, current_dt=None):
    parsed_transaction = parsed_transaction or {}
    interchange = parsed_transaction.get("interchange") or {}
    group = parsed_transaction.get("group") or {}
    transaction = parsed_transaction.get("transaction") or {}

    outbound_sender = _clean_text(sender_id) or _clean_text(interchange.get("receiver_id")) or "RECEIVER"
    outbound_receiver = _clean_text(receiver_id) or _clean_text(interchange.get("sender_id")) or "SENDER"
    functional_id = _clean_text(group.get("functional_id")) or "SM"
    group_control = _clean_text(group.get("control_number")) or "1"
    transaction_type = _clean_text(parsed_transaction.get("type")) or "000"
    transaction_control = _clean_text(transaction.get("control_number")) or "0001"

    body_segments = [
        f"AK1*{functional_id}*{group_control}",
        f"AK2*{transaction_type}*{transaction_control}",
        "AK5*A",
        "AK9*A*1*1*1",
    ]
    return _build_x12_envelope(
        "FA",
        "997",
        outbound_sender,
        outbound_receiver,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def _parse_211(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Booked",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "etd": "",
        "eta": "",
        "cargo_description": "",
        "carrier_scac": "",
        "carrier_name": "",
        "weight_kg": None,
        "volume_cbm": None,
        "notes": "",
    }
    references = {}
    parties = {}
    document = {"bol_number": ""}
    cargo_lines = []
    notes = []
    current_party = None

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "BOL":
            document["bol_number"] = _clean_text(_element(elements, 1))
            shipment["shipment_ref"] = _first_present(_element(elements, 2), shipment["shipment_ref"])
        elif tag == "L11":
            qualifier = _clean_text(_element(elements, 2)) or "UN"
            value = _clean_text(_element(elements, 1))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "N1":
            current_party = _parse_party_segment(elements)
            parties[current_party["entity_code"] or f"PARTY{len(parties) + 1}"] = current_party
            if current_party["entity_code"] in CARRIER_ENTITY_CODES:
                shipment["carrier_name"] = _first_present(current_party["name"], shipment["carrier_name"])
                shipment["carrier_scac"] = _first_present(current_party["id_code"], shipment["carrier_scac"])
        elif tag == "N3" and current_party:
            current_party["address_line_1"] = _clean_text(_element(elements, 1))
            current_party["address_line_2"] = _clean_text(_element(elements, 2))
        elif tag == "N4" and current_party:
            current_party["city"] = _clean_text(_element(elements, 1))
            current_party["state"] = _clean_text(_element(elements, 2))
            current_party["postal_code"] = _clean_text(_element(elements, 3))
            current_party["country"] = _clean_text(_element(elements, 4))
        elif tag == "G62":
            qualifier = _clean_text(_element(elements, 1))
            date_value = _parse_x12_date(_element(elements, 2))
            if qualifier in {"10", "37", "38"}:
                shipment["etd"] = _first_present(shipment["etd"], date_value)
            elif qualifier in {"17", "54", "63"}:
                shipment["eta"] = _first_present(shipment["eta"], date_value)
        elif tag == "AT8":
            shipment["weight_kg"] = shipment["weight_kg"] or _convert_weight_to_kg(_element(elements, 3), _element(elements, 2))
            shipment["volume_cbm"] = shipment["volume_cbm"] or _convert_volume_to_cbm(_element(elements, 7), _element(elements, 6))
        elif tag == "L5":
            description = _clean_text(_element(elements, 2))
            if description:
                cargo_lines.append(description)
        elif tag == "NTE":
            note = _clean_text(_element(elements, 2))
            if note:
                notes.append(note)

    shipper = _party_lookup(parties, ORIGIN_ENTITY_CODES)
    consignee = _party_lookup(parties, DESTINATION_ENTITY_CODES)
    carrier = _party_lookup(parties, CARRIER_ENTITY_CODES)

    shipment["shipment_ref"] = _first_present(shipment["shipment_ref"], _choose_reference(references, "CN", "SI", "BM", "PO"))
    shipment["shipper_name"] = _clean_text(shipper.get("name") if shipper else "")
    shipment["shipper_address"] = _address_label(shipper)
    shipment["consignee_name"] = _clean_text(consignee.get("name") if consignee else "")
    shipment["consignee_address"] = _address_label(consignee)
    shipment["origin_port"] = _location_label(shipper)
    shipment["destination_port"] = _location_label(consignee)
    shipment["carrier_name"] = _first_present(shipment["carrier_name"], carrier.get("name") if carrier else "")
    shipment["carrier_scac"] = _first_present(shipment["carrier_scac"], carrier.get("id_code") if carrier else "")
    shipment["cargo_description"] = ", ".join(_next_unique(cargo_lines))
    shipment["notes"] = " | ".join(_next_unique(notes))

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "carrier": {"scac": shipment["carrier_scac"], "name": shipment["carrier_name"]},
        "parties": {"shipper": shipper or {}, "consignee": consignee or {}, "carrier": carrier or {}},
        "events": [],
        "response": {"label": "Bill of lading received"},
        "document": document,
        "stops": [],
    }


def _parse_214(segments):
    references = {}
    shipment_ref = ""
    carrier_scac = ""
    pro_number = ""
    events = []
    current_event = None

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]

        if tag == "B10":
            pro_number = _clean_text(_element(elements, 1))
            shipment_ref = _first_present(_element(elements, 2), shipment_ref)
            carrier_scac = _first_present(_element(elements, 3), carrier_scac)
        elif tag == "L11":
            qualifier = _clean_text(_element(elements, 2)) or "UN"
            value = _clean_text(_element(elements, 1))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "LX":
            if current_event and current_event.get("status_code"):
                events.append(current_event)
            current_event = {"sequence": _clean_text(_element(elements, 1))}
        elif tag == "AT7":
            if current_event and current_event.get("status_code"):
                events.append(current_event)
                current_event = {}
            status_code = _first_present(_element(elements, 1), _element(elements, 2), _element(elements, 3))
            mapping = AT7_STATUS_MAP.get(status_code, {})
            current_event = {
                "sequence": current_event.get("sequence", "") if current_event else "",
                "status_code": status_code,
                "status": mapping.get("status", ""),
                "description": mapping.get("label", f"Status update {status_code}".strip()),
                "event_date": _combine_date_time(
                    _parse_x12_date(_element(elements, 5)),
                    _parse_x12_time(_element(elements, 6)),
                ),
                "location": "",
            }
        elif tag == "MS1":
            if current_event is None:
                current_event = {}
            city = _clean_text(_element(elements, 1))
            state = _clean_text(_element(elements, 2))
            current_event["location"] = ", ".join(part for part in [city, state] if part)

    if current_event:
        events.append(current_event)

    shipment_ref = _first_present(shipment_ref, _choose_reference(references, "CN", "SI", "BM", "PO"))
    latest_event = next((event for event in reversed(events) if event.get("status") or event.get("description")), {})

    return {
        "shipment": {
            "shipment_ref": shipment_ref,
            "status": latest_event.get("status", ""),
            "carrier_scac": carrier_scac,
        },
        "references": {"shipment_ref": shipment_ref, "pro_number": pro_number, "qualifiers": references},
        "carrier": {"scac": carrier_scac, "name": ""},
        "parties": {},
        "events": events,
        "response": {"label": latest_event.get("description", "Shipment status update")},
        "stops": [],
    }


def _parse_215(segments):
    references = {}
    shipment_ref = ""
    carrier_scac = ""
    status_code = ""
    event_date = ""
    location = ""

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "B4":
            shipment_ref = _first_present(_element(elements, 1), _element(elements, 2), shipment_ref)
            carrier_scac = _first_present(_element(elements, 2), _element(elements, 3), carrier_scac)
        elif tag in {"L11", "N9"}:
            qualifier = _clean_text(_element(elements, 2) or _element(elements, 1)) or "UN"
            value = _clean_text(_element(elements, 1 if tag == "L11" else 2))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "Q7":
            status_code = _first_present(_element(elements, 1), _element(elements, 2), status_code)
        elif tag == "DTM":
            event_date = _combine_date_time(
                _parse_x12_date(_element(elements, 2)),
                _parse_x12_time(_element(elements, 3)),
            )
        elif tag == "R4":
            city = _first_present(_element(elements, 4), _element(elements, 3), _element(elements, 2))
            state = _clean_text(_element(elements, 5))
            location = ", ".join(part for part in [city, state] if part)

    shipment_ref = _first_present(shipment_ref, _choose_reference(references, "CN", "SI", "BM", "PO"))
    mapping = Q7_STATUS_MAP.get(status_code, {})
    event = {
        "status_code": status_code,
        "status": mapping.get("status", ""),
        "description": mapping.get("label", f"Ocean status update {status_code or ''}".strip()),
        "event_date": event_date,
        "location": location,
    }
    return {
        "shipment": {
            "shipment_ref": shipment_ref,
            "status": event["status"],
            "carrier_scac": carrier_scac,
            "mode": "Ocean",
        },
        "references": {"shipment_ref": shipment_ref, "qualifiers": references},
        "carrier": {"scac": carrier_scac, "name": ""},
        "parties": {},
        "events": [event] if any(event.values()) else [],
        "response": {"label": event["description"] or "Ocean shipment status update"},
        "stops": [],
    }


def _parse_850(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Booked",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "etd": "",
        "eta": "",
        "cargo_description": "",
        "notes": "",
    }
    references = {}
    parties = {}
    line_items = []
    current_party = None
    current_line = None
    document = {"po_number": "", "order_date": ""}

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "BEG":
            document["po_number"] = _clean_text(_element(elements, 3))
            document["order_date"] = _parse_x12_date(_element(elements, 5))
            shipment["shipment_ref"] = _first_present(shipment["shipment_ref"], document["po_number"])
        elif tag in {"REF", "L11"}:
            qualifier = _clean_text(_element(elements, 1 if tag == "REF" else 2)) or "UN"
            value = _clean_text(_element(elements, 2 if tag == "REF" else 1))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "N1":
            current_party = _parse_party_segment(elements)
            parties[current_party["entity_code"] or f"PARTY{len(parties) + 1}"] = current_party
        elif tag == "N3" and current_party:
            current_party["address_line_1"] = _clean_text(_element(elements, 1))
            current_party["address_line_2"] = _clean_text(_element(elements, 2))
        elif tag == "N4" and current_party:
            current_party["city"] = _clean_text(_element(elements, 1))
            current_party["state"] = _clean_text(_element(elements, 2))
            current_party["postal_code"] = _clean_text(_element(elements, 3))
            current_party["country"] = _clean_text(_element(elements, 4))
        elif tag == "DTM":
            qualifier = _clean_text(_element(elements, 1))
            date_value = _parse_x12_date(_element(elements, 2))
            if qualifier in {"010", "002"}:
                shipment["etd"] = _first_present(shipment["etd"], date_value)
            elif qualifier in {"017", "067", "063"}:
                shipment["eta"] = _first_present(shipment["eta"], date_value)
        elif tag == "PO1":
            current_line = {
                "line_number": _clean_text(_element(elements, 1)),
                "quantity": _parse_number(_element(elements, 2)),
                "uom": _clean_text(_element(elements, 3)),
                "sku": _first_present(_element(elements, 7), _element(elements, 9), _element(elements, 11)),
            }
            line_items.append(current_line)
        elif tag == "PID" and current_line:
            current_line["description"] = _first_present(_element(elements, 5), _element(elements, 4))

    shipper = _party_lookup(parties, {"SF", "SH", "VN"})
    consignee = _party_lookup(parties, {"ST", "CN", "BT"})
    shipment["shipment_ref"] = _first_present(_choose_reference(references, "CN", "PO"), shipment["shipment_ref"])
    shipment["shipper_name"] = _clean_text(shipper.get("name") if shipper else "")
    shipment["shipper_address"] = _address_label(shipper)
    shipment["consignee_name"] = _clean_text(consignee.get("name") if consignee else "")
    shipment["consignee_address"] = _address_label(consignee)
    shipment["origin_port"] = _location_label(shipper)
    shipment["destination_port"] = _location_label(consignee)
    shipment["cargo_description"] = ", ".join(_next_unique(item.get("description") for item in line_items))

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "parties": {"shipper": shipper or {}, "consignee": consignee or {}},
        "events": [],
        "response": {"label": "Purchase order received"},
        "document": document,
        "line_items": line_items,
        "stops": [],
    }


def _parse_856(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Active",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "etd": "",
        "eta": "",
        "cargo_description": "",
        "containers": "",
        "weight_kg": None,
        "notes": "",
    }
    references = {}
    parties = {}
    line_items = []
    current_party = None
    current_line = None
    document = {"asn_number": "", "document_date": ""}

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "BSN":
            document["asn_number"] = _clean_text(_element(elements, 2))
            document["document_date"] = _combine_date_time(
                _parse_x12_date(_element(elements, 3)),
                _parse_x12_time(_element(elements, 4)),
            )
        elif tag == "REF":
            qualifier = _clean_text(_element(elements, 1)) or "UN"
            value = _clean_text(_element(elements, 2))
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "N1":
            current_party = _parse_party_segment(elements)
            parties[current_party["entity_code"] or f"PARTY{len(parties) + 1}"] = current_party
        elif tag == "N3" and current_party:
            current_party["address_line_1"] = _clean_text(_element(elements, 1))
            current_party["address_line_2"] = _clean_text(_element(elements, 2))
        elif tag == "N4" and current_party:
            current_party["city"] = _clean_text(_element(elements, 1))
            current_party["state"] = _clean_text(_element(elements, 2))
            current_party["postal_code"] = _clean_text(_element(elements, 3))
            current_party["country"] = _clean_text(_element(elements, 4))
        elif tag == "DTM":
            qualifier = _clean_text(_element(elements, 1))
            date_value = _parse_x12_date(_element(elements, 2))
            if qualifier in {"011", "067"}:
                shipment["etd"] = _first_present(shipment["etd"], date_value)
            elif qualifier in {"017", "063"}:
                shipment["eta"] = _first_present(shipment["eta"], date_value)
        elif tag == "LIN":
            current_line = {"sku": _first_present(_element(elements, 3), _element(elements, 5)), "description": ""}
            line_items.append(current_line)
        elif tag == "PID" and current_line:
            current_line["description"] = _first_present(_element(elements, 5), _element(elements, 4))
        elif tag == "SN1" and current_line:
            current_line["quantity"] = _parse_number(_element(elements, 3))
            current_line["uom"] = _clean_text(_element(elements, 4))
            if current_line["uom"] in {"KG", "LB"} and shipment["weight_kg"] is None:
                shipment["weight_kg"] = _convert_weight_to_kg(current_line["quantity"], current_line["uom"])
        elif tag == "TD1" and not shipment["containers"]:
            shipment["containers"] = " ".join(_next_unique(elements[1:3]))

    shipper = _party_lookup(parties, ORIGIN_ENTITY_CODES)
    consignee = _party_lookup(parties, DESTINATION_ENTITY_CODES)
    shipment["shipment_ref"] = _first_present(_choose_reference(references, "CN", "SI", "BM", "PO"), document["asn_number"])
    shipment["shipper_name"] = _clean_text(shipper.get("name") if shipper else "")
    shipment["shipper_address"] = _address_label(shipper)
    shipment["consignee_name"] = _clean_text(consignee.get("name") if consignee else "")
    shipment["consignee_address"] = _address_label(consignee)
    shipment["origin_port"] = _location_label(shipper)
    shipment["destination_port"] = _location_label(consignee)
    shipment["cargo_description"] = ", ".join(_next_unique(item.get("description") or item.get("sku") for item in line_items))

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "parties": {"shipper": shipper or {}, "consignee": consignee or {}},
        "events": [],
        "response": {"label": "Advance ship notice received"},
        "document": document,
        "line_items": line_items,
        "stops": [],
    }


def _parse_990(segments):
    references = {}
    shipment_ref = ""
    carrier_scac = ""
    response_code = ""

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "B1":
            carrier_scac = _first_present(_element(elements, 1), carrier_scac)
            shipment_ref = _first_present(_element(elements, 2), shipment_ref)
            response_code = _first_present(_element(elements, 4), _element(elements, 3), response_code)
        elif tag == "L11":
            qualifier = _clean_text(_element(elements, 2)) or "UN"
            value = _clean_text(_element(elements, 1))
            if value:
                references.setdefault(qualifier, []).append(value)

    shipment_ref = _first_present(shipment_ref, _choose_reference(references, "CN", "SI", "BM", "PO"))
    response = TENDER_RESPONSE_MAP.get(
        response_code,
        {"accepted": False, "status": "", "label": f"Tender response {response_code or 'unknown'}"},
    )

    return {
        "shipment": {"shipment_ref": shipment_ref, "status": response.get("status", ""), "carrier_scac": carrier_scac},
        "references": {"shipment_ref": shipment_ref, "qualifiers": references},
        "carrier": {"scac": carrier_scac, "name": ""},
        "parties": {},
        "events": [],
        "response": {
            "code": response_code,
            "accepted": response.get("accepted", False),
            "label": response.get("label", "Tender response"),
        },
        "stops": [],
    }


def _parse_997(segments):
    ack = {
        "functional_id": "",
        "group_control_number": "",
        "transaction_type": "",
        "transaction_control_number": "",
        "transaction_ack_code": "",
        "group_ack_code": "",
    }

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "AK1":
            ack["functional_id"] = _clean_text(_element(elements, 1))
            ack["group_control_number"] = _clean_text(_element(elements, 2))
        elif tag == "AK2":
            ack["transaction_type"] = _clean_text(_element(elements, 1))
            ack["transaction_control_number"] = _clean_text(_element(elements, 2))
        elif tag == "AK5":
            ack["transaction_ack_code"] = _clean_text(_element(elements, 1))
        elif tag == "AK9":
            ack["group_ack_code"] = _clean_text(_element(elements, 1))

    return {
        "shipment": {},
        "references": {"shipment_ref": "", "qualifiers": {}},
        "carrier": {},
        "parties": {},
        "events": [],
        "response": {
            "label": "Functional acknowledgement received",
            "acknowledged_type": ack["transaction_type"],
            "ack_code": ack["transaction_ack_code"],
            "group_ack_code": ack["group_ack_code"],
        },
        "document": ack,
        "stops": [],
    }


def detect_edifact_delimiters(raw_text):
    text = (raw_text or "").replace("\ufeff", "").lstrip()
    delimiters = {
        "component": ":",
        "element": "+",
        "decimal": ".",
        "release": "?",
        "reserved": " ",
        "segment": "'",
    }
    if text.startswith("UNA") and len(text) >= 9:
        delimiters = {
            "component": text[3],
            "element": text[4],
            "decimal": text[5],
            "release": text[6],
            "reserved": text[7],
            "segment": text[8],
        }
    return delimiters


def _split_released(text, separator, release_char):
    parts = []
    current = []
    released = False
    for char in text:
        if released:
            current.append(char)
            released = False
            continue
        if char == release_char:
            released = True
            continue
        if char == separator:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def split_edifact_segments(raw_text, delimiters=None):
    delimiters = delimiters or detect_edifact_delimiters(raw_text)
    text = (raw_text or "").replace("\ufeff", "").replace("\r", "").replace("\n", "")
    if text.startswith("UNA") and len(text) >= 9:
        text = text[9:]
    segments = []
    for segment in _split_released(text, delimiters["segment"], delimiters["release"]):
        cleaned = segment.strip()
        if cleaned:
            segments.append(cleaned)
    return segments


def parse_edifact_document(raw_text):
    delimiters = detect_edifact_delimiters(raw_text)
    segment_strings = split_edifact_segments(raw_text, delimiters)
    segment_objects = []
    for raw_segment in segment_strings:
        elements = _split_released(raw_segment, delimiters["element"], delimiters["release"])
        segment_objects.append({"raw": raw_segment, "tag": elements[0], "elements": elements})

    messages = []
    unb_segment = None
    current = None
    for segment in segment_objects:
        tag = segment["tag"]
        if tag == "UNB":
            unb_segment = segment
            continue
        if tag == "UNH":
            current = {"delimiters": delimiters, "unb": unb_segment, "segments": [segment]}
            continue
        if current is None:
            continue
        current["segments"].append(segment)
        if tag == "UNT":
            messages.append(_parse_edifact_message(current))
            current = None

    if not messages:
        raise ValueError("No EDIFACT message was found in the EDI payload.")
    return messages


def _parse_edifact_message(bundle):
    unb = bundle.get("unb") or {"elements": []}
    segments = bundle["segments"]
    unh = segments[0]["elements"]
    type_components = _component(unh, 2)
    message_type = _clean_text(type_components[0]).upper()
    version = ":".join(component for component in type_components[1:] if component)

    parsed = _base_transaction(
        "EDIFACT",
        message_type,
        delimiters=bundle["delimiters"],
        interchange={
            "sender_id": _edifact_component(_element(unb["elements"], 2), 0),
            "receiver_id": _edifact_component(_element(unb["elements"], 3), 0),
            "control_number": _clean_text(_element(unb["elements"], 5)),
            "syntax": _clean_text(_element(unb["elements"], 1)),
        },
        group={
            "functional_id": message_type,
            "control_number": _clean_text(_element(unb["elements"], 5)),
            "version": version,
        },
        transaction={
            "control_number": _clean_text(_element(unh, 1)),
            "version": version,
        },
        raw_transaction=_serialize_edifact_segments([segment["raw"] for segment in segments]),
    )

    parser = {
        "IFTMIN": _parse_iftmin,
        "IFTSTA": _parse_iftsta,
        "INVOIC": _parse_invoic,
    }.get(message_type)
    if parser:
        parsed.update(parser(segments))
    else:
        parsed["response"] = {"label": "Unsupported EDIFACT message"}
    return parsed


def _parse_iftmin(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Booked",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "etd": "",
        "eta": "",
        "cargo_description": "",
        "carrier_name": "",
        "carrier_scac": "",
        "containers": "",
        "notes": "",
        "mode": "Ocean",
    }
    references = {}
    parties = {}
    document = {"booking_number": "", "document_date": ""}

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "BGM":
            document["booking_number"] = _clean_text(_element(elements, 2))
        elif tag == "RFF":
            qualifier = _edifact_component(_element(elements, 1), 0) or "UN"
            value = _edifact_component(_element(elements, 1), 1)
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "DTM":
            qualifier = _edifact_component(_element(elements, 1), 0)
            value = _edifact_component(_element(elements, 1), 1)
            fmt = _edifact_component(_element(elements, 1), 2)
            parsed_value = _parse_edifact_date(value, fmt)
            if qualifier == "137":
                document["document_date"] = parsed_value
            elif qualifier in {"133", "10"}:
                shipment["etd"] = _first_present(shipment["etd"], parsed_value)
            elif qualifier in {"132", "17"}:
                shipment["eta"] = _first_present(shipment["eta"], parsed_value)
        elif tag == "NAD":
            party = _parse_edifact_party_segment(elements)
            parties[party["entity_code"] or f"PARTY{len(parties) + 1}"] = party
            if party["entity_code"] in EDIFACT_PARTY_CODES["carrier"]:
                shipment["carrier_name"] = _first_present(party["name"], shipment["carrier_name"])
                shipment["carrier_scac"] = _first_present(party["id_code"], shipment["carrier_scac"])
        elif tag == "LOC":
            qualifier = _clean_text(_element(elements, 1))
            value = _first_present(_edifact_component(_element(elements, 2), 0), _element(elements, 2))
            if qualifier == "9":
                shipment["origin_port"] = _first_present(shipment["origin_port"], value)
            elif qualifier == "11":
                shipment["destination_port"] = _first_present(shipment["destination_port"], value)
        elif tag == "GDS":
            shipment["cargo_description"] = _first_present(shipment["cargo_description"], _clean_text(_element(elements, 1)))
        elif tag == "GID":
            shipment["containers"] = _first_present(shipment["containers"], _clean_text(_element(elements, 2)))
        elif tag == "FTX":
            shipment["notes"] = " | ".join(_next_unique([shipment["notes"], _clean_text(_element(elements, 4))]))

    shipper = _party_lookup(parties, EDIFACT_PARTY_CODES["shipper"])
    consignee = _party_lookup(parties, EDIFACT_PARTY_CODES["consignee"])
    carrier = _party_lookup(parties, EDIFACT_PARTY_CODES["carrier"])
    shipment["shipment_ref"] = _first_present(_choose_reference(references, "CN", "BM", "SI"), document["booking_number"])
    shipment["shipper_name"] = _clean_text(shipper.get("name") if shipper else "")
    shipment["shipper_address"] = _address_label(shipper)
    shipment["consignee_name"] = _clean_text(consignee.get("name") if consignee else "")
    shipment["consignee_address"] = _address_label(consignee)
    shipment["origin_port"] = _first_present(shipment["origin_port"], _location_label(shipper))
    shipment["destination_port"] = _first_present(shipment["destination_port"], _location_label(consignee))
    shipment["carrier_name"] = _first_present(shipment["carrier_name"], carrier.get("name") if carrier else "")
    shipment["carrier_scac"] = _first_present(shipment["carrier_scac"], carrier.get("id_code") if carrier else "")

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "carrier": {"scac": shipment["carrier_scac"], "name": shipment["carrier_name"]},
        "parties": {"shipper": shipper or {}, "consignee": consignee or {}, "carrier": carrier or {}},
        "events": [],
        "response": {"label": "Freight booking instruction received"},
        "document": document,
        "stops": [],
    }


def _parse_iftsta(segments):
    references = {}
    parties = {}
    shipment_ref = ""
    status_code = ""
    event_date = ""
    location = ""
    carrier_name = ""
    carrier_scac = ""

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "RFF":
            qualifier = _edifact_component(_element(elements, 1), 0) or "UN"
            value = _edifact_component(_element(elements, 1), 1)
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "STS":
            status_code = _first_present(
                _edifact_component(_element(elements, 2), 0),
                _edifact_component(_element(elements, 1), 1),
                _clean_text(_element(elements, 2)),
            )
        elif tag == "DTM":
            value = _edifact_component(_element(elements, 1), 1)
            fmt = _edifact_component(_element(elements, 1), 2)
            event_date = _parse_edifact_date(value, fmt)
        elif tag == "LOC":
            qualifier = _clean_text(_element(elements, 1))
            if qualifier in {"9", "11", "7"}:
                location = _first_present(_edifact_component(_element(elements, 2), 0), _element(elements, 2))
        elif tag == "NAD":
            party = _parse_edifact_party_segment(elements)
            parties[party["entity_code"] or f"PARTY{len(parties) + 1}"] = party
            if party["entity_code"] in EDIFACT_PARTY_CODES["carrier"]:
                carrier_name = _first_present(party["name"], carrier_name)
                carrier_scac = _first_present(party["id_code"], carrier_scac)

    shipment_ref = _choose_reference(references, "CN", "BM", "SI")
    mapping = EDIFACT_STATUS_MAP.get(status_code.upper(), {})
    event = {
        "status_code": status_code,
        "status": mapping.get("status", ""),
        "description": mapping.get("label", f"Freight status update {status_code or ''}".strip()),
        "event_date": event_date,
        "location": location,
    }
    return {
        "shipment": {
            "shipment_ref": shipment_ref,
            "status": event["status"],
            "carrier_name": carrier_name,
            "carrier_scac": carrier_scac,
        },
        "references": {"shipment_ref": shipment_ref, "qualifiers": references},
        "carrier": {"scac": carrier_scac, "name": carrier_name},
        "parties": {"carrier": _party_lookup(parties, EDIFACT_PARTY_CODES["carrier"]) or {}},
        "events": [event] if any(event.values()) else [],
        "response": {"label": event["description"] or "Freight status update"},
        "stops": [],
    }


def _parse_invoic(segments):
    shipment = {
        "shipment_ref": "",
        "status": "Active",
        "shipper_name": "",
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "cargo_description": "",
        "notes": "",
    }
    references = {}
    parties = {}
    invoice = {"invoice_number": "", "amount": None, "currency": "USD", "invoice_date": ""}

    for segment in segments:
        elements = segment["elements"]
        tag = segment["tag"]
        if tag == "BGM":
            invoice["invoice_number"] = _clean_text(_element(elements, 2))
        elif tag == "RFF":
            qualifier = _edifact_component(_element(elements, 1), 0) or "UN"
            value = _edifact_component(_element(elements, 1), 1)
            if value:
                references.setdefault(qualifier, []).append(value)
        elif tag == "MOA":
            qualifier = _edifact_component(_element(elements, 1), 0)
            if qualifier == "9":
                invoice["amount"] = _parse_number(_edifact_component(_element(elements, 1), 1))
        elif tag == "CUX":
            currency = _edifact_component(_element(elements, 1), 1) or _edifact_component(_element(elements, 1), 0)
            if len(currency) == 3:
                invoice["currency"] = currency.upper()
        elif tag == "DTM":
            qualifier = _edifact_component(_element(elements, 1), 0)
            value = _edifact_component(_element(elements, 1), 1)
            fmt = _edifact_component(_element(elements, 1), 2)
            if qualifier == "137":
                invoice["invoice_date"] = _parse_edifact_date(value, fmt)
        elif tag == "NAD":
            party = _parse_edifact_party_segment(elements)
            parties[party["entity_code"] or f"PARTY{len(parties) + 1}"] = party

    shipper = _party_lookup(parties, EDIFACT_PARTY_CODES["shipper"])
    consignee = _party_lookup(parties, EDIFACT_PARTY_CODES["consignee"])
    shipment["shipment_ref"] = _choose_reference(references, "CN", "BM", "SI")
    shipment["shipper_name"] = _clean_text(shipper.get("name") if shipper else "")
    shipment["shipper_address"] = _address_label(shipper)
    shipment["consignee_name"] = _clean_text(consignee.get("name") if consignee else "")
    shipment["consignee_address"] = _address_label(consignee)
    shipment["origin_port"] = _location_label(shipper)
    shipment["destination_port"] = _location_label(consignee)

    return {
        "shipment": shipment,
        "references": {"shipment_ref": shipment["shipment_ref"], "qualifiers": references},
        "parties": {"shipper": shipper or {}, "consignee": consignee or {}},
        "events": [],
        "response": {"label": "Invoice received"},
        "invoice": invoice,
        "stops": [],
    }


def parse_edi_document(raw_text):
    edi_format = detect_edi_format(raw_text)
    if edi_format == "X12":
        return parse_x12_document(raw_text)
    return parse_edifact_document(raw_text)


def parse_edi(raw_text):
    transactions = parse_edi_document(raw_text)
    if len(transactions) == 1:
        return transactions[0]
    return {"transactions": transactions}


def detect_type(raw_text):
    transactions = parse_edi_document(raw_text)
    return transactions[0]["type"] if transactions else "UNKNOWN"


def generate_204(shipment, sender_id, receiver_id, control_numbers=None, current_dt=None):
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    carrier_scac = _clean_text(shipment.get("carrier_scac") or shipment.get("scac") or shipment.get("carrier_code") or receiver_id)
    if not shipment_ref:
        raise ValueError("Shipment reference is required to generate a 204.")
    if not carrier_scac:
        raise ValueError("Carrier SCAC is required to generate a 204.")

    pickup_date = _format_outbound_date(shipment.get("etd"))
    delivery_date = _format_outbound_date(shipment.get("eta"))
    body_segments = [
        f"B2**{carrier_scac}**{shipment_ref}",
        "B2A*00*LT",
        f"L11*{shipment_ref}*CN",
    ]
    if pickup_date:
        body_segments.append(f"G62*10*{pickup_date}")
    if delivery_date:
        body_segments.append(f"G62*17*{delivery_date}")

    shipper_name = _first_present(shipment.get("shipper_name"), shipment.get("origin_port"))
    shipper_address = _first_present(shipment.get("shipper_address"), shipment.get("origin_port"))
    shipper_city = _split_location(_first_present(shipment.get("origin_port"), shipper_address))
    body_segments.append(f"N1*SH*{_segment_text(shipper_name)}")
    if shipper_address:
        body_segments.append(f"N3*{_segment_text(shipper_address)}")
    if shipper_city["city"] or shipper_city["state"] or shipper_city["postal"]:
        body_segments.append(
            "N4*{city}*{state}*{postal}".format(
                city=_segment_text(shipper_city["city"]),
                state=_segment_text(shipper_city["state"]),
                postal=_segment_text(shipper_city["postal"]),
            )
        )

    consignee_name = _first_present(shipment.get("consignee_name"), shipment.get("destination_port"))
    consignee_address = _first_present(shipment.get("consignee_address"), shipment.get("destination_port"))
    consignee_city = _split_location(_first_present(shipment.get("destination_port"), consignee_address))
    body_segments.append(f"N1*CN*{_segment_text(consignee_name)}")
    if consignee_address:
        body_segments.append(f"N3*{_segment_text(consignee_address)}")
    if consignee_city["city"] or consignee_city["state"] or consignee_city["postal"]:
        body_segments.append(
            "N4*{city}*{state}*{postal}".format(
                city=_segment_text(consignee_city["city"]),
                state=_segment_text(consignee_city["state"]),
                postal=_segment_text(consignee_city["postal"]),
            )
        )

    carrier_name = _first_present(shipment.get("carrier_name"), carrier_scac)
    body_segments.append(f"N1*CA*{_segment_text(carrier_name)}*2*{carrier_scac}")

    weight_kg = _parse_number(shipment.get("weight_kg"))
    if weight_kg is not None:
        body_segments.append(f"AT8*G*K*{int(round(weight_kg, 0))}")

    cargo_description = _clean_text(shipment.get("cargo_description"))
    if cargo_description:
        body_segments.append(f"L5*1*{_segment_text(cargo_description)}")

    notes = _clean_text(shipment.get("notes"))
    if notes:
        body_segments.append(f"NTE*GEN*{_segment_text(notes)}")

    return _build_x12_envelope(
        "SM",
        "204",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_214(shipment, sender_id, receiver_id, control_numbers=None, current_dt=None, event=None):
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("Shipment reference is required to generate a 214.")

    current_dt = current_dt or datetime.now(timezone.utc)
    event = event or {}
    status = _first_present(event.get("status"), shipment.get("status"), "Active")
    status_code = _first_present(event.get("status_code"), _status_to_at7_code(status))
    location_text = _first_present(event.get("location"), _infer_location_for_status(shipment, status))
    location = _split_location(location_text)
    event_ts = _clean_text(event.get("event_date")) or current_dt.isoformat(timespec="seconds")

    body_segments = [
        f"B10*{_segment_text(_first_present(event.get('pro_number'), shipment.get('shipment_ref')))}*{shipment_ref}*{_segment_text(_clean_text(shipment.get('carrier_scac') or receiver_id))[:10]}",
        "LX*1",
        f"AT7*{status_code}***{_format_outbound_date(event_ts)}*{_format_outbound_time(event_ts) or current_dt.strftime('%H%M')}*CT",
    ]
    if location["city"] or location["state"]:
        body_segments.append(f"MS1*{_segment_text(location['city'])}*{_segment_text(location['state'])}*US")

    return _build_x12_envelope(
        "QM",
        "214",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_215(shipment, sender_id, receiver_id, control_numbers=None, current_dt=None, event=None):
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("Shipment reference is required to generate a 215.")

    current_dt = current_dt or datetime.now(timezone.utc)
    event = event or {}
    status = _first_present(event.get("status"), shipment.get("status"), "In Transit")
    status_code = _first_present(event.get("status_code"), _status_to_q7_code(status))
    location_text = _first_present(event.get("location"), _infer_location_for_status(shipment, status))
    location = _split_location(location_text)
    event_ts = _clean_text(event.get("event_date")) or current_dt.isoformat(timespec="seconds")
    carrier_scac = _clean_text(shipment.get("carrier_scac") or receiver_id)

    body_segments = [
        f"B4*{shipment_ref}*{carrier_scac}",
        f"L11*{shipment_ref}*CN",
        f"Q7*{status_code}",
        f"DTM*140*{_format_outbound_date(event_ts)}",
    ]
    if location["city"] or location["state"]:
        body_segments.append(f"R4*L*UN*{_segment_text(location['city'])}*{_segment_text(location['state'])}")

    return _build_x12_envelope(
        "QM",
        "215",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_856(shipment, sender_id, receiver_id, control_numbers=None, current_dt=None):
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("Shipment reference is required to generate an 856.")

    current_dt = current_dt or datetime.now(timezone.utc)
    body_segments = [
        f"BSN*00*{shipment_ref}*{current_dt.strftime('%Y%m%d')}*{current_dt.strftime('%H%M')}",
        f"DTM*011*{_format_outbound_date(shipment.get('etd') or current_dt.isoformat())}",
        f"REF*CN*{shipment_ref}",
        "HL*1**S",
        f"N1*SH*{_segment_text(_first_present(shipment.get('shipper_name'), shipment.get('origin_port')))}",
        f"N1*CN*{_segment_text(_first_present(shipment.get('consignee_name'), shipment.get('destination_port')))}",
        "HL*2*1*I",
    ]
    cargo_ref = _first_present(shipment.get("containers"), shipment.get("cargo_description"), shipment_ref)
    body_segments.append(f"LIN**CN*{_segment_text(cargo_ref)}")
    weight_kg = _parse_number(shipment.get("weight_kg"))
    if weight_kg is not None:
        body_segments.append(f"SN1**{int(round(weight_kg, 0))}*KG")
    description = _clean_text(shipment.get("cargo_description"))
    if description:
        body_segments.append(f"PID*F****{_segment_text(description)}")

    return _build_x12_envelope(
        "SH",
        "856",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_990(shipment, sender_id, receiver_id, response_code="A", control_numbers=None, current_dt=None):
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    carrier_scac = _clean_text(shipment.get("carrier_scac") or receiver_id)
    if not shipment_ref:
        raise ValueError("Shipment reference is required to generate a 990.")
    if not carrier_scac:
        raise ValueError("Carrier SCAC is required to generate a 990.")

    body_segments = [f"B1*{carrier_scac}*{shipment_ref}**{_clean_text(response_code).upper() or 'A'}"]
    return _build_x12_envelope(
        "GF",
        "990",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
    )


def generate_997(inbound_transaction, control_numbers=None, current_dt=None):
    control_numbers = control_numbers or {}
    current_dt = current_dt or datetime.now(timezone.utc)

    interchange = inbound_transaction.get("interchange", {})
    group = inbound_transaction.get("group", {})
    transaction = inbound_transaction.get("transaction", {})

    sender_id = _first_present(interchange.get("receiver_id"), group.get("receiver_code"), "TMS")
    receiver_id = _first_present(interchange.get("sender_id"), group.get("sender_code"), "PARTNER")
    functional_id = _first_present(group.get("functional_id"), inbound_transaction.get("type"), "SM")
    group_version = _first_present(group.get("version"), transaction.get("version"), "005010")

    body_segments = [
        f"AK1*{functional_id}*{_segment_text(group.get('control_number')) or '1'}",
        f"AK2*{_segment_text(inbound_transaction.get('type'))}*{_segment_text(transaction.get('control_number')) or '1'}",
        "AK5*A",
        "AK9*A*1*1*1",
    ]
    return _build_x12_envelope(
        "FA",
        "997",
        sender_id,
        receiver_id,
        body_segments,
        control_numbers=control_numbers,
        current_dt=current_dt,
        version=group_version or "005010",
    )


def generate_iftsta(shipment, sender_id, receiver_id, control_number=None, current_dt=None, event=None):
    shipment_ref = _clean_text(shipment.get("shipment_ref"))
    if not shipment_ref:
        raise ValueError("Shipment reference is required to generate an IFTSTA.")

    current_dt = current_dt or datetime.now(timezone.utc)
    event = event or {}
    status = _first_present(event.get("status"), shipment.get("status"), "Active")
    status_code = {
        "ACTIVE": "ACT",
        "BOOKED": "BKD",
        "IN TRANSIT": "INT",
        "DELIVERED": "DEL",
        "CANCELLED": "CAN",
    }.get(_clean_text(status).upper(), "ACT")
    event_ts = _clean_text(event.get("event_date")) or current_dt.isoformat(timespec="seconds")
    location = _first_present(event.get("location"), _infer_location_for_status(shipment, status))

    control_number = _clean_text(control_number) or make_control_number(6)
    body_segments = [
        _build_unb(sender_id, receiver_id, control_number, current_dt=current_dt),
        f"UNH+{control_number}+IFTSTA:D:99B:UN",
        f"BGM+34+{shipment_ref}+9",
        f"RFF+CN:{shipment_ref}",
        f"STS+1+{status_code}",
        f"DTM+137:{_format_outbound_date(event_ts)}:102",
    ]
    if location:
        body_segments.append(f"LOC+11+{_segment_text(location)}")
    body_segments.append(f"UNT+{len(body_segments) - 1}+{control_number}")
    body_segments.append(f"UNZ+1+{control_number}")
    return _serialize_edifact_segments(body_segments)


def ensure_edi_inbox():
    EDI_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    EDI_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    EDI_FAILED_DIR.mkdir(parents=True, exist_ok=True)
    return EDI_INBOX_DIR


def get_edi_inbox_path():
    return str(ensure_edi_inbox())


def _unique_archive_path(target_dir, source_path):
    candidate = target_dir / source_path.name
    if not candidate.exists():
        return candidate
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return target_dir / f"{source_path.stem}-{timestamp}{source_path.suffix}"


def _match_inbound_partner(conn, parsed_transaction):
    from .tms_db import find_edi_partner

    sender_id = _clean_text((parsed_transaction.get("interchange") or {}).get("sender_id"))
    if not sender_id:
        return None
    return find_edi_partner(
        conn,
        isa_id=sender_id,
        edi_format=parsed_transaction.get("format", "X12"),
        direction="inbound",
    )


def process_inbound_edi_payload(raw_edi, *, filename="", source_path="", conn=None):
    from .tms_db import apply_edi_transaction, create_edi_transaction, get_db, init_tms_db

    own_connection = conn is None
    if own_connection:
        init_tms_db()
        conn = get_db()

    summary = {
        "format": "UNKNOWN",
        "processed": 0,
        "created": 0,
        "updated": 0,
        "logged": 0,
        "failed": 0,
        "acked": 0,
        "transactions": [],
    }

    try:
        parsed_transactions = parse_edi_document(raw_edi)
        summary["format"] = parsed_transactions[0].get("format", "UNKNOWN") if parsed_transactions else "UNKNOWN"
    except ValueError as exc:
        create_edi_transaction(
            conn,
            "inbound",
            "UNKNOWN",
            raw_edi,
            {"filename": filename, "source_path": source_path, "error": str(exc)},
            status="parse_error",
            edi_format="UNKNOWN",
            filename=filename,
            source_path=source_path,
        )
        if own_connection:
            conn.commit()
            conn.close()
        raise

    try:
        for parsed in parsed_transactions:
            transaction_type = parsed.get("type") or "UNKNOWN"
            shipment_ref = (
                (parsed.get("shipment") or {}).get("shipment_ref")
                or (parsed.get("references") or {}).get("shipment_ref")
                or ""
            )
            raw_transaction = parsed.get("raw_transaction") or raw_edi
            partner = _match_inbound_partner(conn, parsed)
            partner_id = partner["id"] if partner else None
            stored_payload = parsed
            status = "received"
            result = {}

            if transaction_type in AUTO_APPLY_TRANSACTION_TYPES:
                try:
                    result = apply_edi_transaction(conn, parsed)
                    status = result.get("status", "received")
                    summary["processed"] += 1
                    if status == "created":
                        summary["created"] += 1
                    elif status == "updated":
                        summary["updated"] += 1
                except ValueError as exc:
                    stored_payload = dict(parsed)
                    stored_payload["processing_error"] = str(exc)
                    status = "failed"
                    summary["failed"] += 1
            else:
                summary["processed"] += 1
                summary["logged"] += 1

            inbound_id = create_edi_transaction(
                conn,
                "inbound",
                transaction_type,
                raw_transaction,
                stored_payload,
                shipment_ref=result.get("shipment_ref", shipment_ref),
                status=status,
                edi_format=parsed.get("format", "X12"),
                partner_id=partner_id,
                filename=filename,
                source_path=source_path,
            )

            ack_raw = generate_997(parsed)
            create_edi_transaction(
                conn,
                "outbound",
                "997",
                ack_raw,
                {
                    "type": "997",
                    "format": "X12",
                    "acknowledges_transaction_id": inbound_id,
                    "acknowledges_type": transaction_type,
                    "shipment_ref": result.get("shipment_ref", shipment_ref),
                    "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
                },
                shipment_ref=result.get("shipment_ref", shipment_ref),
                status="generated",
                edi_format="X12",
                partner_id=partner_id,
                filename=f"ack-{filename}" if filename else "",
            )
            summary["acked"] += 1
            summary["transactions"].append(
                {
                    "id": inbound_id,
                    "type": transaction_type,
                    "status": status,
                    "shipment_ref": result.get("shipment_ref", shipment_ref),
                }
            )

        if own_connection:
            conn.commit()
    finally:
        if own_connection:
            conn.close()

    return summary


def scan_edi_inbox_once():
    ensure_edi_inbox()
    results = []
    for path in sorted(EDI_INBOX_DIR.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in INBOX_EXTENSIONS:
            continue

        try:
            raw_edi = _decode_edi_bytes(path.read_bytes())
            summary = process_inbound_edi_payload(raw_edi, filename=path.name, source_path=str(path))
            archived_path = _unique_archive_path(EDI_ARCHIVE_DIR, path)
            shutil.move(str(path), str(archived_path))
            results.append({"path": str(path), "status": "processed", "summary": summary})
        except Exception as exc:
            failed_path = _unique_archive_path(EDI_FAILED_DIR, path)
            try:
                shutil.move(str(path), str(failed_path))
            except OSError:
                pass
            results.append({"path": str(path), "status": "failed", "error": str(exc)})
    return results


def _watch_edi_inbox():
    ensure_edi_inbox()
    while not _WATCHER_STOP.is_set():
        try:
            scan_edi_inbox_once()
        except Exception:
            pass
        _WATCHER_STOP.wait(WATCHER_POLL_SECONDS)


def start_edi_inbox_watcher():
    global _WATCHER_THREAD
    ensure_edi_inbox()
    with _WATCHER_LOCK:
        if _WATCHER_THREAD and _WATCHER_THREAD.is_alive():
            return str(EDI_INBOX_DIR)
        _WATCHER_STOP.clear()
        _WATCHER_THREAD = threading.Thread(
            target=_watch_edi_inbox,
            name="tms-edi-inbox-watcher",
            daemon=True,
        )
        _WATCHER_THREAD.start()
    return str(EDI_INBOX_DIR)


def stop_edi_inbox_watcher():
    _WATCHER_STOP.set()


__all__ = [
    "AUTO_APPLY_TRANSACTION_TYPES",
    "EDIFACT_MESSAGE_TYPES",
    "SUPPORTED_TRANSACTION_TYPES",
    "X12_TRANSACTION_TYPES",
    "detect_edi_format",
    "detect_edifact_delimiters",
    "detect_type",
    "detect_x12_delimiters",
    "ensure_edi_inbox",
    "generate_204",
    "generate_214",
    "generate_215",
    "generate_856",
    "generate_990",
    "generate_997",
    "generate_iftsta",
    "get_edi_inbox_path",
    "make_control_number",
    "parse_edi",
    "parse_edi_document",
    "parse_edifact_document",
    "parse_x12_document",
    "process_inbound_edi_payload",
    "scan_edi_inbox_once",
    "split_edifact_segments",
    "split_x12_segments",
    "start_edi_inbox_watcher",
    "stop_edi_inbox_watcher",
]
