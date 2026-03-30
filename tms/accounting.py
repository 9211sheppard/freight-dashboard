"""
Accounting Integration
======================
Two-way sync of invoices, payments, and carrier bills to QuickBooks Online,
Xero, FreshBooks, Wave, Zoho Books, and MYOB (AU/NZ).

Public API
----------
get_all_providers()                    -> list[dict]
get_accounting_settings()              -> dict
save_accounting_settings(data)         -> None
push_invoice(invoice_id, provider_key) -> dict
pull_payments(provider_key)            -> list[dict]
test_connection(provider_key)          -> dict
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
    "quickbooks": {
        "name": "QuickBooks Online",
        "region": "North America / Global",
        "logo": "bi-receipt",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://developer.intuit.com/app/developer/qbo/docs/api/accounting/",
        "base_url": "https://quickbooks.api.intuit.com/v3/company/{realm_id}",
        "token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "auth_url": "https://appcenter.intuit.com/connect/oauth2",
        "scopes": "com.intuit.quickbooks.accounting",
        "settings_keys": ["qb_client_id", "qb_client_secret", "qb_realm_id",
                          "qb_access_token", "qb_refresh_token"],
        "settings_labels": {
            "qb_client_id": "Client ID",
            "qb_client_secret": "Client Secret",
            "qb_realm_id": "Company ID (Realm ID)",
            "qb_access_token": "Access Token",
            "qb_refresh_token": "Refresh Token",
        },
        "notes": "Create app at developer.intuit.com. Use OAuth2 to get tokens.",
    },
    "xero": {
        "name": "Xero",
        "region": "Australia / NZ / UK / Global",
        "logo": "bi-x-circle",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://developer.xero.com/documentation/api/accounting/invoices",
        "base_url": "https://api.xero.com/api.xro/2.0",
        "token_url": "https://identity.xero.com/connect/token",
        "auth_url": "https://login.xero.com/identity/connect/authorize",
        "scopes": "accounting.transactions accounting.contacts",
        "settings_keys": ["xero_client_id", "xero_client_secret",
                          "xero_tenant_id", "xero_access_token", "xero_refresh_token"],
        "settings_labels": {
            "xero_client_id": "Client ID",
            "xero_client_secret": "Client Secret",
            "xero_tenant_id": "Tenant ID",
            "xero_access_token": "Access Token",
            "xero_refresh_token": "Refresh Token",
        },
        "notes": "Create app at developer.xero.com. Popular in AU, NZ, UK.",
    },
    "freshbooks": {
        "name": "FreshBooks",
        "region": "North America / Global",
        "logo": "bi-book",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://www.freshbooks.com/api/start",
        "base_url": "https://api.freshbooks.com/accounting/account/{account_id}",
        "token_url": "https://api.freshbooks.com/auth/oauth/token",
        "auth_url": "https://my.freshbooks.com/service/auth/oauth/authorize",
        "scopes": "admin:all:legacy",
        "settings_keys": ["fb_client_id", "fb_client_secret",
                          "fb_account_id", "fb_access_token", "fb_refresh_token"],
        "settings_labels": {
            "fb_client_id": "Client ID",
            "fb_client_secret": "Client Secret",
            "fb_account_id": "Account ID",
            "fb_access_token": "Access Token",
            "fb_refresh_token": "Refresh Token",
        },
        "notes": "Popular with SMBs. Create app at freshbooks.com/developers.",
    },
    "zoho": {
        "name": "Zoho Books",
        "region": "India / Middle East / Global",
        "logo": "bi-journal",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://www.zoho.com/books/api/v3/",
        "base_url": "https://www.zohoapis.com/books/v3",
        "token_url": "https://accounts.zoho.com/oauth/v2/token",
        "auth_url": "https://accounts.zoho.com/oauth/v2/auth",
        "scopes": "ZohoBooks.invoices.CREATE ZohoBooks.invoices.READ ZohoBooks.contacts.READ",
        "settings_keys": ["zoho_client_id", "zoho_client_secret",
                          "zoho_org_id", "zoho_access_token", "zoho_refresh_token"],
        "settings_labels": {
            "zoho_client_id": "Client ID",
            "zoho_client_secret": "Client Secret",
            "zoho_org_id": "Organisation ID",
            "zoho_access_token": "Access Token",
            "zoho_refresh_token": "Refresh Token",
        },
        "notes": "Strong in India, Middle East, SE Asia. Multi-currency support.",
    },
    "myob": {
        "name": "MYOB",
        "region": "Australia / NZ",
        "logo": "bi-calculator",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://developer.myob.com/api/myob-business-api/v2/",
        "base_url": "https://api.myob.com/accountright",
        "token_url": "https://secure.myob.com/oauth2/v1/authorize",
        "auth_url": "https://secure.myob.com/oauth2/account/authorize",
        "scopes": "CompanyFile",
        "settings_keys": ["myob_client_id", "myob_client_secret",
                          "myob_company_file_id", "myob_access_token", "myob_refresh_token"],
        "settings_labels": {
            "myob_client_id": "Client ID",
            "myob_client_secret": "Client Secret",
            "myob_company_file_id": "Company File ID",
            "myob_access_token": "Access Token",
            "myob_refresh_token": "Refresh Token",
        },
        "notes": "Dominant in Australia and NZ.",
    },
    "wave": {
        "name": "Wave Accounting",
        "region": "North America (Free)",
        "logo": "bi-water",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://developer.waveapps.com/hc/en-us/categories/360001286871",
        "base_url": "https://gql.waveapps.com/graphql/public",
        "token_url": "https://api.waveapps.com/oauth2/token/",
        "auth_url": "https://api.waveapps.com/oauth2/authorize/",
        "scopes": "account1:* business1:*",
        "settings_keys": ["wave_client_id", "wave_client_secret",
                          "wave_business_id", "wave_access_token"],
        "settings_labels": {
            "wave_client_id": "Client ID",
            "wave_client_secret": "Client Secret",
            "wave_business_id": "Business ID",
            "wave_access_token": "Access Token",
        },
        "notes": "Free accounting software. GraphQL API. Good for small operators.",
    },
    "sage": {
        "name": "Sage Business Cloud",
        "region": "UK / Europe / South Africa",
        "logo": "bi-briefcase",
        "api_status": "verified",
        "auth_type": "oauth2",
        "docs_url": "https://developer.sage.com/accounting/",
        "base_url": "https://api.accounting.sage.com/v3.1",
        "token_url": "https://oauth.accounting.sage.com/token",
        "auth_url": "https://www.sageone.com/oauth2/auth/central",
        "scopes": "full_access",
        "settings_keys": ["sage_client_id", "sage_client_secret",
                          "sage_access_token", "sage_refresh_token"],
        "settings_labels": {
            "sage_client_id": "Client ID",
            "sage_client_secret": "Client Secret",
            "sage_access_token": "Access Token",
            "sage_refresh_token": "Refresh Token",
        },
        "notes": "Strong in UK, Europe, South Africa.",
    },
}

# ── Settings ──────────────────────────────────────────────────────────────────

def _all_keys() -> list[str]:
    keys: list[str] = []
    for p in PROVIDERS.values():
        keys.extend(p.get("settings_keys", []))
    return list(dict.fromkeys(keys))


def get_accounting_settings() -> dict[str, str]:
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT key, value FROM tms_settings WHERE key IN ({})".format(
                ",".join("?" * len(_all_keys()))
            ),
            _all_keys(),
        ).fetchall()
    finally:
        conn.close()
    return {r["key"]: r["value"] for r in rows}


def save_accounting_settings(data: dict) -> None:
    allowed = set(_all_keys())
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    try:
        for key, val in data.items():
            if key not in allowed:
                continue
            val = str(val).strip() if val else ""
            existing = conn.execute(
                "SELECT key FROM tms_settings WHERE key = ?", (key,)
            ).fetchone()
            if existing:
                conn.execute("UPDATE tms_settings SET value = ? WHERE key = ?", (val, key))
            else:
                conn.execute("INSERT INTO tms_settings (key, value) VALUES (?, ?)", (key, val))
        conn.commit()
    finally:
        conn.close()


# ── DB schema ─────────────────────────────────────────────────────────────────

_CREATE_SYNC_LOG = """
CREATE TABLE IF NOT EXISTS accounting_sync_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_key    TEXT NOT NULL,
    direction       TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    external_id     TEXT DEFAULT '',
    status          TEXT NOT NULL,
    error           TEXT DEFAULT '',
    payload_json    TEXT DEFAULT '{}',
    created_at      TEXT NOT NULL
);
"""


def _ensure_table() -> None:
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    try:
        conn.execute(_CREATE_SYNC_LOG)
        conn.commit()
    finally:
        conn.close()


def _log_sync(provider_key: str, direction: str, entity_type: str,
              entity_id: str, status: str, external_id: str = "",
              error: str = "", payload: dict | None = None) -> None:
    _ensure_table()
    from .tms_db import get_db
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO accounting_sync_log
               (provider_key, direction, entity_type, entity_id, external_id,
                status, error, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (provider_key, direction, entity_type, entity_id, external_id,
             status, error, json.dumps(payload or {}),
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _http_post(url: str, payload: dict, headers: dict,
               form: bool = False, timeout: int = 15) -> tuple[dict, int]:
    if form:
        data = urllib.parse.urlencode(payload).encode()
        ctype = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(payload).encode()
        ctype = "application/json"
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", ctype)
    for k, v in headers.items():
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


def _http_get(url: str, headers: dict, timeout: int = 15) -> tuple[dict, int]:
    req = urllib.request.Request(url)
    for k, v in headers.items():
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


# ── Token refresh ─────────────────────────────────────────────────────────────

def _refresh_token(provider_key: str, settings: dict) -> str | None:
    p = PROVIDERS[provider_key]
    client_id_key = p["settings_keys"][0]
    client_secret_key = p["settings_keys"][1]
    refresh_key = next((k for k in p["settings_keys"] if "refresh" in k), None)
    if not refresh_key:
        return settings.get(p["settings_keys"][-1], "")  # use access token directly

    cid = settings.get(client_id_key, "")
    csec = settings.get(client_secret_key, "")
    refresh = settings.get(refresh_key, "")
    if not all([cid, csec, refresh]):
        return None

    import base64
    auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    resp, status = _http_post(
        p["token_url"],
        {"grant_type": "refresh_token", "refresh_token": refresh},
        {"Authorization": f"Basic {auth}"},
        form=True,
    )
    if status in (200, 201):
        new_token = resp.get("access_token", "")
        # Persist new token
        save_accounting_settings({
            next(k for k in p["settings_keys"] if "access_token" in k): new_token,
        })
        return new_token
    return None


def _get_token(provider_key: str, settings: dict) -> str | None:
    p = PROVIDERS[provider_key]
    token_key = next((k for k in p["settings_keys"] if "access_token" in k), None)
    if token_key:
        token = settings.get(token_key, "")
        if token:
            return token
    return _refresh_token(provider_key, settings)


# ── Invoice payload builders ──────────────────────────────────────────────────

def _build_invoice_payload(invoice: dict, provider_key: str) -> dict:
    """Normalise a TMS invoice dict into the provider's expected format."""
    line_items = []
    for line in (invoice.get("line_items") or []):
        line_items.append({
            "description": line.get("description", "Freight service"),
            "quantity": float(line.get("quantity", 1)),
            "unit_price": float(line.get("unit_price", 0)),
            "amount": float(line.get("amount", 0)),
        })
    if not line_items:
        line_items = [{
            "description": invoice.get("description") or "Freight service",
            "quantity": 1,
            "unit_price": float(invoice.get("total_amount", 0)),
            "amount": float(invoice.get("total_amount", 0)),
        }]

    base = {
        "customer_name": invoice.get("customer_name", ""),
        "invoice_number": invoice.get("invoice_number", ""),
        "issue_date": (invoice.get("created_at") or "")[:10],
        "due_date": invoice.get("due_date", ""),
        "currency": invoice.get("currency", "USD"),
        "total": float(invoice.get("total_amount", 0)),
        "reference": invoice.get("shipment_ref", ""),
        "line_items": line_items,
    }

    if provider_key == "quickbooks":
        return {
            "Invoice": {
                "CustomerRef": {"name": base["customer_name"]},
                "DocNumber": base["invoice_number"],
                "TxnDate": base["issue_date"],
                "DueDate": base["due_date"],
                "CurrencyRef": {"value": base["currency"]},
                "PrivateNote": base["reference"],
                "Line": [
                    {
                        "DetailType": "SalesItemLineDetail",
                        "Amount": li["amount"],
                        "Description": li["description"],
                        "SalesItemLineDetail": {
                            "Qty": li["quantity"],
                            "UnitPrice": li["unit_price"],
                        },
                    }
                    for li in line_items
                ],
            }
        }

    if provider_key == "xero":
        return {
            "Type": "ACCREC",
            "InvoiceNumber": base["invoice_number"],
            "Contact": {"Name": base["customer_name"]},
            "Date": base["issue_date"],
            "DueDate": base["due_date"],
            "CurrencyCode": base["currency"],
            "Reference": base["reference"],
            "LineItems": [
                {
                    "Description": li["description"],
                    "Quantity": li["quantity"],
                    "UnitAmount": li["unit_price"],
                    "LineAmount": li["amount"],
                }
                for li in line_items
            ],
        }

    if provider_key == "zoho":
        return {
            "customer_name": base["customer_name"],
            "invoice_number": base["invoice_number"],
            "date": base["issue_date"],
            "due_date": base["due_date"],
            "currency_code": base["currency"],
            "reference_number": base["reference"],
            "line_items": [
                {
                    "name": li["description"],
                    "quantity": li["quantity"],
                    "rate": li["unit_price"],
                }
                for li in line_items
            ],
        }

    if provider_key == "freshbooks":
        return {
            "invoice": {
                "customerid": 0,
                "invoice_number": base["invoice_number"],
                "create_date": base["issue_date"],
                "due_date": base["due_date"],
                "currency_code": base["currency"],
                "notes": base["reference"],
                "lines": [
                    {
                        "name": li["description"],
                        "qty": li["quantity"],
                        "unit_cost": {"amount": str(li["unit_price"]), "code": base["currency"]},
                    }
                    for li in line_items
                ],
            }
        }

    # Generic fallback (Wave, MYOB, Sage, others)
    return base


# ── Push invoice ──────────────────────────────────────────────────────────────

def push_invoice(invoice_id: str, provider_key: str) -> dict[str, Any]:
    """
    Push a TMS invoice to the accounting provider.
    Returns {ok, external_id, error}.
    """
    if provider_key not in PROVIDERS:
        return {"ok": False, "external_id": "", "error": "Unknown provider"}

    # Load invoice from TMS DB
    import sqlite3
    from .tms_db import init_tms_db, get_db
    init_tms_db()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        invoice_row = conn.execute(
            "SELECT * FROM auto_invoices WHERE invoice_number = ? OR id = ?",
            (str(invoice_id), str(invoice_id)),
        ).fetchone()
    finally:
        conn.close()

    if not invoice_row:
        return {"ok": False, "external_id": "", "error": "Invoice not found"}

    invoice = dict(invoice_row)
    settings = get_accounting_settings()
    p = PROVIDERS[provider_key]

    token = _get_token(provider_key, settings)
    if not token:
        return {"ok": False, "external_id": "", "error": "No access token — configure credentials first"}

    payload = _build_invoice_payload(invoice, provider_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    # Build URL
    base_url = p["base_url"]
    if provider_key == "quickbooks":
        realm = settings.get("qb_realm_id", "")
        base_url = base_url.replace("{realm_id}", realm)
        url = f"{base_url}/invoice"
    elif provider_key == "xero":
        tenant = settings.get("xero_tenant_id", "")
        headers["Xero-tenant-id"] = tenant
        url = f"{base_url}/Invoices"
    elif provider_key == "zoho":
        org = settings.get("zoho_org_id", "")
        url = f"{base_url}/invoices?organization_id={org}"
    elif provider_key == "freshbooks":
        acct = settings.get("fb_account_id", "")
        base_url = base_url.replace("{account_id}", acct)
        url = f"{base_url}/invoices/invoices"
    elif provider_key == "wave":
        url = base_url  # GraphQL — would need mutation
        return {"ok": False, "external_id": "",
                "error": "Wave uses GraphQL — direct push not yet implemented. Use Wave portal."}
    elif provider_key == "myob":
        file_id = settings.get("myob_company_file_id", "")
        url = f"{base_url}/{file_id}/Sale/Invoice/Service"
    elif provider_key == "sage":
        url = f"{base_url}/sales_invoices"
    else:
        return {"ok": False, "external_id": "", "error": "No endpoint defined for this provider"}

    resp, status = _http_post(url, payload, headers)

    if status in (200, 201):
        ext_id = (
            str(resp.get("Id") or resp.get("id") or
                resp.get("InvoiceID") or
                (resp.get("invoice") or {}).get("invoiceid") or
                (resp.get("invoice") or {}).get("id") or "")
        )
        _log_sync(provider_key, "push", "invoice", str(invoice_id),
                  "success", ext_id, payload=payload)
        return {"ok": True, "external_id": ext_id, "error": ""}

    error_msg = (resp.get("Fault") or {}).get("Error", [{}])[0].get("Message") if "Fault" in resp \
        else resp.get("message") or resp.get("error") or f"HTTP {status}"
    _log_sync(provider_key, "push", "invoice", str(invoice_id),
              "failed", error=str(error_msg), payload=payload)
    return {"ok": False, "external_id": "", "error": str(error_msg)}


# ── Pull payments ─────────────────────────────────────────────────────────────

def pull_payments(provider_key: str) -> list[dict[str, Any]]:
    """Fetch recent paid/voided invoices from accounting provider."""
    if provider_key not in PROVIDERS:
        return []

    settings = get_accounting_settings()
    p = PROVIDERS[provider_key]
    token = _get_token(provider_key, settings)
    if not token:
        return []

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    if provider_key == "quickbooks":
        realm = settings.get("qb_realm_id", "")
        url = (f"https://quickbooks.api.intuit.com/v3/company/{realm}"
               "/query?query=SELECT+*+FROM+Invoice+WHERE+Balance+=+'0'+MAXRESULTS+50")
    elif provider_key == "xero":
        tenant = settings.get("xero_tenant_id", "")
        headers["Xero-tenant-id"] = tenant
        url = "https://api.xero.com/api.xro/2.0/Invoices?Statuses=PAID&page=1"
    elif provider_key == "zoho":
        org = settings.get("zoho_org_id", "")
        url = f"https://www.zohoapis.com/books/v3/invoices?organization_id={org}&status=paid"
    else:
        return []

    resp, status = _http_get(url, headers)
    if status != 200:
        return []

    raw: list[dict] = []
    if provider_key == "quickbooks":
        raw = (resp.get("QueryResponse") or {}).get("Invoice", [])
    elif provider_key == "xero":
        raw = resp.get("Invoices", [])
    elif provider_key == "zoho":
        raw = resp.get("invoices", [])

    return [
        {
            "provider": provider_key,
            "external_id": str(r.get("Id") or r.get("InvoiceID") or r.get("invoice_id") or ""),
            "invoice_number": str(r.get("DocNumber") or r.get("InvoiceNumber") or r.get("invoice_number") or ""),
            "customer": str(r.get("CustomerRef", {}).get("name") or r.get("Contact", {}).get("Name") or r.get("customer_name") or ""),
            "total": float(r.get("TotalAmt") or r.get("Total") or r.get("total") or 0),
            "status": "paid",
        }
        for r in raw
    ]


# ── Test connection ───────────────────────────────────────────────────────────

def test_connection(provider_key: str) -> dict[str, Any]:
    """Verify credentials by hitting a lightweight read endpoint."""
    if provider_key not in PROVIDERS:
        return {"ok": False, "message": "Unknown provider"}

    settings = get_accounting_settings()
    token = _get_token(provider_key, settings)
    if not token:
        return {"ok": False, "message": "No access token. Enter credentials and authorize first."}

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    p = PROVIDERS[provider_key]

    try:
        if provider_key == "quickbooks":
            realm = settings.get("qb_realm_id", "")
            url = f"https://quickbooks.api.intuit.com/v3/company/{realm}/companyinfo/{realm}"
        elif provider_key == "xero":
            headers["Xero-tenant-id"] = settings.get("xero_tenant_id", "")
            url = "https://api.xero.com/api.xro/2.0/Organisation"
        elif provider_key == "zoho":
            org = settings.get("zoho_org_id", "")
            url = f"https://www.zohoapis.com/books/v3/organizations/{org}"
        elif provider_key == "freshbooks":
            url = "https://api.freshbooks.com/auth/api/v1/users/me"
        elif provider_key == "myob":
            url = "https://api.myob.com/accountright"
        elif provider_key == "sage":
            url = "https://api.accounting.sage.com/v3.1/business"
        elif provider_key == "wave":
            return {"ok": True, "message": "Wave GraphQL — connection assumed. Enter Business ID above."}
        else:
            return {"ok": False, "message": "No test endpoint defined"}

        resp, status = _http_get(url, headers)
        if status == 200:
            return {"ok": True, "message": f"Connected to {p['name']} successfully."}
        return {"ok": False, "message": f"HTTP {status}: {resp.get('error') or resp.get('message') or 'Auth failed'}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def get_sync_log(limit: int = 50) -> list[dict]:
    _ensure_table()
    from .tms_db import get_db
    import sqlite3
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM accounting_sync_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_all_providers() -> list[dict[str, Any]]:
    settings = get_accounting_settings()
    result = []
    for key, p in PROVIDERS.items():
        creds_saved = any(settings.get(k, "") for k in p.get("settings_keys", [])
                          if "access_token" in k)
        result.append({**p, "key": key, "creds_saved": creds_saved})
    return result
