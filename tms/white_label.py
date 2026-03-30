"""
White-Label / Multi-Brand per Tenant
Tenant uploads logo, sets brand colors, custom domain, email from-name.
Injected into every page via Jinja2 context processor.
"""
import os
from .tms_db import get_db

DEFAULTS = {
    "brand_name":        "TMS Master",
    "brand_color":       "#c8a96e",
    "brand_color_dark":  "#0a0c0f",
    "brand_logo_url":    "",
    "brand_favicon_url": "",
    "custom_domain":     "",
    "email_from_name":   "TMS Master",
    "email_from_address":"",
    "support_email":     "",
    "support_phone":     "",
    "footer_text":       "Powered by TMS Master",
    "hide_powered_by":   "0",
    "primary_font":      "Inter",
    "sidebar_style":     "dark",
}


def _init_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenant_branding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            setting_key TEXT NOT NULL,
            setting_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tenant_id, setting_key)
        )
    """)
    conn.commit()


def get_branding(tenant_id='default'):
    conn = get_db()
    _init_tables(conn)
    rows = conn.execute(
        "SELECT setting_key, setting_value FROM tenant_branding WHERE tenant_id=?",
        (tenant_id,)
    ).fetchall()
    result = dict(DEFAULTS)
    for r in rows:
        result[r['setting_key']] = r['setting_value']
    return result


def save_branding(tenant_id='default', data=None):
    conn = get_db()
    _init_tables(conn)
    data = data or {}
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        conn.execute("""
            INSERT INTO tenant_branding (tenant_id, setting_key, setting_value, updated_at)
            VALUES (?,?,?, CURRENT_TIMESTAMP)
            ON CONFLICT(tenant_id, setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=CURRENT_TIMESTAMP
        """, (tenant_id, key, value))
    conn.commit()


def get_css_vars(tenant_id='default'):
    """Returns CSS custom property overrides for this tenant's brand."""
    b = get_branding(tenant_id)
    css = f"""
:root {{
    --gold: {b['brand_color']};
    --gold-accent: {b['brand_color']};
    --tms-brand-color: {b['brand_color']};
    --tms-bg: {b['brand_color_dark']};
}}"""
    return css


def get_all_tenant_brandings():
    conn = get_db()
    _init_tables(conn)
    tenant_ids = conn.execute(
        "SELECT DISTINCT tenant_id FROM tenant_branding"
    ).fetchall()
    result = []
    for t in tenant_ids:
        b = get_branding(t['tenant_id'])
        b['tenant_id'] = t['tenant_id']
        result.append(b)
    return result
