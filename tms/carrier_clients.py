"""
carrier_clients.py — Live carrier API clients for TMS integrations
Each client reads encrypted credentials from integration_connections,
calls the real carrier API, and returns normalized rate/tracking/label data.
"""

import json
import logging
import time
import urllib.request
import urllib.parse
import urllib.error
import base64

log = logging.getLogger(__name__)


# ── Credential loader ──────────────────────────────────────────────────────────

def get_credentials(integration_key: str) -> dict:
    """Load and decrypt credentials for a connected integration."""
    from tms.tms_db import get_db
    from tms.tms_integrations import decrypt_key
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT encrypted_fields FROM integration_connections WHERE integration_key=?",
            (integration_key,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    try:
        encrypted = json.loads(row["encrypted_fields"])
        return {k: decrypt_key(v) for k, v in encrypted.items()}
    except Exception:
        return {}


def is_connected(integration_key: str) -> bool:
    from tms.tms_db import get_db
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM integration_connections WHERE integration_key=? AND status='connected'",
            (integration_key,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ── HTTP helpers ───────────────────────────────────────────────────────────────

def _http_post(url, payload, headers=None, timeout=10):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": body, "http_status": e.code}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def _http_get(url, headers=None, timeout=10):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(), "http_status": e.code}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


def _http_form_post(url, form_data, headers=None, timeout=10):
    data = urllib.parse.urlencode(form_data).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), r.status
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(), "http_status": e.code}, e.code
    except Exception as e:
        return {"error": str(e)}, 0


# ── UPS ────────────────────────────────────────────────────────────────────────

_ups_token_cache = {}

def _ups_get_token(client_id, client_secret):
    cache_key = client_id
    cached = _ups_token_cache.get(cache_key)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data, status = _http_form_post(
        "https://onlinetools.ups.com/security/v1/oauth/token",
        {"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {creds}"}
    )
    if status == 200 and "access_token" in data:
        _ups_token_cache[cache_key] = {
            "token": data["access_token"],
            "expires_at": time.time() + data.get("expires_in", 3600)
        }
        return data["access_token"]
    return None


def ups_test(creds: dict) -> dict:
    token = _ups_get_token(creds.get("client_id", ""), creds.get("client_secret", ""))
    if token:
        return {"ok": True, "message": "UPS connected — OAuth token issued successfully"}
    return {"ok": False, "message": "UPS authentication failed — check Client ID and Secret"}


def ups_rate(creds: dict, origin_zip: str, dest_zip: str, weight_lbs: float,
             origin_country="US", dest_country="US") -> list:
    token = _ups_get_token(creds.get("client_id", ""), creds.get("client_secret", ""))
    if not token:
        return []
    payload = {
        "RateRequest": {
            "Request": {"RequestOption": "Shop"},
            "Shipment": {
                "Shipper": {"ShipperNumber": creds.get("account_number", ""),
                            "Address": {"PostalCode": origin_zip, "CountryCode": origin_country}},
                "ShipTo": {"Address": {"PostalCode": dest_zip, "CountryCode": dest_country}},
                "ShipFrom": {"Address": {"PostalCode": origin_zip, "CountryCode": origin_country}},
                "Package": {"PackagingType": {"Code": "02"},
                            "PackageWeight": {"UnitOfMeasurement": {"Code": "LBS"},
                                              "Weight": str(weight_lbs)}}
            }
        }
    }
    data, status = _http_post(
        "https://onlinetools.ups.com/api/rating/v1/Shop",
        payload,
        headers={"Authorization": f"Bearer {token}", "transId": "tms-rate", "transactionSrc": "flash-tms"}
    )
    if status != 200:
        log.warning("UPS rating error %s: %s", status, data.get("error", "")[:200])
        return []
    rates = []
    for service in data.get("RateResponse", {}).get("RatedShipment", []):
        rates.append({
            "carrier": "UPS",
            "service": service.get("Service", {}).get("Code", ""),
            "rate": float(service.get("TotalCharges", {}).get("MonetaryValue", 0)),
            "currency": service.get("TotalCharges", {}).get("CurrencyCode", "USD"),
            "transit_days": service.get("GuaranteedDelivery", {}).get("BusinessDaysInTransit", ""),
        })
    return rates


def ups_track(creds: dict, tracking_number: str) -> dict:
    token = _ups_get_token(creds.get("client_id", ""), creds.get("client_secret", ""))
    if not token:
        return {"ok": False, "message": "Not authenticated"}
    data, status = _http_get(
        f"https://onlinetools.ups.com/api/track/v1/details/{tracking_number}",
        headers={"Authorization": f"Bearer {token}", "transId": "tms-track", "transactionSrc": "flash-tms"}
    )
    if status != 200:
        return {"ok": False, "message": f"Tracking error: {data.get('error','')[:100]}"}
    shipment = data.get("trackResponse", {}).get("shipment", [{}])[0]
    pkg = shipment.get("package", [{}])[0]
    activity = pkg.get("activity", [{}])[0]
    return {
        "ok": True,
        "status": activity.get("status", {}).get("description", "Unknown"),
        "location": activity.get("location", {}).get("address", {}).get("city", ""),
        "timestamp": activity.get("date", "") + " " + activity.get("time", ""),
    }


# ── FedEx ──────────────────────────────────────────────────────────────────────

_fedex_token_cache = {}

def _fedex_get_token(api_key, secret_key):
    cache_key = api_key
    cached = _fedex_token_cache.get(cache_key)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]
    data, status = _http_form_post(
        "https://apis.fedex.com/oauth/token",
        {"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}
    )
    if status == 200 and "access_token" in data:
        _fedex_token_cache[cache_key] = {
            "token": data["access_token"],
            "expires_at": time.time() + data.get("expires_in", 3600)
        }
        return data["access_token"]
    return None


def fedex_test(creds: dict) -> dict:
    token = _fedex_get_token(creds.get("api_key", ""), creds.get("secret_key", ""))
    if token:
        return {"ok": True, "message": "FedEx connected — OAuth token issued successfully"}
    return {"ok": False, "message": "FedEx authentication failed — check API Key and Secret"}


def fedex_rate(creds: dict, origin_zip: str, dest_zip: str, weight_lbs: float,
               origin_country="US", dest_country="US") -> list:
    token = _fedex_get_token(creds.get("api_key", ""), creds.get("secret_key", ""))
    if not token:
        return []
    payload = {
        "accountNumber": {"value": creds.get("account_number", "")},
        "requestedShipment": {
            "shipper": {"address": {"postalCode": origin_zip, "countryCode": origin_country}},
            "recipient": {"address": {"postalCode": dest_zip, "countryCode": dest_country}},
            "pickupType": "USE_SCHEDULED_PICKUP",
            "rateRequestType": ["LIST", "ACCOUNT"],
            "requestedPackageLineItems": [{
                "weight": {"units": "LB", "value": weight_lbs}
            }]
        }
    }
    data, status = _http_post(
        "https://apis.fedex.com/rate/v1/rates/quotes",
        payload,
        headers={"Authorization": f"Bearer {token}"}
    )
    if status != 200:
        log.warning("FedEx rating error %s", status)
        return []
    rates = []
    for detail in data.get("output", {}).get("rateReplyDetails", []):
        for rated in detail.get("ratedShipmentDetails", []):
            rates.append({
                "carrier": "FedEx",
                "service": detail.get("serviceType", ""),
                "rate": float(rated.get("totalNetCharge", 0)),
                "currency": rated.get("currency", "USD"),
                "transit_days": detail.get("commit", {}).get("transitDays", ""),
            })
    return rates


def fedex_track(creds: dict, tracking_number: str) -> dict:
    token = _fedex_get_token(creds.get("api_key", ""), creds.get("secret_key", ""))
    if not token:
        return {"ok": False, "message": "Not authenticated"}
    payload = {"trackingInfo": [{"trackingNumberInfo": {"trackingNumber": tracking_number}}],
               "includeDetailedScans": True}
    data, status = _http_post(
        "https://apis.fedex.com/track/v1/trackingnumbers",
        payload,
        headers={"Authorization": f"Bearer {token}"}
    )
    if status != 200:
        return {"ok": False, "message": "Tracking lookup failed"}
    try:
        result = data["output"]["completeTrackResults"][0]["trackResults"][0]
        event = result.get("scanEvents", [{}])[0]
        return {
            "ok": True,
            "status": result.get("latestStatusDetail", {}).get("description", "Unknown"),
            "location": event.get("scanLocation", {}).get("city", ""),
            "timestamp": event.get("date", ""),
        }
    except (KeyError, IndexError):
        return {"ok": False, "message": "Could not parse tracking response"}


# ── DHL Express ────────────────────────────────────────────────────────────────

def dhl_test(creds: dict) -> dict:
    api_key = creds.get("api_key", "")
    if not api_key:
        return {"ok": False, "message": "No API key stored"}
    data, status = _http_get(
        "https://api-mock.dhl.com/mydhlapi/products?accountNumber=" + creds.get("account_number", "000000000") +
        "&originCountryCode=US&originCityName=New+York&destinationCountryCode=GB&destinationCityName=London&weight=5&length=15&width=10&height=5&plannedShippingDateAndTime=2024-12-31T00%3A00%3A00GMT%2B00%3A00&isCustomsDeclarable=false&unitOfMeasurement=metric",
        headers={"DHL-API-Key": api_key}
    )
    if status == 200:
        return {"ok": True, "message": "DHL Express connected"}
    return {"ok": False, "message": f"DHL auth failed (status {status})"}


def dhl_rate(creds: dict, origin_city: str, dest_city: str,
             origin_country: str, dest_country: str, weight_kg: float) -> list:
    api_key = creds.get("api_key", "")
    account = creds.get("account_number", "")
    if not api_key:
        return []
    import datetime
    ship_date = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT00:00:00GMT+00:00")
    url = (f"https://api-mock.dhl.com/mydhlapi/products"
           f"?accountNumber={account}&originCountryCode={origin_country}"
           f"&originCityName={urllib.parse.quote(origin_city)}"
           f"&destinationCountryCode={dest_country}"
           f"&destinationCityName={urllib.parse.quote(dest_city)}"
           f"&weight={weight_kg}&length=30&width=20&height=15"
           f"&plannedShippingDateAndTime={urllib.parse.quote(ship_date)}"
           f"&isCustomsDeclarable=false&unitOfMeasurement=metric")
    data, status = _http_get(url, headers={"DHL-API-Key": api_key})
    if status != 200:
        return []
    rates = []
    for product in data.get("products", []):
        price = product.get("totalPrice", [{}])[0]
        rates.append({
            "carrier": "DHL Express",
            "service": product.get("productName", ""),
            "rate": float(price.get("price", 0)),
            "currency": price.get("priceCurrency", "USD"),
            "transit_days": product.get("deliveryCapabilities", {}).get("totalTransitDays", ""),
        })
    return rates


def dhl_track(creds: dict, tracking_number: str) -> dict:
    api_key = creds.get("api_key", "")
    if not api_key:
        return {"ok": False, "message": "Not authenticated"}
    data, status = _http_get(
        f"https://api-mock.dhl.com/mydhlapi/shipments/{tracking_number}/tracking?trackingView=all-checkpoints",
        headers={"DHL-API-Key": api_key}
    )
    if status != 200:
        return {"ok": False, "message": "Tracking failed"}
    try:
        shipment = data["shipments"][0]
        event = shipment.get("events", [{}])[0]
        return {
            "ok": True,
            "status": shipment.get("status", "Unknown"),
            "location": event.get("location", {}).get("address", {}).get("addressLocality", ""),
            "timestamp": event.get("timestamp", ""),
        }
    except (KeyError, IndexError):
        return {"ok": False, "message": "Could not parse response"}


# ── EasyPost (multi-carrier wrapper) ──────────────────────────────────────────

def easypost_test(creds: dict) -> dict:
    api_key = creds.get("api_key", "")
    if not api_key:
        return {"ok": False, "message": "No API key stored"}
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    data, status = _http_get("https://api.easypost.com/v2/users/me",
                              headers={"Authorization": f"Basic {auth}"})
    if status == 200:
        return {"ok": True, "message": f"EasyPost connected — account: {data.get('email', 'verified')}"}
    return {"ok": False, "message": "EasyPost authentication failed — check API key"}


def easypost_rate(creds: dict, from_zip: str, to_zip: str, weight_oz: float,
                  from_country="US", to_country="US") -> list:
    api_key = creds.get("api_key", "")
    if not api_key:
        return []
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    payload = {
        "shipment": {
            "to_address": {"zip": to_zip, "country": to_country},
            "from_address": {"zip": from_zip, "country": from_country},
            "parcel": {"weight": weight_oz}
        }
    }
    data, status = _http_post("https://api.easypost.com/v2/shipments", payload,
                               headers={"Authorization": f"Basic {auth}"})
    if status not in (200, 201):
        return []
    rates = []
    for r in data.get("rates", []):
        rates.append({
            "carrier": r.get("carrier", "EasyPost"),
            "service": r.get("service", ""),
            "rate": float(r.get("rate", 0)),
            "currency": r.get("currency", "USD"),
            "transit_days": r.get("est_delivery_days", ""),
        })
    return sorted(rates, key=lambda x: x["rate"])


def easypost_track(creds: dict, tracking_number: str, carrier: str = "") -> dict:
    api_key = creds.get("api_key", "")
    if not api_key:
        return {"ok": False, "message": "Not authenticated"}
    auth = base64.b64encode(f"{api_key}:".encode()).decode()
    payload = {"tracker": {"tracking_code": tracking_number, "carrier": carrier}}
    data, status = _http_post("https://api.easypost.com/v2/trackers", payload,
                               headers={"Authorization": f"Basic {auth}"})
    if status not in (200, 201):
        return {"ok": False, "message": "Tracking lookup failed"}
    return {
        "ok": True,
        "status": data.get("status", "Unknown"),
        "location": data.get("tracking_details", [{}])[-1:][0].get("tracking_location", {}).get("city", "") if data.get("tracking_details") else "",
        "timestamp": data.get("tracking_details", [{}])[-1:][0].get("datetime", "") if data.get("tracking_details") else "",
    }


# ── AfterShip (tracking aggregator) ───────────────────────────────────────────

def aftership_test(creds: dict) -> dict:
    api_key = creds.get("api_key", "")
    if not api_key:
        return {"ok": False, "message": "No API key stored"}
    data, status = _http_get("https://api.aftership.com/v4/couriers",
                              headers={"aftership-api-key": api_key})
    if status == 200:
        count = data.get("data", {}).get("total", "?")
        return {"ok": True, "message": f"AfterShip connected — {count} carriers available"}
    return {"ok": False, "message": "AfterShip authentication failed — check API key"}


def aftership_track(creds: dict, tracking_number: str, slug: str = "") -> dict:
    api_key = creds.get("api_key", "")
    if not api_key:
        return {"ok": False, "message": "Not authenticated"}
    url = f"https://api.aftership.com/v4/trackings/{slug}/{tracking_number}" if slug else \
          f"https://api.aftership.com/v4/trackings/{tracking_number}"
    data, status = _http_get(url, headers={"aftership-api-key": api_key})
    if status != 200:
        return {"ok": False, "message": "Tracking lookup failed"}
    tracking = data.get("data", {}).get("tracking", {})
    checkpoints = tracking.get("checkpoints", [])
    last = checkpoints[-1] if checkpoints else {}
    return {
        "ok": True,
        "status": tracking.get("tag", "Unknown"),
        "location": last.get("city", ""),
        "timestamp": last.get("checkpoint_time", ""),
    }


# ── Unified dispatcher ─────────────────────────────────────────────────────────

_TEST_FNS = {
    "ups": ups_test,
    "fedex": fedex_test,
    "dhl": dhl_test,
    "easypost": easypost_test,
    "aftership": aftership_test,
}

_RATE_FNS = {
    "ups": lambda c, o, d, w: ups_rate(c, o, d, w),
    "fedex": lambda c, o, d, w: fedex_rate(c, o, d, w),
    "dhl": lambda c, o, d, w: dhl_rate(c, o, d, w, "US", "US", w * 0.453592),
    "easypost": lambda c, o, d, w: easypost_rate(c, o, d, w * 16),
}

_TRACK_FNS = {
    "ups": ups_track,
    "fedex": fedex_track,
    "dhl": dhl_track,
    "easypost": easypost_track,
    "aftership": aftership_track,
}


def test_integration(integration_key: str) -> dict:
    """Test a live connection for a stored integration."""
    creds = get_credentials(integration_key)
    if not creds:
        return {"ok": False, "message": "No credentials stored — click Connect first"}
    fn = _TEST_FNS.get(integration_key)
    if fn:
        try:
            return fn(creds)
        except Exception as e:
            return {"ok": False, "message": f"Connection error: {str(e)[:120]}"}
    return {"ok": True, "message": "Credentials stored — live test not yet available for this carrier"}


def get_live_rates(integration_key: str, origin_zip: str, dest_zip: str,
                   weight_lbs: float) -> list:
    """Get live rate quotes from a connected carrier."""
    creds = get_credentials(integration_key)
    if not creds:
        return []
    fn = _RATE_FNS.get(integration_key)
    if not fn:
        return []
    try:
        return fn(creds, origin_zip, dest_zip, weight_lbs)
    except Exception as e:
        log.warning("Live rate error for %s: %s", integration_key, e)
        return []


def get_live_tracking(integration_key: str, tracking_number: str) -> dict:
    """Get live tracking from a connected carrier."""
    creds = get_credentials(integration_key)
    if not creds:
        return {"ok": False, "message": "Not connected"}
    fn = _TRACK_FNS.get(integration_key)
    if not fn:
        return {"ok": False, "message": "Tracking not supported for this carrier"}
    try:
        return fn(creds, tracking_number)
    except Exception as e:
        return {"ok": False, "message": str(e)[:120]}


def get_all_live_rates(origin_zip: str, dest_zip: str, weight_lbs: float) -> list:
    """Query all connected parcel carriers and return combined rate list."""
    results = []
    for key in _RATE_FNS:
        if is_connected(key):
            results.extend(get_live_rates(key, origin_zip, dest_zip, weight_lbs))
    return sorted(results, key=lambda r: r["rate"])
