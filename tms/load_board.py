"""
Global Load Board Integration
==============================
Supports posting loads and pulling carrier capacity across 9 API-verified
load boards worldwide. Portal-only boards are registered for display but
flagged as manual.

Public API
----------
get_all_providers()                          -> list[dict]
post_load(shipment_ref, board_keys)          -> dict   # {board_key: result}
delete_posting(posting_id)                   -> bool
get_active_postings(shipment_ref=None)       -> list[dict]
get_board_settings()                         -> dict
save_board_settings(data)                    -> None
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ── Provider Registry ─────────────────────────────────────────────────────────

PROVIDERS: dict[str, dict[str, Any]] = {
    # ── North America ──────────────────────────────────────────────────────
    "dat": {
        "name": "DAT Load Board",
        "region": "North America",
        "region_code": "na",
        "api_status": "verified",
        "auth_type": "basic",
        "docs_url": "https://docs.dat-hub.com/",
        "base_url": "https://freight.api.dat.com",
        "post_endpoint": "/load",
        "delete_endpoint": "/load/{id}",
        "settings_keys": ["dat_username", "dat_password"],
        "settings_labels": {"dat_username": "DAT Username", "dat_password": "DAT Password"},
        "notes": "Requires DAT Load Board subscription.",
    },
    "truckstop": {
        "name": "Truckstop / ITS",
        "region": "North America",
        "region_code": "na",
        "api_status": "verified",
        "auth_type": "oauth2_password",
        "docs_url": "https://developer.truckstop.com/",
        "base_url": "https://api.truckstop.com",
        "token_endpoint": "/oauth/token",
        "post_endpoint": "/v1/loads",
        "delete_endpoint": "/v1/loads/{id}",
        "settings_keys": ["truckstop_client_id", "truckstop_client_secret",
                          "truckstop_username", "truckstop_password"],
        "settings_labels": {
            "truckstop_client_id": "Client ID",
            "truckstop_client_secret": "Client Secret",
            "truckstop_username": "Username",
            "truckstop_password": "Password",
        },
        "notes": "Requires Systems Integration Agreement (SIA). Contact: integrations@truckstop.com",
    },
    "123loadboard": {
        "name": "123Loadboard",
        "region": "North America",
        "region_code": "na",
        "api_status": "verified",
        "auth_type": "api_key",
        "docs_url": "https://www.123loadboard.com/api/",
        "base_url": "https://api.123loadboard.com",
        "post_endpoint": "/loads",
        "delete_endpoint": "/loads/{id}",
        "settings_keys": ["loadboard123_api_key"],
        "settings_labels": {"loadboard123_api_key": "API Key"},
        "notes": "No integration fees. Contact: partner-integrations@123loadboard.com",
    },
    "uship": {
        "name": "uShip",
        "region": "North America",
        "region_code": "na",
        "api_status": "verified",
        "auth_type": "oauth2_client",
        "docs_url": "https://developer.uship.com/",
        "base_url": "https://api.uship.com",
        "token_endpoint": "/oauth/token",
        "post_endpoint": "/v1/shipments",
        "delete_endpoint": "/v1/shipments/{id}",
        "settings_keys": ["uship_client_id", "uship_client_secret"],
        "settings_labels": {
            "uship_client_id": "Client ID",
            "uship_client_secret": "Client Secret",
        },
        "notes": "Supports webhooks for carrier responses.",
    },
    # ── Europe ──────────────────────────────────────────────────────────────
    "timocom": {
        "name": "TimoCom",
        "region": "Europe",
        "region_code": "eu",
        "api_status": "verified",
        "auth_type": "oauth2_client",
        "docs_url": "https://developer.timocom.com/",
        "base_url": "https://api.timocom.com",
        "token_endpoint": "/oauth2/token",
        "post_endpoint": "/freight-exchange/v1/offers",
        "delete_endpoint": "/freight-exchange/v1/offers/{id}",
        "settings_keys": ["timocom_client_id", "timocom_client_secret"],
        "settings_labels": {
            "timocom_client_id": "Client ID",
            "timocom_client_secret": "Client Secret",
        },
        "notes": "Largest European freight exchange. Integration time 1–4 days.",
    },
    "teleroute": {
        "name": "Teleroute (Alpega)",
        "region": "Europe",
        "region_code": "eu",
        "api_status": "verified",
        "auth_type": "jwt_password",
        "docs_url": "https://api-docs.teleroute.com/",
        "base_url": "https://api.fx.wktransportservices.com",
        "token_endpoint": "/user/token",
        "post_endpoint": "/v2/loads",
        "delete_endpoint": "/v2/loads/{id}",
        "settings_keys": ["teleroute_username", "teleroute_password"],
        "settings_labels": {
            "teleroute_username": "Teleroute Username",
            "teleroute_password": "Teleroute Password",
        },
        "notes": "JWT auth. client_id: freightexchange, client_secret: secret (fixed).",
    },
    "wtransnet": {
        "name": "Wtransnet",
        "region": "Europe",
        "region_code": "eu",
        "api_status": "manual",
        "docs_url": "https://www.wtransnet.com/",
        "settings_keys": [],
        "settings_labels": {},
        "notes": "No public API. Post manually via wtransnet.com portal.",
    },
    "backhaul": {
        "name": "Backhaul.ie",
        "region": "Europe",
        "region_code": "eu",
        "api_status": "contact",
        "docs_url": "https://www.backhaul.ie/",
        "settings_keys": ["backhaul_api_key"],
        "settings_labels": {"backhaul_api_key": "API Key"},
        "notes": "Contact vendor to confirm API availability.",
    },
    # ── Australia / NZ ──────────────────────────────────────────────────────
    "loadshift": {
        "name": "Loadshift (Australia)",
        "region": "Australia / NZ",
        "region_code": "au",
        "api_status": "contact",
        "docs_url": "https://www.loadshift.com.au/",
        "settings_keys": ["loadshift_api_key"],
        "settings_labels": {"loadshift_api_key": "API Key"},
        "notes": "Contact vendor to confirm API availability. Active since 2007.",
    },
    "teg": {
        "name": "Transport Exchange Group (Courier / Haulage Exchange)",
        "region": "Australia / NZ",
        "region_code": "au",
        "api_status": "contact",
        "docs_url": "https://www.teg.tech/",
        "settings_keys": ["teg_api_key"],
        "settings_labels": {"teg_api_key": "API Key"},
        "notes": "8,500+ logistics providers. Contact for integration docs.",
    },
    # ── Japan / Asia ────────────────────────────────────────────────────────
    "hacobell": {
        "name": "Hacobell (Japan)",
        "region": "Japan",
        "region_code": "jp",
        "api_status": "contact",
        "docs_url": "https://www.hacobell.com/",
        "settings_keys": ["hacobell_api_key"],
        "settings_labels": {"hacobell_api_key": "API Key"},
        "notes": "API exists — contact vendor at hacobell.co.jp for documentation.",
    },
    "deliveree": {
        "name": "Deliveree (SE Asia)",
        "region": "Southeast Asia",
        "region_code": "sea",
        "api_status": "verified",
        "auth_type": "api_key",
        "docs_url": "https://developers.deliveree.com/",
        "base_url": "https://api.deliveree.com",
        "post_endpoint": "/v1/deliveries",
        "delete_endpoint": "/v1/deliveries/{id}/cancel",
        "settings_keys": ["deliveree_api_key"],
        "settings_labels": {"deliveree_api_key": "API Key"},
        "notes": "Covers Thailand, Indonesia, Vietnam, Philippines, Singapore, Malaysia. Webhooks supported.",
    },
    "transportify": {
        "name": "Transportify (Philippines)",
        "region": "Southeast Asia",
        "region_code": "sea",
        "api_status": "verified",
        "auth_type": "api_key",
        "docs_url": "https://www.transportify.com.ph/api-for-tech-teams/",
        "base_url": "https://api.transportify.com.ph",
        "post_endpoint": "/v1/deliveries",
        "delete_endpoint": "/v1/deliveries/{id}",
        "settings_keys": ["transportify_api_key"],
        "settings_labels": {"transportify_api_key": "API Key"},
        "notes": "1M+ customers. Sandbox + production environments. Contact: developers@transportify.com.ph",
    },
    # ── Middle East ─────────────────────────────────────────────────────────
    "saloodo": {
        "name": "Saloodo (DHL — ME/Africa)",
        "region": "Middle East / Africa",
        "region_code": "mea",
        "api_status": "contact",
        "docs_url": "https://www.saloodo.com/mea/",
        "settings_keys": ["saloodo_api_key"],
        "settings_labels": {"saloodo_api_key": "API Key"},
        "notes": "DHL subsidiary. Covers UAE, Saudi Arabia, GCC, Africa. Contact DHL for API access.",
    },
    "trukkin": {
        "name": "Trukkin (UAE / Saudi / Pakistan)",
        "region": "Middle East",
        "region_code": "mea",
        "api_status": "contact",
        "docs_url": "https://www.trukkin.com/",
        "settings_keys": ["trukkin_api_key"],
        "settings_labels": {"trukkin_api_key": "API Key"},
        "notes": "12+ GCC/Pakistan countries. Contact vendor for API credentials.",
    },
    "fetchr": {
        "name": "Fetchr (UAE / Saudi Arabia)",
        "region": "Middle East",
        "region_code": "mea",
        "api_status": "contact",
        "docs_url": "https://www.fetchr.us/",
        "settings_keys": ["fetchr_api_key"],
        "settings_labels": {"fetchr_api_key": "API Key"},
        "notes": "REST API docs available. Covers UAE, Saudi, Egypt, Bahrain.",
    },
    # ── India ───────────────────────────────────────────────────────────────
    "rivigo": {
        "name": "Rivigo (India)",
        "region": "India",
        "region_code": "in",
        "api_status": "contact",
        "docs_url": "https://www.rivigo.com/",
        "settings_keys": ["rivigo_api_key"],
        "settings_labels": {"rivigo_api_key": "API Key"},
        "notes": "India's largest digital trucking marketplace. API via integration partners.",
    },
    "blackbuck": {
        "name": "Blackbuck (India)",
        "region": "India",
        "region_code": "in",
        "api_status": "manual",
        "docs_url": "https://www.blackbuck.com/",
        "settings_keys": [],
        "settings_labels": {},
        "notes": "No public API. Post manually via portal.",
    },
    # ── Brazil / LatAm ──────────────────────────────────────────────────────
    "fretebras": {
        "name": "Fretebras (Brazil / South America)",
        "region": "South America",
        "region_code": "latam",
        "api_status": "verified",
        "auth_type": "api_key",
        "docs_url": "https://developer.fretebras.com.br/",
        "base_url": "https://api.fretebras.com.br",
        "post_endpoint": "/v1/loads",
        "delete_endpoint": "/v1/loads/{id}",
        "settings_keys": ["fretebras_api_key"],
        "settings_labels": {"fretebras_api_key": "API Key"},
        "notes": "Largest freight marketplace in South America. Contact: suporte@fretebras.com.br",
    },
    # ── Africa ──────────────────────────────────────────────────────────────
    "kobo360": {
        "name": "Kobo360 (West / East Africa)",
        "region": "Africa",
        "region_code": "af",
        "api_status": "contact",
        "docs_url": "https://www.kobo360.com/",
        "settings_keys": ["kobo360_api_key"],
        "settings_labels": {"kobo360_api_key": "API Key"},
        "notes": "Covers Nigeria, Ghana, Kenya, Ivory Coast. Y Combinator backed. Contact for API.",
    },
    "loadme": {
        "name": "LoadMe (Middle East / Africa)",
        "region": "Africa / Middle East",
        "region_code": "af",
        "api_status": "contact",
        "docs_url": "https://www.load-me.com/",
        "settings_keys": ["loadme_api_key"],
        "settings_labels": {"loadme_api_key": "API Key"},
        "notes": "Dubai HQ. Real-time truck tracking + mobile bidding. Contact for API.",
    },
}

_VERIFIED_API_KEYS = {k for k, v in PROVIDERS.items() if v["api_status"] == "verified"}

# ── DB schema ─────────────────────────────────────────────────────────────────

_CREATE_POSTINGS = """
CREATE TABLE IF NOT EXISTS load_board_postings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_ref    TEXT NOT NULL,
    board_key       TEXT NOT NULL,
    board_name      TEXT NOT NULL,
    external_id     TEXT DEFAULT '',
    status          TEXT DEFAULT 'active',
    payload_json    TEXT DEFAULT '{}',
    response_json   TEXT DEFAULT '{}',
    error           TEXT DEFAULT '',
    posted_at       TEXT NOT NULL,
    deleted_at      TEXT DEFAULT '',
    UNIQUE(shipment_ref, board_key)
);
"""


def _ensure_table(conn) -> None:
    conn.execute(_CREATE_POSTINGS)
    conn.commit()


# ── DB helpers ────────────────────────────────────────────────────────────────

def _tms_conn():
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    import sqlite3
    conn = get_db()
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Settings ─────────────────────────────────────────────────────────────────

def _all_settings_keys() -> list[str]:
    keys: list[str] = []
    for p in PROVIDERS.values():
        keys.extend(p.get("settings_keys", []))
    return list(dict.fromkeys(keys))  # dedupe, preserve order


def get_board_settings() -> dict[str, str]:
    from .tms_db import get_email_settings  # reuse same get_settings pattern
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT key, value FROM tms_settings WHERE key LIKE 'lb_%' OR key IN ({})".format(
                ",".join("?" * len(_all_settings_keys()))
            ),
            _all_settings_keys(),
        ).fetchall()
    finally:
        conn.close()
    return {r["key"]: r["value"] for r in rows}


def save_board_settings(data: dict) -> None:
    allowed = set(_all_settings_keys())
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    try:
        for key, val in data.items():
            if key in allowed:
                existing = conn.execute(
                    "SELECT key FROM tms_settings WHERE key = ?", (key,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE tms_settings SET value = ? WHERE key = ?", (str(val).strip(), key)
                    )
                else:
                    conn.execute(
                        "INSERT INTO tms_settings (key, value) VALUES (?, ?)", (key, str(val).strip())
                    )
        conn.commit()
    finally:
        conn.close()


# ── Token helpers ─────────────────────────────────────────────────────────────

def _http_post_json(url: str, payload: dict, headers: dict | None = None,
                    timeout: int = 15) -> tuple[dict, int]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"error": str(e)}
        return body, e.code


def _http_post_form(url: str, form: dict, headers: dict | None = None,
                    timeout: int = 15) -> tuple[dict, int]:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"error": str(e)}
        return body, e.code


def _http_delete(url: str, headers: dict | None = None, timeout: int = 15) -> tuple[dict, int]:
    req = urllib.request.Request(url, method="DELETE")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                return json.loads(resp.read()), resp.status
            except Exception:
                return {}, resp.status
    except urllib.error.HTTPError as e:
        return {"error": str(e)}, e.code


def _get_oauth2_token(token_url: str, client_id: str, client_secret: str,
                      username: str = "", password: str = "") -> str | None:
    form: dict[str, str] = {
        "grant_type": "client_credentials" if not username else "password",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if username:
        form["username"] = username
        form["password"] = password
        form["grant_type"] = "password"
    resp, status = _http_post_form(token_url, form)
    if status in (200, 201):
        return resp.get("access_token")
    return None


def _get_jwt_token(token_url: str, username: str, password: str) -> str | None:
    payload = {
        "grant_type": "password",
        "client_id": "freightexchange",
        "client_secret": "secret",
        "scope": "any",
        "username": username,
        "password": password,
    }
    resp, status = _http_post_form(token_url, payload)
    if status in (200, 201):
        return resp.get("access_token")
    return None


# ── Payload builder ───────────────────────────────────────────────────────────

def _build_payload(shipment: dict, board_key: str) -> dict:
    """Build a normalized load posting payload for a given board."""
    base = {
        "origin": shipment.get("origin_port") or shipment.get("shipper_address") or "",
        "destination": shipment.get("destination_port") or shipment.get("consignee_address") or "",
        "equipment_type": shipment.get("container_type") or shipment.get("mode") or "FTL",
        "weight": shipment.get("cargo_weight_kg") or 0,
        "length": "",
        "commodity": shipment.get("cargo_description") or "",
        "pickup_date": shipment.get("etd") or "",
        "delivery_date": shipment.get("eta") or "",
        "reference": shipment.get("shipment_ref") or "",
        "contact_name": shipment.get("shipper_name") or "",
        "notes": shipment.get("special_instructions") or "",
    }

    # Board-specific payload shaping
    if board_key == "dat":
        return {
            "load": {
                "origin": {"city": base["origin"]},
                "destination": {"city": base["destination"]},
                "equipmentType": base["equipment_type"],
                "commodity": base["commodity"],
                "shipmentDate": base["pickup_date"],
                "referenceNumber": base["reference"],
            }
        }
    if board_key in ("truckstop", "123loadboard"):
        return {
            "originCity": base["origin"],
            "destinationCity": base["destination"],
            "equipmentType": base["equipment_type"],
            "commodity": base["commodity"],
            "pickupDate": base["pickup_date"],
            "referenceNumber": base["reference"],
            "comments": base["notes"],
        }
    if board_key == "timocom":
        return {
            "loadingLocation": {"name": base["origin"]},
            "unloadingLocation": {"name": base["destination"]},
            "loadingDate": base["pickup_date"],
            "truckType": base["equipment_type"],
            "description": base["commodity"],
            "referenceNumber": base["reference"],
        }
    if board_key == "teleroute":
        return {
            "pickupCity": base["origin"],
            "deliveryCity": base["destination"],
            "pickupDate": base["pickup_date"],
            "deliveryDate": base["delivery_date"],
            "description": base["commodity"],
            "reference": base["reference"],
        }
    if board_key in ("deliveree", "transportify"):
        return {
            "pickups": [{"name": base["contact_name"], "address": base["origin"],
                         "date": base["pickup_date"]}],
            "deliveries": [{"address": base["destination"], "date": base["delivery_date"]}],
            "note": base["notes"] or base["commodity"],
        }
    if board_key == "fretebras":
        return {
            "origem": base["origin"],
            "destino": base["destination"],
            "data_coleta": base["pickup_date"],
            "tipo_veiculo": base["equipment_type"],
            "descricao": base["commodity"],
            "referencia": base["reference"],
        }
    # Generic fallback
    return base


# ── Per-provider post logic ───────────────────────────────────────────────────

def _post_to_board(board_key: str, settings: dict, shipment: dict) -> dict[str, Any]:
    """
    Post a load to a single board. Returns:
      {ok: bool, external_id: str, response: dict, error: str}
    """
    provider = PROVIDERS.get(board_key)
    if not provider:
        return {"ok": False, "external_id": "", "response": {}, "error": "Unknown provider"}

    status = provider["api_status"]
    if status == "manual":
        return {"ok": False, "external_id": "", "response": {},
                "error": f"Manual posting required — visit {provider['docs_url']}"}
    if status == "contact":
        return {"ok": False, "external_id": "", "response": {},
                "error": "API credentials not yet available — contact vendor to obtain API access."}

    payload = _build_payload(shipment, board_key)
    auth_type = provider.get("auth_type", "")
    base_url = provider.get("base_url", "")
    post_url = base_url + provider.get("post_endpoint", "")

    headers: dict[str, str] = {"Content-Type": "application/json"}

    try:
        if auth_type == "api_key":
            # Different boards use different header names
            key_setting = provider["settings_keys"][0]
            api_key = settings.get(key_setting, "")
            if not api_key:
                return {"ok": False, "external_id": "", "response": {},
                        "error": f"Missing API key: {key_setting}"}
            headers["Api-Key"] = api_key
            headers["Authorization"] = f"Bearer {api_key}"

        elif auth_type == "basic":
            import base64
            user = settings.get("dat_username", "")
            pwd = settings.get("dat_password", "")
            if not user or not pwd:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "Missing DAT username or password"}
            creds = base64.b64encode(f"{user}:{pwd}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"

        elif auth_type == "oauth2_client":
            cid = settings.get(provider["settings_keys"][0], "")
            csec = settings.get(provider["settings_keys"][1], "")
            if not cid or not csec:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "Missing OAuth2 client credentials"}
            token_url = base_url + provider.get("token_endpoint", "/oauth/token")
            token = _get_oauth2_token(token_url, cid, csec)
            if not token:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "OAuth2 token request failed"}
            headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "oauth2_password":
            cid = settings.get(provider["settings_keys"][0], "")
            csec = settings.get(provider["settings_keys"][1], "")
            user = settings.get(provider["settings_keys"][2], "")
            pwd = settings.get(provider["settings_keys"][3], "")
            if not cid or not csec:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "Missing Truckstop client credentials"}
            token_url = base_url + provider.get("token_endpoint", "/oauth/token")
            token = _get_oauth2_token(token_url, cid, csec, user, pwd)
            if not token:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "OAuth2 password token request failed"}
            headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "jwt_password":
            user = settings.get(provider["settings_keys"][0], "")
            pwd = settings.get(provider["settings_keys"][1], "")
            if not user or not pwd:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "Missing Teleroute credentials"}
            token_url = base_url + provider.get("token_endpoint", "/user/token")
            token = _get_jwt_token(token_url, user, pwd)
            if not token:
                return {"ok": False, "external_id": "", "response": {},
                        "error": "JWT token request failed"}
            headers["Authorization"] = f"Bearer {token}"
            headers["Accept-version"] = "v2"

        resp, http_status = _http_post_json(post_url, payload, headers)
        if http_status in (200, 201):
            ext_id = (
                str(resp.get("id") or resp.get("loadId") or resp.get("offerId") or
                    resp.get("deliveryId") or resp.get("shipmentId") or "")
            )
            return {"ok": True, "external_id": ext_id, "response": resp, "error": ""}
        return {"ok": False, "external_id": "", "response": resp,
                "error": f"HTTP {http_status}: {resp.get('error') or resp.get('message') or 'Post failed'}"}

    except Exception as exc:
        return {"ok": False, "external_id": "", "response": {}, "error": str(exc)}


# ── Public functions ──────────────────────────────────────────────────────────

def get_all_providers() -> list[dict[str, Any]]:
    """Return provider list enriched with whether credentials are saved."""
    settings = get_board_settings()
    result = []
    for key, p in PROVIDERS.items():
        creds_saved = all(settings.get(k, "") for k in p.get("settings_keys", []))
        result.append({
            **p,
            "key": key,
            "creds_saved": creds_saved,
        })
    return result


def post_load(shipment_ref: str, board_keys: list[str]) -> dict[str, dict]:
    """
    Post a shipment to one or more load boards.
    Returns {board_key: result_dict} for each board.
    """
    from .tms_db import get_db
    conn = _tms_conn()
    _ensure_table(conn)

    # Load shipment
    shipment_row = conn.execute(
        "SELECT * FROM shipments WHERE shipment_ref = ?", (shipment_ref,)
    ).fetchone()
    if not shipment_row:
        conn.close()
        return {k: {"ok": False, "error": "Shipment not found"} for k in board_keys}

    shipment = dict(shipment_row)
    settings = get_board_settings()
    results: dict[str, dict] = {}

    for board_key in board_keys:
        if board_key not in PROVIDERS:
            results[board_key] = {"ok": False, "error": "Unknown board"}
            continue

        result = _post_to_board(board_key, settings, shipment)
        results[board_key] = result

        # Upsert posting record
        now = _now()
        existing = conn.execute(
            "SELECT id FROM load_board_postings WHERE shipment_ref = ? AND board_key = ?",
            (shipment_ref, board_key),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE load_board_postings
                   SET external_id = ?, status = ?, response_json = ?, error = ?, posted_at = ?
                   WHERE shipment_ref = ? AND board_key = ?""",
                (
                    result.get("external_id", ""),
                    "active" if result["ok"] else "failed",
                    json.dumps(result.get("response", {})),
                    result.get("error", ""),
                    now,
                    shipment_ref,
                    board_key,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO load_board_postings
                   (shipment_ref, board_key, board_name, external_id, status,
                    payload_json, response_json, error, posted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    shipment_ref,
                    board_key,
                    PROVIDERS[board_key]["name"],
                    result.get("external_id", ""),
                    "active" if result["ok"] else "failed",
                    json.dumps(_build_payload(shipment, board_key)),
                    json.dumps(result.get("response", {})),
                    result.get("error", ""),
                    now,
                ),
            )

    conn.commit()
    conn.close()
    return results


def delete_posting(posting_id: int) -> bool:
    conn = _tms_conn()
    _ensure_table(conn)

    row = conn.execute(
        "SELECT * FROM load_board_postings WHERE id = ?", (posting_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False

    posting = dict(row)
    board_key = posting["board_key"]
    external_id = posting["external_id"]
    provider = PROVIDERS.get(board_key, {})

    ok = False
    if external_id and provider.get("api_status") == "verified":
        settings = get_board_settings()
        delete_url = (
            provider.get("base_url", "") +
            provider.get("delete_endpoint", "/{id}").replace("{id}", external_id)
        )
        # We'd need auth headers here too — for now just fire DELETE with API key if available
        headers: dict[str, str] = {}
        for key_name in provider.get("settings_keys", []):
            val = settings.get(key_name, "")
            if val:
                headers["Authorization"] = f"Bearer {val}"
                headers["Api-Key"] = val
                break
        _, status = _http_delete(delete_url, headers)
        ok = status in (200, 204)

    conn.execute(
        "UPDATE load_board_postings SET status = 'deleted', deleted_at = ? WHERE id = ?",
        (_now(), posting_id),
    )
    conn.commit()
    conn.close()
    return ok


def get_active_postings(shipment_ref: str | None = None) -> list[dict[str, Any]]:
    conn = _tms_conn()
    _ensure_table(conn)

    if shipment_ref:
        rows = conn.execute(
            "SELECT * FROM load_board_postings WHERE shipment_ref = ? ORDER BY posted_at DESC",
            (shipment_ref,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM load_board_postings ORDER BY posted_at DESC LIMIT 200"
        ).fetchall()

    conn.close()
    return [dict(r) for r in rows]
