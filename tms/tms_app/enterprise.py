import ipaddress
import re
from datetime import datetime, timedelta, timezone

try:
    from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
    from saml2.client import Saml2Client
    from saml2.config import SPConfig

    HAS_PYSAML2 = True
except Exception:
    BINDING_HTTP_POST = None
    BINDING_HTTP_REDIRECT = None
    Saml2Client = None
    SPConfig = None
    HAS_PYSAML2 = False


PASSWORD_POLICY_TEXT = "Use at least 12 characters with upper, lower, number, and symbol."
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


def normalize_tenant_id(value, fallback="tenant-default"):
    raw_value = (value or "").strip().lower()
    clean_value = re.sub(r"[^a-z0-9]+", "-", raw_value).strip("-")
    return clean_value or fallback


def validate_password_complexity(password):
    candidate = password or ""
    if len(candidate) < 12:
        return PASSWORD_POLICY_TEXT
    checks = [
        re.search(r"[A-Z]", candidate),
        re.search(r"[a-z]", candidate),
        re.search(r"\d", candidate),
        re.search(r"[^A-Za-z0-9]", candidate),
    ]
    if not all(checks):
        return PASSWORD_POLICY_TEXT
    return None


def parse_ip_rules(raw_value):
    if isinstance(raw_value, (list, tuple, set)):
        values = raw_value
    else:
        values = re.split(r"[\r\n,]+", str(raw_value or ""))
    rules = []
    for value in values:
        clean_value = str(value or "").strip()
        if not clean_value:
            continue
        rules.append(clean_value)
    return rules


def is_ip_allowed(ip_address, raw_rules):
    rules = parse_ip_rules(raw_rules)
    if not rules:
        return True
    if not ip_address:
        return False
    try:
        candidate = ipaddress.ip_address(ip_address)
    except ValueError:
        return False
    for rule in rules:
        try:
            if "/" in rule:
                if candidate in ipaddress.ip_network(rule, strict=False):
                    return True
            elif candidate == ipaddress.ip_address(rule):
                return True
        except ValueError:
            continue
    return False


def is_locked_until(locked_until):
    if not locked_until:
        return False
    try:
        return datetime.fromisoformat(locked_until) > datetime.now(timezone.utc)
    except ValueError:
        return False


def next_lockout_timestamp():
    return (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()


def build_saml_stub_context(tenant, issuer, acs_url):
    saml_ready = bool(
        tenant
        and tenant.get("saml_entity_id")
        and tenant.get("saml_sso_url")
        and HAS_PYSAML2
    )
    saml_client = None
    error = None
    if saml_ready:
        config = SPConfig()
        try:
            config.load(
                {
                    "entityid": issuer,
                    "service": {
                        "sp": {
                            "allow_unsolicited": True,
                            "endpoints": {
                                "assertion_consumer_service": [
                                    (acs_url, BINDING_HTTP_POST),
                                ],
                            },
                        }
                    },
                    "metadata": {"inline": [tenant.get("saml_metadata_url") or ""]},
                }
            )
            saml_client = Saml2Client(config=config)
        except Exception as exc:
            error = str(exc)
            saml_client = None
    elif tenant and not HAS_PYSAML2:
        error = "pysaml2 is not installed."

    return {
        "tenant": tenant,
        "issuer": issuer,
        "acs_url": acs_url,
        "has_pysaml2": HAS_PYSAML2,
        "saml_client_ready": saml_client is not None,
        "saml_error": error,
    }
