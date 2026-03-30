"""
TMS Integration Hub — Smart Connect
OAuth where available. Guided key wizard everywhere else.
TMS Master = internal marketplace (no external key needed).
"""

# ── Encryption helpers ────────────────────────────────────────────────────────
import base64
import hashlib
import json
import os
from cryptography.fernet import Fernet


_WEAK_INTEGRATION_KEYS = {
    "",
    "change-me",
    "change-me-for-local-dev",
    "flash-tms-default-key-change-in-prod",
    "replace-with-a-long-random-secret",
    "tms-master-dev-change-me",
}


def _integration_secret():
    return os.environ.get("INTEGRATION_MASTER_KEY") or os.environ.get("SECRET_KEY") or ""


def _integration_production_mode():
    return (os.environ.get("TMS_ENV") or os.environ.get("FLASK_ENV") or "").strip().lower() == "production"


def _get_fernet():
    raw = _integration_secret()
    if _integration_production_mode():
        if raw in _WEAK_INTEGRATION_KEYS or len(raw) < 32:
            raise RuntimeError(
                "Production requires a strong INTEGRATION_MASTER_KEY or SECRET_KEY for encrypted settings."
            )
    elif not raw:
        raw = "flash-tms-default-key-change-in-prod"
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)

def encrypt_key(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()

def decrypt_key(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


# ── Integration catalogue ─────────────────────────────────────────────────────
# connection_type:
#   "internal"     → TMS Master, no key needed
#   "oauth"        → one-click OAuth redirect
#   "api_key"      → guided API-key form
#   "coming_soon"  → tile shown, connect disabled
#   "request"      → partner-gated, shows "Request Access"

PROVIDERS = {

    # ══════════════════════════════════════════════════════════════════════════
    # TMS MASTER — Internal (featured hero)
    # ══════════════════════════════════════════════════════════════════════════
    "flash_network": {
        "name": "TMS Master",
        "category": "Internal Network",
        "region": "Global",
        "color": "#c8a96e",
        "description": "Your built-in freight community. Post loads, offer capacity, and transact directly with other TMS users — no external load board needed.",
        "website": "/tms/network",
        "connection_type": "internal",
        "capabilities": ["Internal load board", "Capacity marketplace", "Direct messaging", "User ratings", "Shipment matching"],
        "badge": "INCLUDED",
        "featured": True,
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PARCEL & LAST-MILE
    # ══════════════════════════════════════════════════════════════════════════
    "fedex": {
        "name": "FedEx",
        "category": "Parcel",
        "region": "Global",
        "color": "#4d148c",
        "description": "Rate quotes, label generation, real-time tracking, and pickup scheduling for FedEx Express and Ground.",
        "website": "https://developer.fedex.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "secret_key", "label": "Secret Key", "type": "password"},
                   {"key": "account_number", "label": "Account Number", "type": "text"}],
        "key_guide": "FedEx Developer Portal → My Projects → Create Project → copy API Key + Secret Key",
        "docs": "https://developer.fedex.com/api/en-us/home.html",
        "capabilities": ["Label generation", "Rate quotes", "Real-time tracking", "Pickup scheduling", "International"],
    },
    "ups": {
        "name": "UPS",
        "category": "Parcel",
        "region": "Global",
        "color": "#FFB500",
        "description": "UPS shipping APIs for rates, labels, tracking, and address validation across 220 countries.",
        "website": "https://developer.ups.com",
        "connection_type": "api_key",
        "fields": [{"key": "client_id", "label": "Client ID", "type": "text"},
                   {"key": "client_secret", "label": "Client Secret", "type": "password"},
                   {"key": "account_number", "label": "Account Number", "type": "text"}],
        "key_guide": "UPS Developer Portal → My Apps → Add App → copy Client ID and Client Secret",
        "docs": "https://developer.ups.com",
        "capabilities": ["Label generation", "Rate quotes", "Tracking", "Address validation", "Freight"],
    },
    "dhl": {
        "name": "DHL Express",
        "category": "Parcel",
        "region": "Global",
        "color": "#FFCC00",
        "description": "DHL Express APIs for international shipping, rates, tracking, and shipment creation in 220+ countries.",
        "website": "https://developer.dhl.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "account_number", "label": "DHL Account Number", "type": "text"}],
        "key_guide": "DHL Developer Portal → My Apps → Create App → copy API Key",
        "docs": "https://developer.dhl.com",
        "capabilities": ["International shipping", "Rate quotes", "Tracking", "Customs docs", "Pick-up booking"],
    },
    "aftership": {
        "name": "AfterShip",
        "category": "Parcel",
        "region": "Global",
        "color": "#f7b731",
        "description": "Track shipments across 1,200+ carriers worldwide with one API. The fastest way to add multi-carrier tracking.",
        "website": "https://www.aftership.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "AfterShip Dashboard → Settings → API Keys → Create API Key",
        "docs": "https://www.aftership.com/docs/api/4",
        "capabilities": ["1,200+ carriers", "Real-time tracking", "Webhooks", "Branded tracking page", "Analytics"],
    },
    "easypost": {
        "name": "EasyPost",
        "category": "Parcel",
        "region": "Global",
        "color": "#46b6e7",
        "description": "Unified shipping API for 100+ carriers. Rate shopping, label generation, and tracking in one integration.",
        "website": "https://www.easypost.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "EasyPost Dashboard → API Keys → copy Test or Production key",
        "docs": "https://www.easypost.com/docs/api",
        "capabilities": ["100+ carriers", "Rate shopping", "Label printing", "Tracking", "Address verification"],
    },
    "australia_post": {
        "name": "Australia Post",
        "category": "Parcel",
        "region": "Asia-Pacific",
        "color": "#D40000",
        "description": "Australia Post APIs for domestic and international parcel shipping, tracking, and returns management.",
        "website": "https://developers.auspost.com.au",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "account_number", "label": "Account Number", "type": "text"},
                   {"key": "password", "label": "API Password", "type": "password"}],
        "key_guide": "MyPost Business → Developer Centre → Register for API access → copy key",
        "docs": "https://developers.auspost.com.au",
        "capabilities": ["Domestic parcels", "International", "Express", "Tracking", "Returns"],
    },
    "japan_post": {
        "name": "Japan Post",
        "category": "Parcel",
        "region": "Asia-Pacific",
        "color": "#cc0000",
        "description": "Japan Post Yuubin tracking and shipping APIs for domestic Japan and international routes.",
        "website": "https://www.post.japanpost.jp",
        "connection_type": "coming_soon",
        "capabilities": ["Domestic Japan", "International", "EMS", "Tracking"],
    },
    "singpost": {
        "name": "Singapore Post",
        "category": "Parcel",
        "region": "Asia-Pacific",
        "color": "#e63946",
        "description": "SingPost APIs for Singapore domestic delivery and intra-Asia last-mile logistics.",
        "website": "https://www.singpost.com",
        "connection_type": "coming_soon",
        "capabilities": ["Singapore domestic", "Intra-Asia", "eCommerce", "Tracking"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # TELEMATICS & ELD
    # ══════════════════════════════════════════════════════════════════════════
    "motive": {
        "name": "Motive (KeepTruckin)",
        "category": "Telematics & ELD",
        "region": "North America",
        "color": "#2563eb",
        "description": "Connected fleet platform. ELD compliance, GPS tracking, safety, fuel management, and driver management.",
        "website": "https://gomotive.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Motive Fleet Dashboard → Settings → Integrations → API Keys → Generate Key",
        "docs": "https://developer.gomotive.com",
        "capabilities": ["ELD compliance", "GPS tracking", "HOS logs", "Safety events", "IFTA reporting"],
    },
    "samsara": {
        "name": "Samsara",
        "category": "Telematics & ELD",
        "region": "Global",
        "color": "#00a862",
        "description": "Fleet management platform with real-time GPS, ELD, safety cameras, and open API for TMS integration.",
        "website": "https://www.samsara.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_token", "label": "API Token", "type": "password"}],
        "key_guide": "Samsara Cloud → Settings → API Tokens → Create Token",
        "docs": "https://developers.samsara.com",
        "capabilities": ["Real-time GPS", "ELD", "Dashcam", "Route optimization", "Fuel monitoring"],
    },
    "geotab": {
        "name": "Geotab",
        "category": "Telematics & ELD",
        "region": "Global",
        "color": "#e63946",
        "description": "World's largest telematics platform. OpenAPI for TMS integration — 50,000+ fleet customers globally.",
        "website": "https://www.geotab.com",
        "connection_type": "api_key",
        "fields": [{"key": "username", "label": "Username", "type": "text"},
                   {"key": "password", "label": "Password", "type": "password"},
                   {"key": "database", "label": "Database Name", "type": "text"}],
        "key_guide": "MyGeotab → Administration → Users → your username and database name shown in URL",
        "docs": "https://geotab.github.io/sdk",
        "capabilities": ["GPS tracking", "Driver behavior", "Maintenance", "Fuel", "Open SDK"],
    },
    "teletrac_navman": {
        "name": "Teletrac Navman",
        "category": "Telematics & ELD",
        "region": "Asia-Pacific",
        "color": "#0057a8",
        "description": "#1 fleet management platform in Australia & New Zealand. TN360 open API for GPS, compliance, and job dispatch.",
        "website": "https://www.teletracnavman.com.au",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "account_id", "label": "Account ID", "type": "text"}],
        "key_guide": "TN360 Platform → Admin → API Management → Generate Key",
        "docs": "https://developers.teletracnavman.com",
        "capabilities": ["GPS tracking", "NHVR compliance", "Job dispatch", "ANZ regulation", "Maintenance"],
    },
    "mix_telematics": {
        "name": "MiX Telematics",
        "category": "Telematics & ELD",
        "region": "Global",
        "color": "#ff6b00",
        "description": "Global telematics with strong Africa, Middle East, and ANZ coverage. Fleet tracking and driver safety.",
        "website": "https://www.mixtelematics.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "organization_id", "label": "Organization ID", "type": "text"}],
        "key_guide": "MiX Fleet Manager → Settings → API Access → Request API Key",
        "docs": "https://developer.mixtelematics.com",
        "capabilities": ["GPS tracking", "Driver scoring", "Fuel analytics", "Africa coverage", "Alerts"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # RAIL FREIGHT
    # ══════════════════════════════════════════════════════════════════════════
    "terminal49": {
        "name": "Terminal49",
        "category": "Rail & Intermodal",
        "region": "North America",
        "color": "#6366f1",
        "description": "Unified API for BNSF, Union Pacific, CN, CP, CSX, and Norfolk Southern. Container tracking across all Class I railroads.",
        "website": "https://terminal49.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Terminal49 Dashboard → Settings → API Keys → Generate New Key",
        "docs": "https://www.terminal49.com/docs",
        "capabilities": ["BNSF", "Union Pacific", "CN Rail", "CP Rail", "CSX", "Norfolk Southern", "Container tracking"],
    },
    "bnsf": {
        "name": "BNSF Railway",
        "category": "Rail & Intermodal",
        "region": "North America",
        "color": "#f97316",
        "description": "Direct BNSF API for intermodal shipping, rate quotes, shipment booking, and container tracking.",
        "website": "https://www.bnsf.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "customer_id", "label": "Customer ID", "type": "text"}],
        "key_guide": "BNSF Customer Portal → API Center → Register for API access",
        "docs": "https://www.bnsf.com/ship-with-bnsf/support-services/customer-api",
        "capabilities": ["Intermodal booking", "Rate quotes", "Container tracking", "BOL", "Schedules"],
    },
    "db_cargo": {
        "name": "DB Cargo (Deutsche Bahn — Europe)",
        "category": "rail_intermodal", "region": "Europe",
        "auth_type": "oauth2_client",
        "settings_keys": ["db_cargo_client_id", "db_cargo_client_secret"],
        "description": "Europe's largest rail freight operator. API for booking, tracking, rate quotes across 18 EU countries.",
        "capabilities": ["Rail booking", "Rate quotes", "Container tracking", "Intermodal", "Cross-border EU"],
        "website": "https://www.dbcargo.com", "docs": "https://developer.deutschebahn.com"
    },
    "network_rail_uk": {
        "name": "Network Rail / GB Railfreight (UK)",
        "category": "rail_intermodal", "region": "United Kingdom",
        "auth_type": "api_key",
        "settings_keys": ["gbrail_api_key"],
        "description": "UK rail freight booking and tracking via GB Railfreight API. Major ports to inland terminals.",
        "capabilities": ["Booking", "Terminal availability", "Tracking", "Port shuttle"],
        "website": "https://www.gbrailfreight.com", "docs": "https://developer.gbrailfreight.com"
    },
    "aurizon": {
        "name": "Aurizon (Australia Rail Freight)",
        "category": "rail_intermodal", "region": "Australia",
        "auth_type": "api_key",
        "settings_keys": ["aurizon_api_key"],
        "description": "Australia's largest rail freight operator. East-West and North-South corridors, bulk and intermodal.",
        "capabilities": ["Intermodal booking", "Bulk freight", "Tracking", "Port connections"],
        "website": "https://www.aurizon.com.au", "docs": "https://developer.aurizon.com.au"
    },
    "indian_railways_freight": {
        "name": "Indian Railways FOIS (Freight Operations)",
        "category": "rail_intermodal", "region": "India",
        "auth_type": "api_key",
        "settings_keys": ["fois_api_key", "fois_username"],
        "description": "Indian Railways Freight Operations Information System. Wagon tracking, rake status, freight billing.",
        "capabilities": ["Wagon tracking", "Rake status", "Freight billing", "Station data"],
        "website": "https://fois.indianrail.gov.in", "docs": "https://api.indianrail.gov.in/freight"
    },
    "transnet_freightreail": {
        "name": "Transnet Freight Rail (South Africa)",
        "category": "rail_intermodal", "region": "Africa",
        "auth_type": "api_key",
        "settings_keys": ["transnet_api_key"],
        "description": "South Africa's national freight rail operator. General freight, bulk commodities, container rail.",
        "capabilities": ["Container rail", "Bulk freight", "Tracking", "Port connections"],
        "website": "https://www.transnet.net", "docs": "https://developer.transnet.net"
    },
    "cn_rail": {
        "name": "CN Rail (Canada / North America)",
        "category": "rail_intermodal", "region": "Canada / North America",
        "auth_type": "api_key",
        "settings_keys": ["cn_api_key", "cn_customer_id"],
        "description": "Canadian National Railway API. Intermodal bookings, car tracking, rate quotes, Canada-US-Mexico.",
        "capabilities": ["Intermodal booking", "Car tracking", "Rate quotes", "Cross-border"],
        "website": "https://www.cn.ca", "docs": "https://developer.cn.ca"
    },
    "j_freight": {
        "name": "JR Freight (Japan)",
        "category": "rail_intermodal", "region": "Japan",
        "auth_type": "api_key",
        "settings_keys": ["jrfreight_api_key"],
        "description": "Japan Freight Railway Company. Container freight across Japan's rail network.",
        "capabilities": ["Container booking", "Tracking", "Terminal info", "Rate inquiry"],
        "website": "https://www.jrfreight.co.jp", "docs": "https://api.jrfreight.co.jp"
    },

    # ══════════════════════════════════════════════════════════════════════════
    # CUSTOMS & TRADE COMPLIANCE
    # ══════════════════════════════════════════════════════════════════════════
    "cbp_ace": {
        "name": "US CBP — ACE/AES",
        "category": "Customs & Compliance",
        "region": "North America",
        "color": "#1d3557",
        "description": "US Customs and Border Protection. ACE for imports, AES for exports. Mandatory electronic filing for all US cross-border trade.",
        "website": "https://www.cbp.gov/trade/ace",
        "connection_type": "api_key",
        "fields": [{"key": "filer_code", "label": "Filer Code", "type": "text"},
                   {"key": "ein", "label": "EIN / Tax ID", "type": "text"},
                   {"key": "submitter_id", "label": "AES Submitter ID", "type": "text"}],
        "key_guide": "Register at ACE Secure Data Portal (ace.cbp.dhs.gov) as an Importer/Exporter. Filer Code assigned by CBP.",
        "docs": "https://www.cbp.gov/trade/ace/ABI",
        "capabilities": ["Import filings", "Export (AES)", "Entry summary", "ISF 10+2", "Duty drawback"],
    },
    "uk_cds": {
        "name": "UK CDS (Customs Declaration Service)",
        "category": "Customs & Compliance",
        "region": "Europe",
        "color": "#012169",
        "description": "HMRC's Customs Declaration Service — mandatory for all UK imports and exports post-Brexit.",
        "website": "https://www.gov.uk/guidance/how-hmrc-will-introduce-the-customs-declaration-service",
        "connection_type": "api_key",
        "fields": [{"key": "client_id", "label": "HMRC Client ID", "type": "text"},
                   {"key": "client_secret", "label": "HMRC Client Secret", "type": "password"},
                   {"key": "eori", "label": "EORI Number", "type": "text"}],
        "key_guide": "Register on HMRC Developer Hub → Create application → get Client ID + Secret. EORI from HMRC registration.",
        "docs": "https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/customs-declarations",
        "capabilities": ["Import declarations", "Export declarations", "EORI validation", "Duty calculation"],
    },
    "eu_ics2": {
        "name": "EU ICS2",
        "category": "Customs & Compliance",
        "region": "Europe",
        "color": "#003399",
        "description": "EU Import Control System 2. Mandatory ENS (Entry Summary Declaration) for all goods entering the EU — filed 24hrs pre-arrival.",
        "website": "https://taxation-customs.ec.europa.eu/ics2-programme_en",
        "connection_type": "coming_soon",
        "capabilities": ["ENS filing", "Risk assessment", "Pre-arrival notification", "EU-wide compliance"],
    },
    "atlas_germany": {
        "name": "ATLAS (Germany)",
        "category": "Customs & Compliance",
        "region": "Europe",
        "color": "#000000",
        "description": "German Federal Customs Authority electronic system. Required for all German import/export declarations.",
        "website": "https://www.zoll.de/EN/Businesses/Electronic-customs-processing/ATLAS/atlas_node.html",
        "connection_type": "coming_soon",
        "capabilities": ["German customs", "EORI", "Import/export declarations", "Transit (NCTS)"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # PORT COMMUNITY SYSTEMS
    # ══════════════════════════════════════════════════════════════════════════
    "portbase": {
        "name": "PortBase (Rotterdam)",
        "category": "Port Systems",
        "region": "Europe",
        "color": "#005293",
        "description": "Rotterdam's port community system. Pre-notification, customs, vessel calls, container release for Europe's largest port.",
        "website": "https://www.portbase.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "company_id", "label": "PortBase Company ID", "type": "text"}],
        "key_guide": "PortBase portal → My Account → API Access → Request key from PortBase support",
        "docs": "https://portbase.com/en/services",
        "capabilities": ["Pre-notification", "Container release", "Customs", "Vessel ETA", "Barge planning"],
    },
    "one_stop_australia": {
        "name": "1-Stop (Australia)",
        "category": "Port Systems",
        "region": "Asia-Pacific",
        "color": "#00843D",
        "description": "Australia's port community system for Sydney, Melbourne, Brisbane, Fremantle. Container availability and vessel schedules.",
        "website": "https://www.1-stop.biz",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "client_code", "label": "Client Code", "type": "text"}],
        "key_guide": "1-Stop portal → My Account → API Credentials → Request access",
        "docs": "https://www.1-stop.biz/solutions/api-integration",
        "capabilities": ["Container availability", "Vessel ETA", "Receival cut-offs", "Wharf slots", "All AU ports"],
    },
    "portconnect_nz": {
        "name": "PortConnect (NZ)",
        "category": "Port Systems",
        "region": "Asia-Pacific",
        "color": "#000000",
        "description": "New Zealand's port community system. Port of Auckland, Lyttelton, Tauranga connectivity.",
        "website": "https://www.portconnect.co.nz",
        "connection_type": "coming_soon",
        "capabilities": ["NZ ports", "Container tracking", "Vessel schedules", "Customs"],
    },
    "dakosy": {
        "name": "DAKOSY (Hamburg)",
        "category": "Port Systems",
        "region": "Europe",
        "color": "#1a1a2e",
        "description": "Hamburg port community system. Pre-gate notification, customs, container tracking for Germany's largest port.",
        "website": "https://www.dakosy.de",
        "connection_type": "coming_soon",
        "capabilities": ["Hamburg port", "Pre-gate notification", "ZAPP customs", "Vessel ETA"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ASIA-PACIFIC MARKETPLACES
    # ══════════════════════════════════════════════════════════════════════════
    "lalamove": {
        "name": "Lalamove",
        "category": "Asia-Pacific Freight",
        "region": "Asia-Pacific",
        "color": "#f6a000",
        "description": "On-demand delivery platform across Southeast Asia and Hong Kong. Same-day city logistics via API.",
        "website": "https://www.lalamove.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "api_secret", "label": "API Secret", "type": "password"}],
        "key_guide": "Lalamove Business Portal → API Integration → Generate API Key",
        "docs": "https://developers.lalamove.com",
        "capabilities": ["On-demand delivery", "Singapore", "Malaysia", "Philippines", "Thailand", "Hong Kong"],
    },
    "ninja_van": {
        "name": "Ninja Van",
        "category": "Asia-Pacific Freight",
        "region": "Asia-Pacific",
        "color": "#e63946",
        "description": "Southeast Asia's leading parcel delivery network across Singapore, Malaysia, Indonesia, Philippines, Thailand, Vietnam.",
        "website": "https://www.ninjavan.co",
        "connection_type": "api_key",
        "fields": [{"key": "client_id", "label": "Client ID", "type": "text"},
                   {"key": "client_secret", "label": "Client Secret", "type": "password"},
                   {"key": "country_code", "label": "Country Code (SG/MY/ID/PH/TH/VN)", "type": "text"}],
        "key_guide": "Ninja Van Shipper Portal → Settings → API → Generate Credentials",
        "docs": "https://api-docs.ninjavan.co",
        "capabilities": ["SEA delivery", "Same-day", "Next-day", "Returns", "COD", "6 countries"],
    },
    "jt_express": {
        "name": "J&T Express",
        "category": "Asia-Pacific Freight",
        "region": "Asia-Pacific",
        "color": "#e63946",
        "description": "Southeast Asia's largest express delivery network with strong Indonesia presence and pan-ASEAN expansion.",
        "website": "https://www.jtexpress.my",
        "connection_type": "api_key",
        "fields": [{"key": "customer_code", "label": "Customer Code", "type": "text"},
                   {"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "J&T Business Portal → API Center → Register → copy Customer Code and API Key",
        "docs": "https://open.jtexpress.my",
        "capabilities": ["Indonesia", "Malaysia", "Philippines", "Thailand", "Vietnam", "Singapore"],
    },
    "cainiao": {
        "name": "Alibaba Cainiao",
        "category": "Asia-Pacific Freight",
        "region": "Asia-Pacific",
        "color": "#ff6a00",
        "description": "Alibaba's logistics platform. 5M+ cross-border packages/day. Partner API for certified 3PLs and freight forwarders.",
        "website": "https://www.cainiao.com",
        "connection_type": "request",
        "capabilities": ["Cross-border China", "5M+ packages/day", "Last-mile 220 countries", "Bonded warehouses"],
    },
    "jd_logistics": {
        "name": "JD Logistics",
        "category": "Asia-Pacific Freight",
        "region": "Asia-Pacific",
        "color": "#e31837",
        "description": "JD.com's logistics arm. China domestic + international freight with warehousing and last-mile delivery.",
        "website": "https://www.jdl.com",
        "connection_type": "request",
        "capabilities": ["China domestic", "Cross-border", "Cold chain", "Bonded warehouses", "B2B freight"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # EUROPE FREIGHT MARKETPLACES
    # ══════════════════════════════════════════════════════════════════════════
    "sennder": {
        "name": "Sennder",
        "category": "European Freight",
        "region": "Europe",
        "color": "#5c6bc0",
        "description": "Europe's leading digital freight platform across Germany, Netherlands, France, Spain, Italy, and UK.",
        "website": "https://www.sennder.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "company_id", "label": "Company ID", "type": "text"}],
        "key_guide": "Sennder Shipper Portal → Settings → API Integration → Generate Key",
        "docs": "https://api.sennder.com/docs",
        "capabilities": ["FTL Europe", "LTL", "Real-time tracking", "Rate quotes", "Carrier network"],
    },
    "timocom": {
        "name": "TIMOCOM",
        "category": "European Freight",
        "region": "Europe",
        "color": "#e63946",
        "description": "Europe's largest freight marketplace. 43,000+ companies trading capacity across Germany and Central Europe.",
        "website": "https://www.timocom.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "company_id", "label": "TIMOCOM Company ID", "type": "text"}],
        "key_guide": "TIMOCOM Smart Logistics System → Settings → API → API Key Management",
        "docs": "https://www.postman.com/timocom",
        "capabilities": ["Load board", "Capacity board", "Rate benchmarks", "Carrier search", "Central Europe"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # NORTH AMERICA DIGITAL BROKERS
    # ══════════════════════════════════════════════════════════════════════════
    "convoy": {
        "name": "Convoy",
        "category": "Digital Freight",
        "region": "North America",
        "color": "#00b4d8",
        "description": "Digital freight network. Instant FTL quotes, automated load matching, real-time tracking across 48 states.",
        "website": "https://convoy.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "shipper_id", "label": "Shipper ID", "type": "text"}],
        "key_guide": "Convoy Shipper Portal → Integrations → API Access → Generate Key",
        "docs": "https://convoy.com/api",
        "capabilities": ["Instant FTL quotes", "Load matching", "Real-time tracking", "Automated dispatch"],
    },
    "coyote": {
        "name": "Coyote Logistics",
        "category": "Digital Freight",
        "region": "North America",
        "color": "#ff6b35",
        "description": "3PL with 75,000+ carrier relationships. Spot and contract freight with API-driven load tendering.",
        "website": "https://www.coyote.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "account_id", "label": "Account ID", "type": "text"}],
        "key_guide": "Coyote Portal → My Account → API Settings → Generate API Key",
        "docs": "https://developer.coyote.com",
        "capabilities": ["Spot freight", "Contract freight", "Carrier vetting", "Load tracking", "LTL"],
    },
    "loadsmart": {
        "name": "Loadsmart",
        "category": "Digital Freight",
        "region": "North America",
        "color": "#0097a7",
        "description": "AI-powered freight management with instant pricing, automated execution, and real-time visibility.",
        "website": "https://loadsmart.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Loadsmart Shipper Portal → Settings → API → Generate Key",
        "docs": "https://api.loadsmart.com/docs",
        "capabilities": ["Instant pricing", "FTL/LTL", "Real-time tracking", "AI optimization"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # VESSEL TRACKING
    # ══════════════════════════════════════════════════════════════════════════
    "marinetraffic": {
        "name": "MarineTraffic",
        "category": "Vessel Tracking",
        "region": "Global",
        "color": "#1565c0",
        "description": "Real-time AIS vessel tracking for 400,000+ vessels. Port calls, ETA predictions, and vessel details.",
        "website": "https://www.marinetraffic.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "MarineTraffic Account → My API → Generate API Key",
        "docs": "https://www.marinetraffic.com/en/ais-api-services",
        "capabilities": ["Live vessel positions", "Port calls", "ETA prediction", "Vessel history", "Fleet monitoring"],
    },
    "vesselfinder": {
        "name": "VesselFinder",
        "category": "Vessel Tracking",
        "region": "Global",
        "color": "#0288d1",
        "description": "AIS vessel tracking API. Real-time positions, vessel details, port arrivals, and departure data.",
        "website": "https://www.vesselfinder.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "VesselFinder Account → API → Register for API access → copy key",
        "docs": "https://api.vesselfinder.com",
        "capabilities": ["AIS tracking", "Vessel details", "Port arrivals", "Fleet lists", "Historical"],
    },
    "everstream": {
        "name": "Everstream Analytics",
        "category": "Vessel Tracking",
        "region": "Global",
        "color": "#7c3aed",
        "description": "Supply chain risk and disruption intelligence. Port congestion, weather delays, and predictive ETAs.",
        "website": "https://www.everstream.ai",
        "connection_type": "request",
        "capabilities": ["Port congestion", "Risk alerts", "Weather disruption", "Predictive ETA", "Lane analytics"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # CARGO INSURANCE
    # ══════════════════════════════════════════════════════════════════════════
    "loadsure": {
        "name": "Loadsure",
        "category": "Insurance",
        "region": "Global",
        "color": "#06b6d4",
        "description": "Per-shipment cargo insurance. Quote, bind, and certificate in seconds via API. Built to be embedded in TMS.",
        "website": "https://www.loadsure.net",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "broker_id", "label": "Broker ID", "type": "text"}],
        "key_guide": "Loadsure Partner Portal → API Access → Generate Key + copy Broker ID",
        "docs": "https://docs.loadsure.net",
        "capabilities": ["Per-load insurance", "Instant certificate", "Claims portal", "Commodity coverage"],
    },
    "falvey_freight": {
        "name": "Falvey Freight Insurance",
        "category": "freight_insurance", "region": "North America",
        "auth_type": "api_key",
        "settings_keys": ["falvey_api_key", "falvey_agent_id"],
        "description": "Instant freight insurance certificates. Per-shipment coverage, all modes, same-day binding.",
        "capabilities": ["Per-load coverage", "Instant cert", "All modes", "Claims portal", "API quoting"],
        "website": "https://www.falveyinsurance.com", "docs": "https://api.falveyinsurance.com"
    },
    "marsh_cargo": {
        "name": "Marsh Cargo (Global)",
        "category": "freight_insurance", "region": "Global",
        "auth_type": "oauth2_client",
        "settings_keys": ["marsh_client_id", "marsh_client_secret"],
        "description": "Global cargo insurance from Marsh, world's largest insurance broker. Ocean, air, land, project cargo.",
        "capabilities": ["Ocean cargo", "Air freight", "Land transit", "Project cargo", "Claims management"],
        "website": "https://www.marsh.com/cargo", "docs": "https://developer.marsh.com/cargo"
    },
    "throughput_insurance": {
        "name": "Throughput (Digital Cargo Insurance)",
        "category": "freight_insurance", "region": "Global",
        "auth_type": "api_key",
        "settings_keys": ["throughput_api_key"],
        "description": "Embedded cargo insurance API for logistics platforms. Quote, bind, and cert in one API call.",
        "capabilities": ["Embedded insurance", "Instant bind", "Digital cert", "All modes", "Global coverage"],
        "website": "https://www.getthroughput.com", "docs": "https://docs.getthroughput.com"
    },
    "one_cover": {
        "name": "OneCover (AU/NZ Freight Insurance)",
        "category": "freight_insurance", "region": "Australia / New Zealand",
        "auth_type": "api_key",
        "settings_keys": ["onecover_api_key"],
        "description": "Australian freight and cargo insurance. Marine transit, road, air. Instant online certificates.",
        "capabilities": ["Marine transit", "Road freight", "Air freight", "Certificate API"],
        "website": "https://www.onecover.com.au", "docs": "https://api.onecover.com.au"
    },
    "tiq": {
        "name": "TIQ (The Insurance Quarter — Europe)",
        "category": "freight_insurance", "region": "Europe",
        "auth_type": "api_key",
        "settings_keys": ["tiq_api_key"],
        "description": "European cargo insurance API. Instant quotes for road, sea, air freight across EU.",
        "capabilities": ["Road", "Sea", "Air", "Instant quote", "EU coverage"],
        "website": "https://www.tiq.de", "docs": "https://api.tiq.de/cargo"
    },
    "coverhound_cargo": {
        "name": "CoverHound Cargo (US SMB)",
        "category": "freight_insurance", "region": "North America",
        "auth_type": "api_key",
        "settings_keys": ["coverhound_api_key"],
        "description": "Commercial cargo insurance for small/mid-size shippers and brokers. API quoting and binding.",
        "capabilities": ["Commercial cargo", "Motor truck cargo", "Instant quote", "Digital bind"],
        "website": "https://www.coverhound.com", "docs": "https://developer.coverhound.com"
    },
    "global_indemnity": {
        "name": "Global Indemnity Group (Specialty Cargo)",
        "category": "freight_insurance", "region": "Global",
        "auth_type": "api_key",
        "settings_keys": ["gig_api_key", "gig_producer_code"],
        "description": "Specialty cargo insurance including high-value, hazmat, temperature-sensitive, and project cargo.",
        "capabilities": ["High-value cargo", "Hazmat", "Reefer", "Project cargo", "Excess coverage"],
        "website": "https://www.globalindemnity.com", "docs": "https://api.globalindemnity.com"
    },
    "tt_club": {
        "name": "TT Club",
        "category": "Insurance",
        "region": "Global",
        "color": "#1a237e",
        "description": "Mutual insurer for freight forwarders, 3PLs, and logistics operators. P&I, cargo liability, and cyber coverage.",
        "website": "https://www.ttclub.com",
        "connection_type": "coming_soon",
        "capabilities": ["P&I insurance", "Cargo liability", "Cyber", "Legal expenses", "Freight forwarding"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ELECTRONIC BILL OF LADING
    # ══════════════════════════════════════════════════════════════════════════
    "bolero": {
        "name": "Bolero (eBL)",
        "category": "Trade Documents",
        "region": "Global",
        "color": "#1b5e20",
        "description": "Electronic Bill of Lading platform. Transfer title digitally — replace paper B/L for ocean freight.",
        "website": "https://www.bolero.net",
        "connection_type": "request",
        "capabilities": ["Electronic B/L", "Title transfer", "Bank integration", "LC digitization"],
    },
    "essdocs": {
        "name": "essDOCS (CargoDocs)",
        "category": "Trade Documents",
        "region": "Global",
        "color": "#0d47a1",
        "description": "Paperless trade documentation for eBL, sea waybills, and shipping docs. Used by 30+ top banks.",
        "website": "https://www.essdocs.com",
        "connection_type": "request",
        "capabilities": ["eBL", "Sea waybill", "Letter of credit", "Bank connectivity", "Commodity trading"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ERP CONNECTORS
    # ══════════════════════════════════════════════════════════════════════════
    "sap": {
        "name": "SAP S/4HANA",
        "category": "ERP",
        "region": "Global",
        "color": "#0070f2",
        "description": "Sync purchase orders, inventory, and shipment data with SAP S/4HANA via REST API or IDoc EDI bridge.",
        "website": "https://www.sap.com",
        "connection_type": "api_key",
        "fields": [{"key": "host", "label": "SAP Host URL", "type": "text"},
                   {"key": "client", "label": "SAP Client Number", "type": "text"},
                   {"key": "username", "label": "Service Account Username", "type": "text"},
                   {"key": "password", "label": "Service Account Password", "type": "password"}],
        "key_guide": "SAP BTP Cockpit → Instances & Subscriptions → Service Key → Download JSON → extract host/credentials",
        "docs": "https://api.sap.com",
        "capabilities": ["PO sync", "Inventory", "Shipment confirmation", "Invoice matching", "IDoc EDI"],
    },
    "oracle_netsuite": {
        "name": "Oracle NetSuite",
        "category": "ERP",
        "region": "Global",
        "color": "#c74634",
        "description": "Sync orders, inventory, and financials between TMS and NetSuite via SuiteScript REST API.",
        "website": "https://www.netsuite.com",
        "connection_type": "api_key",
        "fields": [{"key": "account_id", "label": "Account ID", "type": "text"},
                   {"key": "consumer_key", "label": "Consumer Key", "type": "password"},
                   {"key": "consumer_secret", "label": "Consumer Secret", "type": "password"},
                   {"key": "token_id", "label": "Token ID", "type": "text"},
                   {"key": "token_secret", "label": "Token Secret", "type": "password"}],
        "key_guide": "NetSuite → Setup → Integration → Manage Integrations → Create new → enable Token-Based Authentication",
        "docs": "https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/chapter_N2935730.html",
        "capabilities": ["Order sync", "Inventory", "Invoice", "Customer records", "Financial reconciliation"],
    },
    "dynamics365": {
        "name": "Microsoft Dynamics 365",
        "category": "ERP",
        "region": "Global",
        "color": "#0078d4",
        "description": "Sync shipments, orders, and logistics data with Dynamics 365 Supply Chain Management via Dataverse API.",
        "website": "https://dynamics.microsoft.com",
        "connection_type": "oauth",
        "oauth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "oauth_scopes": "https://api.businesscentral.dynamics.com/.default",
        "fields": [{"key": "tenant_id", "label": "Azure Tenant ID", "type": "text"},
                   {"key": "client_id", "label": "App Client ID", "type": "text"},
                   {"key": "client_secret", "label": "App Client Secret", "type": "password"}],
        "key_guide": "Azure AD → App registrations → New registration → note Tenant ID + Client ID → Certificates & secrets → New client secret",
        "docs": "https://docs.microsoft.com/en-us/dynamics365/supply-chain",
        "capabilities": ["Order management", "Inventory", "Warehouse", "Transportation", "Power BI"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # WMS
    # ══════════════════════════════════════════════════════════════════════════
    "manhattan_wms": {
        "name": "Manhattan Associates WMS",
        "category": "WMS",
        "region": "Global",
        "color": "#1565c0",
        "description": "Enterprise WMS integration. Sync shipment releases, inventory levels, and warehouse events via Manhattan SCALE API.",
        "website": "https://www.manh.com",
        "connection_type": "request",
        "capabilities": ["Inventory sync", "Order release", "Pick/pack/ship", "Returns", "Robotics"],
    },
    "blue_yonder_wms": {
        "name": "Blue Yonder WMS",
        "category": "WMS",
        "region": "Global",
        "color": "#1a237e",
        "description": "Blue Yonder Luminate Logistics WMS integration for order fulfillment, returns, and inventory visibility.",
        "website": "https://blueyonder.com",
        "connection_type": "request",
        "capabilities": ["Order fulfillment", "Inventory", "Returns", "Automation", "AI planning"],
    },
    "korber_wms": {
        "name": "Körber WMS",
        "category": "WMS",
        "region": "Global",
        "color": "#e63946",
        "description": "Körber (HighJump) WMS with open API. Strong in 3PL market with robotics orchestration.",
        "website": "https://www.koerber-supplychain.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_endpoint", "label": "API Endpoint URL", "type": "text"},
                   {"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Körber WMS Admin → System Settings → API Configuration → Generate Key",
        "docs": "https://developer.koerber-supplychain.com",
        "capabilities": ["3PL billing", "Inventory", "Order fulfillment", "Robotics", "Multi-client"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # FREIGHT AUDIT & PAYMENT
    # ══════════════════════════════════════════════════════════════════════════
    "cass": {
        "name": "Cass Information Systems",
        "category": "Freight Audit & Pay",
        "region": "Global",
        "color": "#00695c",
        "description": "Processes $38B+ freight spend annually. Automated invoice auditing, rate validation, and carrier payment.",
        "website": "https://www.cassinfo.com",
        "connection_type": "request",
        "capabilities": ["Invoice audit", "Rate validation", "Carrier payment", "Spend analytics", "EDI"],
    },
    "paycargo": {
        "name": "PayCargo",
        "category": "Freight Audit & Pay",
        "region": "Global",
        "color": "#2e7d32",
        "description": "Digital freight payment platform. Pay carriers, airlines, ports, and agents electronically per shipment.",
        "website": "https://www.paycargo.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "company_code", "label": "Company Code", "type": "text"}],
        "key_guide": "PayCargo Portal → Settings → API Integration → Request API Access → copy key",
        "docs": "https://api.paycargo.com/docs",
        "capabilities": ["Freight payment", "Air cargo payment", "Port fees", "Customs duties", "Reconciliation"],
    },

    # ══════════════════════════════════════════════════════════════════════════
    # EXISTING INTEGRATIONS (kept from original)
    # ══════════════════════════════════════════════════════════════════════════
    "dat": {
        "name": "DAT Freight & Analytics",
        "category": "Load Board",
        "region": "North America",
        "color": "#e63946",
        "description": "Largest freight marketplace in North America. Post loads, find carriers, access rate data.",
        "website": "https://www.dat.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "client_id", "label": "Client ID", "type": "text"}],
        "key_guide": "DAT One → Account → Integrations → API Keys → Create New Key",
        "docs": "https://developer.dat.com",
        "capabilities": ["Load posting", "Rate lookup", "Carrier search", "Market data"],
    },
    "truckstop": {
        "name": "Truckstop.com",
        "category": "Load Board",
        "region": "North America",
        "color": "#f77f00",
        "description": "Trusted freight marketplace connecting brokers and carriers across North America.",
        "website": "https://truckstop.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "username", "label": "Username", "type": "text"}],
        "key_guide": "Truckstop → My Account → API Access → Generate Key",
        "docs": "https://developer.truckstop.com",
        "capabilities": ["Load board", "Rate analytics", "Carrier vetting", "DOT lookup"],
    },
    "highway": {
        "name": "Highway",
        "category": "Carrier Vetting",
        "region": "North America",
        "color": "#4cc9f0",
        "description": "AI-powered carrier identity and fraud prevention.",
        "website": "https://www.highway.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Highway Dashboard → Settings → API → Generate Key",
        "docs": "https://docs.highway.com",
        "capabilities": ["Carrier identity", "Fraud detection", "DOT/MC lookup", "Insurance verification"],
    },
    "rmis": {
        "name": "RMIS (Registry Monitoring Insurance Services)",
        "category": "carrier_compliance",
        "region": "North America",
        "color": "#2563eb",
        "auth_type": "api_key",
        "settings_keys": ["rmis_api_key", "rmis_username"],
        "settings_labels": {
            "rmis_api_key": "API Key",
            "rmis_username": "Username",
        },
        "description": "Carrier compliance monitoring. Insurance cert verification, authority checks, safety scores, automated alerts when carrier goes out of compliance.",
        "capabilities": ["Insurance verification", "Authority monitoring", "Safety score", "Compliance alerts", "Carrier onboarding packet"],
        "website": "https://www.rmis.com",
        "docs": "https://api.rmis.com/docs"
    },
    "my_carrier_packets": {
        "name": "MyCarrierPackets",
        "category": "carrier_compliance",
        "region": "North America",
        "color": "#0f766e",
        "auth_type": "api_key",
        "settings_keys": ["mcp_api_key"],
        "settings_labels": {
            "mcp_api_key": "API Key",
        },
        "description": "Digital carrier onboarding packets. W-9, insurance cert, agreement signature, carrier setup all in one flow.",
        "capabilities": ["Digital W-9", "Insurance cert upload", "Agreement e-sign", "Carrier setup", "Compliance tracking"],
        "website": "https://www.mycarrierpackets.com",
        "docs": "https://api.mycarrierpackets.com"
    },
    "carrier411": {
        "name": "Carrier411",
        "category": "carrier_compliance",
        "region": "North America",
        "color": "#dc2626",
        "auth_type": "api_key",
        "settings_keys": ["carrier411_api_key"],
        "settings_labels": {
            "carrier411_api_key": "API Key",
        },
        "description": "Carrier safety monitoring. Real-time FMCSA data, CSA scores, out-of-service rates, authority status alerts.",
        "capabilities": ["CSA scores", "OOS rates", "Authority alerts", "Crash history", "Inspection data"],
        "website": "https://www.carrier411.com",
        "docs": "https://www.carrier411.com/api"
    },
    "saferwatch": {
        "name": "SaferWatch",
        "category": "carrier_compliance",
        "region": "North America",
        "color": "#0ea5e9",
        "auth_type": "api_key",
        "settings_keys": ["saferwatch_api_key"],
        "settings_labels": {
            "saferwatch_api_key": "API Key",
        },
        "description": "Carrier safety and compliance monitoring with mobile app for drivers. CSA, insurance, authority in real time.",
        "capabilities": ["Real-time CSA", "Insurance monitoring", "Driver app", "Compliance reports", "API webhooks"],
        "website": "https://www.saferwatch.com",
        "docs": "https://saferwatch.com/developers"
    },
    "assure_assist": {
        "name": "Assure Assist (Global Carrier Compliance)",
        "category": "carrier_compliance",
        "region": "Global",
        "color": "#7c3aed",
        "auth_type": "api_key",
        "settings_keys": ["assure_api_key"],
        "settings_labels": {
            "assure_api_key": "API Key",
        },
        "description": "Global carrier onboarding and compliance. Covers AU, UK, EU, CA. Licence checks, insurance, operator accreditation.",
        "capabilities": ["Global compliance", "Licence verification", "Insurance check", "Onboarding workflow", "Audit trail"],
        "website": "https://www.assureassist.com.au",
        "docs": "https://assureassist.com.au/api"
    },
    "greenscreens": {
        "name": "Greenscreens.ai (AI Rate Intelligence)",
        "category": "rate_intelligence",
        "region": "North America",
        "color": "#16a34a",
        "auth_type": "api_key",
        "settings_keys": ["greenscreens_api_key", "greenscreens_customer_id"],
        "settings_labels": {
            "greenscreens_api_key": "API Key",
            "greenscreens_customer_id": "Customer ID",
        },
        "description": "AI-powered freight rate predictions. Lane-level buy/sell rate recommendations updated every 15 minutes using ML on market data.",
        "capabilities": ["Buy rate prediction", "Sell rate guidance", "Lane analytics", "Market intelligence", "DAT/Truckstop feed"],
        "website": "https://www.greenscreens.ai",
        "docs": "https://docs.greenscreens.ai"
    },
    "apex_capital": {
        "name": "Apex Capital (Factoring + Fuel Cards)",
        "category": "factoring",
        "region": "North America",
        "color": "#f97316",
        "auth_type": "api_key",
        "settings_keys": ["apex_api_key", "apex_client_id"],
        "settings_labels": {
            "apex_api_key": "API Key",
            "apex_client_id": "Client ID",
        },
        "description": "Freight factoring, fuel cards, and quick pay for carriers. Same-day funding on invoices.",
        "capabilities": ["Invoice factoring", "Fuel cards", "Same-day pay", "Load advances", "Credit checks"],
        "website": "https://www.apexcapitalcorp.com",
        "docs": "https://developer.apexcapitalcorp.com"
    },
    "tafs": {
        "name": "TAFS (Transport Alliance Financial Services)",
        "category": "factoring",
        "region": "North America",
        "color": "#b45309",
        "auth_type": "api_key",
        "settings_keys": ["tafs_api_key"],
        "settings_labels": {
            "tafs_api_key": "API Key",
        },
        "description": "Freight factoring and fuel advance program. Recourse and non-recourse factoring for carriers and owner-operators.",
        "capabilities": ["Factoring", "Fuel advance", "Credit checks", "Online portal", "Same-day funding"],
        "website": "https://www.tafs.com",
        "docs": "https://www.tafs.com/api-integration"
    },
    "ntelx": {
        "name": "NtelX (Asia-Pacific Carrier Compliance)",
        "category": "carrier_compliance",
        "region": "Asia-Pacific",
        "color": "#8b5cf6",
        "auth_type": "api_key",
        "settings_keys": ["ntelx_api_key"],
        "settings_labels": {
            "ntelx_api_key": "API Key",
        },
        "description": "Carrier compliance and risk management for APAC logistics operators. Covers AU/NZ/SG transport operator licence verification.",
        "capabilities": ["Operator licence check", "Insurance verification", "Risk scoring", "Compliance alerts"],
        "website": "https://www.ntelx.com",
        "docs": "https://ntelx.com/developers"
    },
    "verisk_transport": {
        "name": "Verisk Transport Analytics",
        "category": "carrier_compliance",
        "region": "Global",
        "color": "#475569",
        "auth_type": "api_key",
        "settings_keys": ["verisk_api_key", "verisk_org_id"],
        "settings_labels": {
            "verisk_api_key": "API Key",
            "verisk_org_id": "Organization ID",
        },
        "description": "Global carrier risk scoring and compliance analytics. Covers FMCSA (US), DVSA (UK), BASt (DE), VicRoads (AU) data feeds.",
        "capabilities": ["Global risk score", "Cross-border compliance", "Insurance analytics", "Carrier benchmarking"],
        "website": "https://www.verisk.com/transportation",
        "docs": "https://developer.verisk.com/transport"
    },
    "project44": {
        "name": "project44",
        "category": "Visibility",
        "region": "Global",
        "color": "#6d28d9",
        "description": "Real-time multimodal visibility across ocean, air, LTL, FTL, rail, and parcel.",
        "website": "https://www.project44.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "client_id", "label": "Client ID", "type": "text"}],
        "key_guide": "project44 Portal → Settings → API Keys → Create",
        "docs": "https://api.project44.com",
        "capabilities": ["Ocean tracking", "LTL/FTL", "Air", "Rail", "Predictive ETA"],
    },
    "fourkites": {
        "name": "FourKites",
        "category": "Visibility",
        "region": "Global",
        "color": "#0ea5e9",
        "description": "Global supply chain visibility platform. Real-time tracking across 500+ enterprise shippers.",
        "website": "https://www.fourkites.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "FourKites Dashboard → Administration → API Keys → Generate",
        "docs": "https://developer.fourkites.com",
        "capabilities": ["Multi-modal tracking", "AI ETAs", "Yard management", "Analytics"],
    },
    "maersk": {
        "name": "Maersk API",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#42b0d5",
        "description": "Direct Maersk booking, schedules, rates, tracking, and B/L management.",
        "website": "https://developer.maersk.com",
        "connection_type": "api_key",
        "fields": [{"key": "consumer_key", "label": "Consumer Key", "type": "password"},
                   {"key": "consumer_secret", "label": "Consumer Secret", "type": "password"}],
        "key_guide": "Maersk Developer Portal → My Apps → Create App → copy Consumer Key + Secret",
        "docs": "https://developer.maersk.com",
        "capabilities": ["Booking", "Schedule lookup", "B/L", "Tracking", "Rate quotes"],
    },
    "msc": {
        "name": "MSC",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#003087",
        "description": "Mediterranean Shipping Company — world's largest container line by fleet size.",
        "website": "https://www.msc.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "MSC myMSC Portal → API Access → Request Integration",
        "docs": "https://www.msc.com/api",
        "capabilities": ["Booking", "Tracking", "Schedule", "Rate inquiry"],
    },
    "hapag_lloyd": {
        "name": "Hapag-Lloyd",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#f15a22",
        "description": "Hapag-Lloyd direct booking, tracking, and schedule APIs.",
        "website": "https://developer.hapag-lloyd.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "client_id", "label": "Client ID", "type": "text"}],
        "key_guide": "Hapag-Lloyd Developer Portal → Create App → copy API Key",
        "docs": "https://developer.hapag-lloyd.com",
        "capabilities": ["Booking", "B/L", "Tracking", "Schedule", "Rate inquiry"],
    },
    "cma_cgm": {
        "name": "CMA CGM",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#003087",
        "description": "CMA CGM API for bookings, container tracking, and vessel schedules.",
        "website": "https://www.cma-cgm.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "CMA CGM eBusiness Portal → API Access → Generate Key",
        "docs": "https://www.cma-cgm.com/ebusiness/api",
        "capabilities": ["Booking", "Tracking", "Schedule", "Documentation"],
    },
    "one_ocean": {
        "name": "ONE (Ocean Network Express)",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#e63946",
        "description": "ONE is the world's 7th largest container carrier, formed from NYK, MOL, K Line.",
        "website": "https://www.one-line.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "ONE eCommerce → API Integration → Request Access",
        "docs": "https://ecomm.one-line.com/api",
        "capabilities": ["Booking", "Tracking", "B/L", "Schedule"],
    },
    "evergreen": {
        "name": "Evergreen Line",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#2d6a4f",
        "description": "Evergreen container shipping API for bookings and tracking.",
        "website": "https://www.evergreen-line.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Evergreen eBusiness → API → Request API Credentials",
        "docs": "https://www.evergreen-line.com/static/cms/en-global/e-commerce.html",
        "capabilities": ["Booking", "Tracking", "Schedule", "Documentation"],
    },
    "cosco": {
        "name": "COSCO Shipping",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#e63946",
        "description": "China COSCO Shipping — world's 4th largest container line. Essential for China trade lanes.",
        "website": "https://elines.coscoshipping.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "COSCO eShipping → API Center → Apply for API access",
        "docs": "https://elines.coscoshipping.com/ebusiness/API",
        "capabilities": ["Booking", "Tracking", "Schedule", "Rate inquiry", "China focus"],
    },
    "zim": {
        "name": "ZIM",
        "category": "Ocean Carrier",
        "region": "Global",
        "color": "#003087",
        "description": "ZIM Integrated Shipping — strong on Asia-US East Coast and Middle East routes.",
        "website": "https://www.zim.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "ZIM eBusiness Portal → API Integration → Generate Key",
        "docs": "https://www.zim.com/api",
        "capabilities": ["Booking", "Tracking", "Schedule", "Documentation"],
    },
    "cargowise": {
        "name": "CargoWise",
        "category": "Global TMS",
        "region": "Global",
        "color": "#1565c0",
        "description": "CargoWise One — the world's most widely used freight forwarding platform. Sync clients, shipments, invoices.",
        "website": "https://cargowise.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "server_url", "label": "Server URL", "type": "text"}],
        "key_guide": "CargoWise → System → Setup → API → Generate Token",
        "docs": "https://cargowise.com/developer",
        "capabilities": ["Shipment sync", "Client records", "Invoice", "Customs", "Port connectivity"],
    },
    "flexport": {
        "name": "Flexport",
        "category": "Digital Freight",
        "region": "Global",
        "color": "#5046e5",
        "description": "Flexport API for shipment visibility, booking, and document management across ocean and air.",
        "website": "https://flexport.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Flexport Platform → Account → API Tokens → Create Token",
        "docs": "https://apidocs.flexport.com",
        "capabilities": ["Booking", "Visibility", "Documents", "Invoicing", "Analytics"],
    },
    "freightos": {
        "name": "Freightos",
        "category": "Rate Marketplace",
        "region": "Global",
        "color": "#0ea5e9",
        "description": "Instant air/ocean freight rates and booking from 100+ freight providers on one platform.",
        "website": "https://freightos.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Freightos Developer Portal → My Apps → Generate API Key",
        "docs": "https://developers.freightos.com",
        "capabilities": ["Instant rate quotes", "Ocean booking", "Air booking", "100+ providers"],
    },
    "descartes": {
        "name": "Descartes Systems",
        "category": "Customs & Compliance",
        "region": "Global",
        "color": "#1a237e",
        "description": "Global compliance, customs filing, trade content, and routing optimization.",
        "website": "https://www.descartes.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "account_id", "label": "Account ID", "type": "text"}],
        "key_guide": "Descartes GLN → My Account → API Access → Generate Key",
        "docs": "https://developer.descartes.com",
        "capabilities": ["Customs filing", "Trade compliance", "Routing", "ELD", "Port community"],
    },
    "webcargo": {
        "name": "WebCargo by Freightos",
        "category": "Air Freight",
        "region": "Global",
        "color": "#7c3aed",
        "description": "Air cargo booking and rates from 50+ airlines in one API. Real-time AWB and e-booking.",
        "website": "https://www.webcargo.net",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "WebCargo Portal → API Access → Generate Key",
        "docs": "https://developer.webcargo.net",
        "capabilities": ["Air rates", "AWB booking", "50+ airlines", "Real-time capacity", "e-AWB"],
    },
    "cargo_ai": {
        "name": "Cargo.AI",
        "category": "Air Freight",
        "region": "Global",
        "color": "#0ea5e9",
        "description": "AI-powered air cargo rate intelligence and booking platform.",
        "website": "https://cargo.ai",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"}],
        "key_guide": "Cargo.AI Platform → Settings → API → Generate Key",
        "docs": "https://docs.cargo.ai",
        "capabilities": ["Air rates", "Booking", "AI forecasting", "Capacity alerts"],
    },
    "triumphpay": {
        "name": "TriumphPay",
        "category": "Freight Finance",
        "region": "North America",
        "color": "#7c3aed",
        "description": "Freight payment network for brokers and carriers. Factoring, quick pay, and carrier payment.",
        "website": "https://www.triumphpay.com",
        "connection_type": "api_key",
        "fields": [{"key": "api_key", "label": "API Key", "type": "password"},
                   {"key": "account_id", "label": "Account ID", "type": "text"}],
        "key_guide": "TriumphPay Portal → Settings → API → Generate Key",
        "docs": "https://developer.triumphpay.com",
        "capabilities": ["Carrier payment", "Quick pay", "Factoring", "Invoice processing"],
    },
}

# ── Category ordering for display ─────────────────────────────────────────────
CATEGORY_LABELS = {
    "carrier_compliance": "Carrier Compliance",
    "rate_intelligence": "Rate Intelligence",
    "factoring": "Factoring",
}

SETTINGS_CATEGORY_ORDER = [
    "carrier_compliance",
    "factoring",
]


def _credential_input_type(setting_key: str) -> str:
    lowered = setting_key.lower()
    if any(token in lowered for token in ("secret", "token", "password", "api_key")):
        return "password"
    return "text"


def _normalize_provider_catalog() -> None:
    for provider in PROVIDERS.values():
        settings_keys = provider.get("settings_keys", [])
        settings_labels = provider.setdefault("settings_labels", {})
        for key in settings_keys:
            settings_labels.setdefault(key, key.replace("_", " ").title())
        if settings_keys and not provider.get("fields"):
            provider["fields"] = [
                {
                    "key": key,
                    "label": settings_labels[key],
                    "type": _credential_input_type(key),
                }
                for key in settings_keys
            ]
        if provider.get("auth_type") == "api_key":
            provider.setdefault("connection_type", "api_key")
        if provider.get("docs") and not provider.get("docs_url"):
            provider["docs_url"] = provider["docs"]


def _settings_providers(categories=None) -> dict:
    allowed = set(categories or SETTINGS_CATEGORY_ORDER)
    return {
        key: provider
        for key, provider in PROVIDERS.items()
        if provider.get("category") in allowed and provider.get("settings_keys")
    }


def get_integration_settings(categories=None) -> dict:
    providers = _settings_providers(categories)
    if not providers:
        return {}

    from .tms_db import init_tms_db, get_db

    init_tms_db()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT integration_key, encrypted_fields FROM integration_connections WHERE integration_key IN ({})".format(
                ",".join("?" * len(providers))
            ),
            list(providers),
        ).fetchall()
    finally:
        conn.close()

    settings = {}
    for row in rows:
        try:
            stored = json.loads(row["encrypted_fields"] or "{}")
        except Exception:
            stored = {}
        for key, value in stored.items():
            settings[key] = decrypt_key(value)
    return settings


def save_integration_settings(data: dict, categories=None) -> None:
    providers = _settings_providers(categories)
    if not providers:
        return

    from .tms_db import init_tms_db, get_db

    init_tms_db()
    conn = get_db()
    try:
        for provider_key, provider in providers.items():
            values = {
                key: str(data.get(key, "")).strip()
                for key in provider.get("settings_keys", [])
            }
            encrypted = {
                key: encrypt_key(value)
                for key, value in values.items()
                if value
            }
            if encrypted:
                conn.execute(
                    """INSERT INTO integration_connections (integration_key, encrypted_fields, status, updated_at)
                       VALUES (?, ?, 'connected', CURRENT_TIMESTAMP)
                       ON CONFLICT(tenant_id, integration_key) DO UPDATE SET
                           encrypted_fields=excluded.encrypted_fields,
                           status='connected',
                           last_error='',
                           updated_at=CURRENT_TIMESTAMP""",
                    (provider_key, json.dumps(encrypted)),
                )
            else:
                conn.execute(
                    "DELETE FROM integration_connections WHERE integration_key=?",
                    (provider_key,),
                )
        conn.commit()
    finally:
        conn.close()


def get_settings_providers(categories=None) -> list:
    settings = get_integration_settings(categories)
    providers = []
    for key, provider in _settings_providers(categories).items():
        values = [settings.get(setting_key, "") for setting_key in provider.get("settings_keys", [])]
        providers.append({
            **provider,
            "key": key,
            "creds_saved": all(values),
            "partial_saved": any(values) and not all(values),
            "docs_url": provider.get("docs_url") or provider.get("docs") or provider.get("website"),
        })
    return providers


_normalize_provider_catalog()
INTEGRATIONS = PROVIDERS

CATEGORY_ORDER = [
    "Internal Network",
    "Parcel",
    "Ocean Carrier",
    "Digital Freight",
    "Load Board",
    "European Freight",
    "Asia-Pacific Freight",
    "Rail & Intermodal",
    "Telematics & ELD",
    "Visibility",
    "Port Systems",
    "Customs & Compliance",
    "Vessel Tracking",
    "Insurance",
    "Trade Documents",
    "ERP",
    "WMS",
    "Freight Audit & Pay",
    "Air Freight",
    "Carrier Vetting",
    "carrier_compliance",
    "Global TMS",
    "Rate Marketplace",
    "rate_intelligence",
    "Freight Finance",
    "factoring",
]
