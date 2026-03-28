"""
carrier_api.py
--------------
Unified vessel schedule client for carrier APIs and the SeaRates DCSA-style
aggregator. It normalizes carrier responses into the dashboard's
vessel_schedules shape and keeps failures isolated per carrier.
"""

import argparse
import logging
import os
import threading
import time
from datetime import datetime

import requests

from config import (
    MAERSK_API_KEY,
    MSC_API_KEY,
    CMA_API_KEY,
    HAPAG_API_KEY,
    DCSA_API_KEY,
)


log = logging.getLogger(__name__)

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


ORIGIN_PORTS = {
    "China": [
        "Shanghai", "Ningbo", "Yantian", "Shenzhen", "Guangzhou",
        "Qingdao", "Tianjin", "Xiamen", "Dalian", "Lianyungang",
    ],
    "Vietnam": ["Ho Chi Minh", "Cat Lai", "Cai Mep", "Hai Phong", "Da Nang"],
    "India": [
        "Nhava Sheva", "JNPT", "Chennai", "Mundra", "Cochin",
        "Hazira", "Pipavav", "Kolkata", "Mumbai",
    ],
    "Middle East": ["Jebel Ali", "Dubai", "Dammam", "Sohar", "Salalah", "Jeddah", "Aqaba", "Kuwait", "Muscat"],
    "Europe": [
        "Rotterdam", "Hamburg", "Antwerp", "Bremerhaven", "Felixstowe",
        "Le Havre", "Barcelona", "Genoa", "Valencia", "Piraeus", "Gdansk",
    ],
    "South Korea": ["Busan", "Incheon", "Gwangyang"],
    "Japan": ["Yokohama", "Tokyo", "Kobe", "Osaka", "Nagoya"],
    "Bangladesh": ["Chittagong", "Mongla"],
    "Indonesia": ["Tanjung Priok", "Surabaya", "Belawan", "Makassar"],
    "Malaysia": ["Port Klang", "Penang", "Tanjung Pelepas"],
    "Thailand": ["Laem Chabang", "Bangkok"],
    "Brazil": ["Santos", "Itajai", "Paranagua", "Rio de Janeiro"],
    "Mexico": ["Manzanillo", "Lazaro Cardenas", "Veracruz", "Altamira"],
    "Pakistan": ["Karachi", "Port Qasim"],
    "Sri Lanka": ["Colombo"],
    "Taiwan": ["Kaohsiung", "Taichung", "Keelung"],
    "Philippines": ["Manila", "Batangas", "Subic Bay"],
    "Turkey": ["Mersin", "Istanbul", "Izmir", "Ambarli"],
    "Egypt": ["Port Said", "Alexandria", "Damietta"],
    "South Africa": ["Durban", "Cape Town", "Port Elizabeth"],
    "Nigeria": ["Apapa", "Lagos", "Tin Can Island"],
    "Kenya": ["Mombasa"],
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Fremantle", "Adelaide"],
    "New Zealand": ["Auckland", "Tauranga", "Lyttelton"],
}

DEST_PORTS = {
    "USA": [
        "Los Angeles", "Long Beach", "Oakland", "Seattle", "Tacoma",
        "New York", "Newark", "Norfolk", "Savannah", "Charleston",
        "Houston", "Miami",
    ],
    "Canada": ["Vancouver", "Prince Rupert", "Montreal", "Halifax"],
    "Europe": [
        "Rotterdam", "Hamburg", "Antwerp", "Bremerhaven", "Felixstowe",
        "Le Havre", "Barcelona", "Genoa", "Valencia", "Piraeus",
    ],
    "Mexico": ["Manzanillo", "Lazaro Cardenas", "Veracruz", "Altamira"],
    "South America": [
        "Santos", "Buenos Aires", "Callao", "Buenaventura",
        "Cartagena", "Valparaiso", "San Antonio", "Montevideo",
    ],
    "Central America": ["Colon", "Moin", "Puerto Cortes", "Puerto Quetzal", "Acajutla"],
    "Australia/NZ": [
        "Sydney", "Melbourne", "Brisbane", "Fremantle", "Adelaide",
        "Auckland", "Tauranga", "Lyttelton", "Port Botany",
    ],
    "Middle East": ["Jebel Ali", "Dubai", "Dammam", "Sohar", "Salalah", "Jeddah", "Aqaba"],
    "Africa": ["Durban", "Mombasa", "Lagos", "Tema", "Dar es Salaam", "Port Elizabeth", "Apapa"],
}


# Primary lookup values use widely accepted shipping UN/LOCODEs. Where carrier
# implementations differ in practice, common alternates are retained as aliases.
PORT_LOCODES = {
    "Shanghai": "CNSHA",
    "Ningbo": "CNNBO",
    "Yantian": "CNYTN",
    "Shenzhen": "CNSNZ",
    "Guangzhou": "CNGGZ",
    "Qingdao": "CNQIN",
    "Tianjin": "CNTNJ",
    "Xiamen": "CNXMN",
    "Dalian": "CNDAL",
    "Lianyungang": "CNLYG",
    "Ho Chi Minh": "VNSGN",
    "Cat Lai": "VNCLI",
    "Cai Mep": "VNCMT",
    "Hai Phong": "VNHPH",
    "Da Nang": "VNDAD",
    "Nhava Sheva": "INNSA",
    "JNPT": "INNSA",
    "Chennai": "INMAA",
    "Mundra": "INMUN",
    "Cochin": "INCOK",
    "Hazira": "INHZR",
    "Pipavav": "INPAV",
    "Kolkata": "INCCU",
    "Mumbai": "INBOM",
    "Jebel Ali": "AEJEA",
    "Dubai": "AEDXB",
    "Dammam": "SADMM",
    "Sohar": "OMSOH",
    "Salalah": "OMSLL",
    "Jeddah": "SAJED",
    "Aqaba": "JOAQB",
    "Kuwait": "KWKWI",
    "Muscat": "OMMCT",
    "Rotterdam": "NLRTM",
    "Hamburg": "DEHAM",
    "Antwerp": "BEANR",
    "Bremerhaven": "DEBRV",
    "Felixstowe": "GBFXT",
    "Le Havre": "FRLEH",
    "Barcelona": "ESBCN",
    "Genoa": "ITGOA",
    "Valencia": "ESVLC",
    "Piraeus": "GRPIR",
    "Gdansk": "PLGDN",
    "Busan": "KRPUS",
    "Incheon": "KRINC",
    "Gwangyang": "KRKAN",
    "Yokohama": "JPYOK",
    "Tokyo": "JPTYO",
    "Kobe": "JPUKB",
    "Osaka": "JPOSA",
    "Nagoya": "JPNGO",
    "Chittagong": "BDCGP",
    "Tanjung Priok": "IDTPP",
    "Surabaya": "IDSUB",
    "Belawan": "IDBLW",
    "Port Klang": "MYPKG",
    "Penang": "MYPEN",
    "Tanjung Pelepas": "MYTPP",
    "Laem Chabang": "THLCH",
    "Bangkok": "THBKK",
    "Santos": "BRSSZ",
    "Itajai": "BRITJ",
    "Paranagua": "BRPNG",
    "Rio de Janeiro": "BRRIO",
    "Manzanillo": "MXZLO",
    "Lazaro Cardenas": "MXLZC",
    "Veracruz": "MXVER",
    "Altamira": "MXATM",
    "Los Angeles": "USLAX",
    "Long Beach": "USLGB",
    "Oakland": "USOAK",
    "Seattle": "USSEA",
    "Tacoma": "USTIW",
    "New York": "USNYC",
    "Newark": "USNWK",
    "Norfolk": "USORF",
    "Savannah": "USSAV",
    "Charleston": "USCHS",
    "Houston": "USHOU",
    "Miami": "USMIA",
    "Vancouver": "CAVAN",
    "Prince Rupert": "CAPRR",
    "Montreal": "CAMTR",
    "Halifax": "CAHAL",
    "Buenos Aires": "ARBUE",
    "Callao": "PECLL",
    "Buenaventura": "COBUN",
    "Cartagena": "COCTG",
    "Valparaiso": "CLVAP",
    "San Antonio": "CLSAI",
    "Montevideo": "UYMVD",
    "Colon": "PAONX",
    "Moin": "CRPMN",
    "Puerto Cortes": "HNPCR",
    "Puerto Quetzal": "GTPRQ",
    "Acajutla": "SVAQJ",
    "Sydney": "AUSYD",
    "Melbourne": "AUMEL",
    "Brisbane": "AUBNE",
    "Fremantle": "AUFRE",
    "Adelaide": "AUADL",
    "Auckland": "NZAKL",
    "Tauranga": "NZTRG",
    "Lyttelton": "NZLYT",
    "Port Botany": "AUPBT",
    "Durban": "ZADUR",
    "Mombasa": "KEMBA",
    "Lagos": "NGLAG",
    "Tema": "GHTEM",
    "Dar es Salaam": "TZDAR",
    "Port Elizabeth": "ZAPLZ",
    "Apapa": "NGAPP",
}

PORT_LOCODE_ALIASES = {
    "Shanghai": ["CNSHG", "CNPDG"],
    "Yantian": ["CNYAN"],
    "Shenzhen": ["CNSZX"],
    "Guangzhou": ["CNGZG"],
    "Tianjin": ["CNTNG"],
    "Xiamen": ["CNXMH"],
    "Dalian": ["CNDAG", "CNDLC"],
    "Ho Chi Minh": ["VNVIC"],
    "Cai Mep": ["VNTOT"],
    "Aqaba": ["JOAQJ"],
    "Muscat": ["OMSTQ"],
    "Antwerp": ["BEANT"],
    "Busan": ["KRBNP"],
    "Port Klang": ["MYWSP", "MYXPQ"],
    "Long Beach": ["USLBH"],
    "Norfolk": ["USNFK", "USNFJ", "USNFF"],
    "Houston": ["USHSO"],
    "Miami": ["USMIO"],
    "Moin": ["CRMOB"],
}

PORT_NAMES_BY_LOCODE = {}
for _port_name, _primary in PORT_LOCODES.items():
    PORT_NAMES_BY_LOCODE[_primary.upper()] = _port_name
    for _alias in PORT_LOCODE_ALIASES.get(_port_name, []):
        PORT_NAMES_BY_LOCODE[_alias.upper()] = _port_name


CARRIER_KEYS = {
    "Maersk": MAERSK_API_KEY,
    "MSC": MSC_API_KEY,
    "CMA CGM": CMA_API_KEY,
    "Hapag-Lloyd": HAPAG_API_KEY,
}

CARRIER_SCACS = {
    "Maersk": "MAEU",
    "MSC": "MSCU",
    "CMA CGM": "CMDU",
    "Hapag-Lloyd": "HDMU",
}

CARRIER_SOURCES = {
    "Maersk": "maersk_api",
    "MSC": "msc_api",
    "CMA CGM": "cma_api",
    "Hapag-Lloyd": "hapag_api",
    "DCSA": "dcsa_api",
}

API_BASE_URLS = {
    "Maersk": os.environ.get("MAERSK_SCHEDULE_URL", "https://api.maersk.com/schedules/point-to-point"),
    "MSC": os.environ.get("MSC_SCHEDULE_URL", "https://app.msc.com/api/schedules"),
    "CMA CGM": os.environ.get("CMA_SCHEDULE_URL", "https://api-portal.cma-cgm.com"),
    "Hapag-Lloyd": os.environ.get("HAPAG_SCHEDULE_URL", "https://developer.hlag.com"),
    "DCSA": os.environ.get("DCSA_SCHEDULE_URL", "https://schedules.searates.com/api/v2"),
}


_session = requests.Session()
_session.headers.update({
    "User-Agent": "flashcargo-contact-dashboard/1.0",
    "Accept": "application/json, text/html;q=0.9",
})

_rate_lock = threading.Lock()
_last_request_at = {}


def has_any_api_keys_configured():
    return any([MAERSK_API_KEY, MSC_API_KEY, CMA_API_KEY, HAPAG_API_KEY, DCSA_API_KEY])


def configured_key_status():
    return {
        "Maersk": bool(MAERSK_API_KEY),
        "MSC": bool(MSC_API_KEY),
        "CMA CGM": bool(CMA_API_KEY),
        "Hapag-Lloyd": bool(HAPAG_API_KEY),
        "DCSA": bool(DCSA_API_KEY),
    }


def resolve_port_name(locode):
    return PORT_NAMES_BY_LOCODE.get((locode or "").upper(), locode or "")


def _throttle(bucket):
    with _rate_lock:
        last = _last_request_at.get(bucket, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_request_at[bucket] = time.monotonic()


def _safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


def _request_json(bucket, url, headers=None, params=None, timeout=30):
    _throttle(bucket)
    response = _session.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    if response.status_code >= 400:
        payload = _safe_json(response)
        if payload:
            raise RuntimeError(str(payload))
        raise RuntimeError("HTTP %s from %s" % (response.status_code, url))
    payload = _safe_json(response)
    if payload is None:
        raise RuntimeError("Non-JSON response from %s" % url)
    return payload


def _request_text(bucket, url, headers=None, params=None, timeout=30):
    _throttle(bucket)
    response = _session.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError("HTTP %s from %s" % (response.status_code, url))
    return response.text


def _pick(mapping, *paths):
    for path in paths:
        value = mapping
        ok = True
        for key in path:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                ok = False
                break
        if ok and value not in (None, "", [], {}):
            return value
    return None


def _pick_list(mapping, *paths):
    value = _pick(mapping, *paths)
    if isinstance(value, list):
        return value
    return []


def _as_iso_date(value):
    if not value:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    candidates = [
        "%Y/%m/%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y%m%d",
    ]
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).strftime("%Y-%m-%d")
    except Exception:
        pass
    for fmt in candidates:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return text[:10]


def _parse_dt(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    for candidate in [
        normalized,
        normalized.replace(" ", "T"),
        normalized.replace("T", " "),
    ]:
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            continue
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]:
        try:
            return datetime.strptime(text[:19], fmt)
        except Exception:
            continue
    return None


def _format_transit(transit_value, etd, eta):
    if transit_value not in (None, ""):
        text = str(transit_value).strip()
        if text.isdigit():
            return "%s days" % text
        return text
    etd_dt = _parse_dt(etd)
    eta_dt = _parse_dt(eta)
    if etd_dt and eta_dt:
        days = (eta_dt.date() - etd_dt.date()).days
        if days >= 0:
            return "%s days" % days
    return ""


def _extract_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for path in [
        ("data", "schedules"),
        ("data", "routes"),
        ("data", "results"),
        ("data", "items"),
        ("data", "pointToPointRoutings"),
        ("data", "vesselSchedules"),
        ("data", "commercialSchedules"),
        ("schedules",),
        ("routes",),
        ("results",),
        ("items",),
        ("pointToPointRoutings",),
        ("vesselSchedules",),
        ("commercialSchedules",),
    ]:
        value = _pick(payload, *[path])
        if isinstance(value, list):
            return value
    if any(k in payload for k in ("origin", "destination", "vessel_name", "vesselName", "transit_time")):
        return [payload]
    return []


def _normalize_generic_item(item, carrier_name, origin_locode, dest_locode, source_tag):
    origin_name = _pick(
        item,
        ("origin", "port_name"),
        ("origin", "portName"),
        ("origin", "locationName"),
        ("originPort", "portName"),
        ("originPort", "locationName"),
        ("placeOfReceipt", "locationName"),
        ("portOfLoading", "locationName"),
        ("departure", "port_name"),
        ("departure", "portName"),
    )
    destination_name = _pick(
        item,
        ("destination", "port_name"),
        ("destination", "portName"),
        ("destination", "locationName"),
        ("destinationPort", "portName"),
        ("destinationPort", "locationName"),
        ("placeOfDelivery", "locationName"),
        ("portOfDischarge", "locationName"),
        ("arrival", "port_name"),
        ("arrival", "portName"),
    )
    origin_name = origin_name or resolve_port_name(origin_locode)
    destination_name = destination_name or resolve_port_name(dest_locode)

    etd_raw = _pick(
        item,
        ("origin", "estimated_date"),
        ("origin", "estimatedDate"),
        ("departure", "estimated_date"),
        ("departure", "estimatedDate"),
        ("departure", "date"),
        ("schedule", "departureDate"),
        ("transportCall", "departureDate"),
    ) or item.get("etd") or item.get("departureDate")
    eta_raw = _pick(
        item,
        ("destination", "estimated_date"),
        ("destination", "estimatedDate"),
        ("arrival", "estimated_date"),
        ("arrival", "estimatedDate"),
        ("arrival", "date"),
        ("schedule", "arrivalDate"),
        ("transportCall", "arrivalDate"),
    ) or item.get("eta") or item.get("arrivalDate")

    legs = _pick_list(item, ("legs",), ("transportLegs",), ("segments",))
    first_leg = legs[0] if legs else {}

    vessel_name = (
        item.get("vessel_name")
        or item.get("vesselName")
        or _pick(item, ("vessel", "name"))
        or first_leg.get("vessel_name")
        or first_leg.get("vesselName")
        or _pick(first_leg, ("vessel", "name"))
        or ""
    )
    service = (
        item.get("service")
        or item.get("service_name")
        or item.get("serviceName")
        or item.get("service_code")
        or item.get("serviceCode")
        or first_leg.get("service_name")
        or first_leg.get("serviceName")
        or first_leg.get("service_code")
        or first_leg.get("serviceCode")
        or ""
    )
    transit = _format_transit(item.get("transit_time") or item.get("transitTime"), etd_raw, eta_raw)

    normalized = {
        "carrier": carrier_name,
        "origin": str(origin_name or "").strip(),
        "destination": str(destination_name or "").strip(),
        "vessel_name": str(vessel_name or "").strip(),
        "service": str(service or "").strip(),
        "etd": _as_iso_date(etd_raw),
        "eta": _as_iso_date(eta_raw),
        "transit_time": transit,
        "source": source_tag,
    }
    if not normalized["carrier"] or not normalized["origin"] or not normalized["destination"] or not normalized["etd"]:
        return None
    return normalized


def _normalize_searates_item(item, origin_locode, dest_locode):
    legs = item.get("legs") or []
    first_leg = legs[0] if legs else {}
    etd_raw = _pick(item, ("origin", "estimated_date")) or _pick(first_leg, ("departure", "estimated_date"))
    eta_raw = _pick(item, ("destination", "estimated_date")) or _pick(first_leg, ("arrival", "estimated_date"))
    vessel_name = first_leg.get("vessel_name") or item.get("vessel_name") or ""
    service = first_leg.get("service_name") or first_leg.get("service_code") or item.get("service_name") or ""
    transit = _format_transit(item.get("transit_time"), etd_raw, eta_raw)
    return {
        "carrier": item.get("carrier_name") or "DCSA",
        "origin": _pick(item, ("origin", "port_name")) or resolve_port_name(origin_locode),
        "destination": _pick(item, ("destination", "port_name")) or resolve_port_name(dest_locode),
        "vessel_name": str(vessel_name).strip(),
        "service": str(service).strip(),
        "etd": _as_iso_date(etd_raw),
        "eta": _as_iso_date(eta_raw),
        "transit_time": transit,
        "source": CARRIER_SOURCES["DCSA"],
    }


def _dedupe_rows(rows):
    deduped = []
    seen = set()
    for row in rows:
        if not row:
            continue
        key = (
            (row.get("carrier") or "").strip().lower(),
            (row.get("origin") or "").strip().lower(),
            (row.get("destination") or "").strip().lower(),
            (row.get("vessel_name") or "").strip().lower(),
            (row.get("etd") or "").strip(),
        )
        if not key[0] or not key[1] or not key[2] or not key[4]:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _try_candidate_requests(bucket, urls, headers_list, params_list):
    last_error = None
    for url in urls:
        for headers in headers_list:
            for params in params_list:
                try:
                    return _request_json(bucket, url, headers=headers, params=params)
                except Exception as exc:
                    last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("No endpoint candidates configured")


def fetch_maersk_schedules(origin_locode, dest_locode, start_date, end_date):
    if not MAERSK_API_KEY:
        return []
    payload = _request_json(
        "maersk",
        API_BASE_URLS["Maersk"],
        headers={"Consumer-Key": MAERSK_API_KEY},
        params={
            "originUnLocCode": origin_locode,
            "destinationUnLocCode": dest_locode,
            "dateRange.startDate": start_date,
            "dateRange.endDate": end_date,
        },
    )
    rows = []
    for item in _extract_records(payload):
        normalized = _normalize_generic_item(item, "Maersk", origin_locode, dest_locode, CARRIER_SOURCES["Maersk"])
        if normalized:
            rows.append(normalized)
    return _dedupe_rows(rows)


def fetch_msc_schedules(origin_locode, dest_locode, start_date, end_date):
    rows = []
    if MSC_API_KEY:
        payload = _try_candidate_requests(
            "msc",
            [API_BASE_URLS["MSC"]],
            [
                {"X-API-Key": MSC_API_KEY, "Authorization": "Bearer %s" % MSC_API_KEY},
                {"Ocp-Apim-Subscription-Key": MSC_API_KEY},
                {"Authorization": "Bearer %s" % MSC_API_KEY},
            ],
            [
                {
                    "originUnLocCode": origin_locode,
                    "destinationUnLocCode": dest_locode,
                    "dateFrom": start_date,
                    "dateTo": end_date,
                },
                {
                    "origin": origin_locode,
                    "destination": dest_locode,
                    "startDate": start_date,
                    "endDate": end_date,
                },
                {
                    "from": origin_locode,
                    "to": dest_locode,
                    "fromDate": start_date,
                    "toDate": end_date,
                },
            ],
        )
        for item in _extract_records(payload):
            normalized = _normalize_generic_item(item, "MSC", origin_locode, dest_locode, CARRIER_SOURCES["MSC"])
            if normalized:
                rows.append(normalized)
        return _dedupe_rows(rows)

    # Best-effort public page fallback. MSC blocks some clients, so failures are
    # expected and intentionally non-fatal.
    html = _request_text(
        "msc-public",
        "https://www.msc.com/en/search-a-schedule",
        params={"origin": origin_locode, "destination": dest_locode, "fromDate": start_date},
    )
    lowered = html.lower()
    if "access denied" in lowered or "no results" in lowered:
        return []
    if resolve_port_name(origin_locode).lower() in lowered and resolve_port_name(dest_locode).lower() in lowered:
        rows.append({
            "carrier": "MSC",
            "origin": resolve_port_name(origin_locode),
            "destination": resolve_port_name(dest_locode),
            "vessel_name": "",
            "service": "",
            "etd": start_date,
            "eta": "",
            "transit_time": "",
            "source": CARRIER_SOURCES["MSC"],
        })
    return _dedupe_rows(rows)


def fetch_cma_schedules(origin_locode, dest_locode, start_date, end_date):
    if not CMA_API_KEY:
        return []
    payload = _try_candidate_requests(
        "cma",
        [
            API_BASE_URLS["CMA CGM"].rstrip("/") + "/commercial-schedules/point-to-point-routings",
            API_BASE_URLS["CMA CGM"].rstrip("/") + "/api/commercial-schedules/point-to-point-routings",
            API_BASE_URLS["CMA CGM"].rstrip("/") + "/schedules/point-to-point",
        ],
        [
            {"X-API-Key": CMA_API_KEY},
            {"Ocp-Apim-Subscription-Key": CMA_API_KEY},
            {"Authorization": "Bearer %s" % CMA_API_KEY},
        ],
        [
            {
                "originUnLocCode": origin_locode,
                "destinationUnLocCode": dest_locode,
                "departureStartDate": start_date,
                "departureEndDate": end_date,
            },
            {
                "placeOfReceipt": origin_locode,
                "placeOfDelivery": dest_locode,
                "departureStartDate": start_date,
                "departureEndDate": end_date,
            },
        ],
    )
    rows = []
    for item in _extract_records(payload):
        normalized = _normalize_generic_item(item, "CMA CGM", origin_locode, dest_locode, CARRIER_SOURCES["CMA CGM"])
        if normalized:
            rows.append(normalized)
    return _dedupe_rows(rows)


def fetch_hapag_schedules(origin_locode, dest_locode, start_date, end_date):
    if not HAPAG_API_KEY:
        return []
    payload = _try_candidate_requests(
        "hapag",
        [
            API_BASE_URLS["Hapag-Lloyd"].rstrip("/") + "/commercial-schedules/point-to-point-routings",
            API_BASE_URLS["Hapag-Lloyd"].rstrip("/") + "/api/commercial-schedules/point-to-point-routings",
            API_BASE_URLS["Hapag-Lloyd"].rstrip("/") + "/schedules/point-to-point",
        ],
        [
            {"X-API-Key": HAPAG_API_KEY},
            {"Ocp-Apim-Subscription-Key": HAPAG_API_KEY},
            {"Authorization": "Bearer %s" % HAPAG_API_KEY},
        ],
        [
            {
                "originUnLocCode": origin_locode,
                "destinationUnLocCode": dest_locode,
                "departureStartDate": start_date,
                "departureEndDate": end_date,
            },
            {
                "placeOfReceipt": origin_locode,
                "placeOfDelivery": dest_locode,
                "departureStartDate": start_date,
                "departureEndDate": end_date,
            },
        ],
    )
    rows = []
    for item in _extract_records(payload):
        normalized = _normalize_generic_item(item, "Hapag-Lloyd", origin_locode, dest_locode, CARRIER_SOURCES["Hapag-Lloyd"])
        if normalized:
            rows.append(normalized)
    return _dedupe_rows(rows)


def fetch_dcsa_schedules(origin_locode, dest_locode, start_date, end_date, carriers=None):
    if not DCSA_API_KEY:
        return []
    weeks = 1
    try:
        start_dt = _parse_dt(start_date)
        end_dt = _parse_dt(end_date)
        if start_dt and end_dt:
            delta_days = max(1, (end_dt.date() - start_dt.date()).days)
            weeks = max(1, min(6, ((delta_days + 6) // 7)))
    except Exception:
        weeks = 1

    carrier_scacs = []
    for carrier in carriers or []:
        scac = CARRIER_SCACS.get(carrier)
        if scac:
            carrier_scacs.append(scac)

    payload = _request_json(
        "dcsa",
        API_BASE_URLS["DCSA"].rstrip("/") + "/schedules/by-points",
        headers={"X-API-KEY": DCSA_API_KEY, "Content-Type": "application/json"},
        params={
            "origin": origin_locode,
            "destination": dest_locode,
            "from_date": start_date,
            "weeks": weeks,
            "sort": "DEP",
            "cargo_type": "GC",
            "direct_only": "false",
            "multimodal": "true",
            "carriers": ",".join(carrier_scacs) if carrier_scacs else None,
        },
    )
    rows = []
    for item in _pick_list(payload, ("data", "schedules")):
        normalized = _normalize_searates_item(item, origin_locode, dest_locode)
        if normalized:
            if carriers and normalized["carrier"] not in carriers:
                continue
            rows.append(normalized)
    return _dedupe_rows(rows)


def fetch_schedules(origin_locode, dest_locode, start_date, end_date, carriers=None):
    requested = carriers or ["Maersk", "MSC", "CMA CGM", "Hapag-Lloyd"]
    rows = []
    aggregator_backfill = []

    adapter_specs = [
        ("Maersk", fetch_maersk_schedules),
        ("MSC", fetch_msc_schedules),
        ("CMA CGM", fetch_cma_schedules),
        ("Hapag-Lloyd", fetch_hapag_schedules),
    ]

    for carrier_name, adapter in adapter_specs:
        if carrier_name not in requested:
            continue
        if not CARRIER_KEYS.get(carrier_name):
            aggregator_backfill.append(carrier_name)
            continue
        try:
            rows.extend(adapter(origin_locode, dest_locode, start_date, end_date))
        except Exception as exc:
            aggregator_backfill.append(carrier_name)
            log.warning("[%s] %s", carrier_name, exc)

    if DCSA_API_KEY and aggregator_backfill:
        try:
            rows.extend(fetch_dcsa_schedules(origin_locode, dest_locode, start_date, end_date, carriers=aggregator_backfill))
        except Exception as exc:
            log.warning("[DCSA] %s", exc)

    return _dedupe_rows(rows)


def _test_dcsa_connection():
    payload = _request_json(
        "dcsa-test",
        API_BASE_URLS["DCSA"].rstrip("/") + "/carriers",
        headers={"X-API-KEY": DCSA_API_KEY, "Content-Type": "application/json"},
        params={"schedule_type": "BY_POINTS", "cargo_type": "GC"},
    )
    count = len(_pick_list(payload, ("data", "carriers")))
    return "ok (%s carriers)" % count


def run_tests():
    print("Carrier API status")
    print("------------------")
    status = configured_key_status()
    for carrier, enabled in status.items():
        print("%s: %s" % (carrier, "configured" if enabled else "not configured"))

    print("")
    print("Test calls")
    print("----------")
    origin = PORT_LOCODES["Shanghai"]
    destination = PORT_LOCODES["Los Angeles"]
    start_date = datetime.utcnow().strftime("%Y-%m-%d")
    end_date = start_date

    tests = [
        ("Maersk", MAERSK_API_KEY, lambda: fetch_maersk_schedules(origin, destination, start_date, end_date)),
        ("MSC", MSC_API_KEY, lambda: fetch_msc_schedules(origin, destination, start_date, end_date)),
        ("CMA CGM", CMA_API_KEY, lambda: fetch_cma_schedules(origin, destination, start_date, end_date)),
        ("Hapag-Lloyd", HAPAG_API_KEY, lambda: fetch_hapag_schedules(origin, destination, start_date, end_date)),
        ("DCSA", DCSA_API_KEY, _test_dcsa_connection),
    ]

    for carrier, key, fn in tests:
        if not key:
            print("%s: skipped (no key)" % carrier)
            continue
        try:
            result = fn()
            if isinstance(result, str):
                print("%s: %s" % (carrier, result))
            else:
                print("%s: ok (%s rows)" % (carrier, len(result)))
        except Exception as exc:
            print("%s: failed (%s)" % (carrier, exc))


def main():
    parser = argparse.ArgumentParser(description="Carrier API utilities")
    parser.add_argument("--test", action="store_true", help="Print configured carriers and make a test call")
    args = parser.parse_args()

    if args.test:
        run_tests()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
