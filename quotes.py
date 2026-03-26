"""
quotes.py  —  Invoice & Quote PDF Generation for Freight Intelligence Dashboard

Generates professional freight rate quotes and invoices as PDF files.
Uses HTML → PDF conversion via weasyprint (or falls back to HTML export).
"""

import io
import os
from datetime import datetime, timedelta
from database import get_db


# ─────────────────────────────────────────────────────────────────────────────
#  Quote / Invoice Number Generation
# ─────────────────────────────────────────────────────────────────────────────

def _next_number(tenant_id: int, prefix: str = "QT") -> str:
    """Generate next sequential quote/invoice number for a tenant."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT MAX(CAST(SUBSTR(doc_number, LENGTH(?) + 2) AS INTEGER)) "
            "FROM quotes WHERE tenant_id = ? AND doc_number LIKE ?",
            (prefix, tenant_id, f"{prefix}-%"),
        ).fetchone()
        seq = (row[0] or 0) + 1
        return f"{prefix}-{seq:05d}"
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Database Schema
# ─────────────────────────────────────────────────────────────────────────────

def init_quotes_db():
    """Create quotes/invoices tables."""
    conn = get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quotes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                doc_type    TEXT    NOT NULL DEFAULT 'quote',
                doc_number  TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'draft',
                client_name TEXT    NOT NULL DEFAULT '',
                client_email TEXT   NOT NULL DEFAULT '',
                client_company TEXT NOT NULL DEFAULT '',
                origin      TEXT    NOT NULL DEFAULT '',
                destination TEXT    NOT NULL DEFAULT '',
                origin_locode  TEXT NOT NULL DEFAULT '',
                dest_locode    TEXT NOT NULL DEFAULT '',
                carrier     TEXT    NOT NULL DEFAULT '',
                container_type TEXT NOT NULL DEFAULT '40ft',
                rate_amount REAL   NOT NULL DEFAULT 0,
                currency    TEXT   NOT NULL DEFAULT 'USD',
                valid_from  TEXT   NOT NULL DEFAULT '',
                valid_to    TEXT   NOT NULL DEFAULT '',
                transit_days INTEGER DEFAULT 0,
                notes       TEXT   NOT NULL DEFAULT '',
                line_items  TEXT   NOT NULL DEFAULT '[]',
                subtotal    REAL   NOT NULL DEFAULT 0,
                tax_pct     REAL   NOT NULL DEFAULT 0,
                tax_amount  REAL   NOT NULL DEFAULT 0,
                total       REAL   NOT NULL DEFAULT 0,
                sent_at     TEXT,
                viewed_at   TEXT,
                accepted_at TEXT,
                created_at  TEXT   NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT   NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  CRUD Operations
# ─────────────────────────────────────────────────────────────────────────────

def create_quote(tenant_id: int, user_id: int, data: dict) -> dict:
    """Create a new quote or invoice."""
    doc_type = data.get("doc_type", "quote")
    prefix = "INV" if doc_type == "invoice" else "QT"
    doc_number = _next_number(tenant_id, prefix)

    # Calculate totals from line items
    import json
    line_items = data.get("line_items", [])
    if isinstance(line_items, str):
        line_items = json.loads(line_items)

    subtotal = sum(item.get("amount", 0) for item in line_items)
    if not line_items and data.get("rate_amount"):
        subtotal = float(data["rate_amount"])
        line_items = [{
            "description": f"{data.get('container_type', '40ft')} container {data.get('origin', '')} → {data.get('destination', '')}",
            "qty": 1,
            "unit_price": subtotal,
            "amount": subtotal,
        }]

    tax_pct = float(data.get("tax_pct", 0))
    tax_amount = subtotal * (tax_pct / 100)
    total = subtotal + tax_amount

    valid_from = data.get("valid_from", datetime.now().strftime("%Y-%m-%d"))
    valid_to = data.get("valid_to", (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d"))

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO quotes (tenant_id, user_id, doc_type, doc_number, status,
                client_name, client_email, client_company,
                origin, destination, origin_locode, dest_locode,
                carrier, container_type, rate_amount, currency,
                valid_from, valid_to, transit_days, notes,
                line_items, subtotal, tax_pct, tax_amount, total)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            tenant_id, user_id, doc_type, doc_number, "draft",
            data.get("client_name", ""),
            data.get("client_email", ""),
            data.get("client_company", ""),
            data.get("origin", ""),
            data.get("destination", ""),
            data.get("origin_locode", ""),
            data.get("dest_locode", ""),
            data.get("carrier", ""),
            data.get("container_type", "40ft"),
            float(data.get("rate_amount", 0)),
            data.get("currency", "USD"),
            valid_from, valid_to,
            int(data.get("transit_days", 0)),
            data.get("notes", ""),
            json.dumps(line_items),
            subtotal, tax_pct, tax_amount, total,
        ))
        conn.commit()
        qid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"ok": True, "id": qid, "doc_number": doc_number}
    finally:
        conn.close()


def get_quote(quote_id: int, tenant_id: int) -> dict:
    """Fetch a single quote/invoice."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM quotes WHERE id = ? AND tenant_id = ?",
            (quote_id, tenant_id),
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def list_quotes(tenant_id: int, doc_type: str = None, status: str = None,
                limit: int = 50, offset: int = 0) -> list:
    """List quotes/invoices for a tenant."""
    conn = get_db()
    try:
        sql = "SELECT * FROM quotes WHERE tenant_id = ?"
        params = [tenant_id]
        if doc_type:
            sql += " AND doc_type = ?"
            params.append(doc_type)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_quote(quote_id: int, tenant_id: int, data: dict) -> dict:
    """Update a quote/invoice."""
    import json
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT * FROM quotes WHERE id = ? AND tenant_id = ?",
            (quote_id, tenant_id),
        ).fetchone()
        if not existing:
            return {"ok": False, "error": "Not found"}

        allowed = ["status", "client_name", "client_email", "client_company",
                    "origin", "destination", "carrier", "container_type",
                    "rate_amount", "currency", "valid_from", "valid_to",
                    "transit_days", "notes", "line_items", "tax_pct"]
        sets, vals = [], []
        for key in allowed:
            if key in data:
                val = data[key]
                if key == "line_items" and isinstance(val, list):
                    val = json.dumps(val)
                sets.append(f"{key} = ?")
                vals.append(val)

        if not sets:
            return {"ok": False, "error": "No fields to update"}

        # Recalculate totals
        line_items = data.get("line_items", json.loads(existing["line_items"]))
        if isinstance(line_items, str):
            line_items = json.loads(line_items)
        subtotal = sum(item.get("amount", 0) for item in line_items)
        if not line_items:
            subtotal = float(data.get("rate_amount", existing["rate_amount"]))
        tax_pct = float(data.get("tax_pct", existing["tax_pct"]))
        tax_amount = subtotal * (tax_pct / 100)
        total = subtotal + tax_amount

        sets.extend(["subtotal = ?", "tax_amount = ?", "total = ?", "updated_at = datetime('now')"])
        vals.extend([subtotal, tax_amount, total])

        vals.extend([quote_id, tenant_id])
        conn.execute(f"UPDATE quotes SET {', '.join(sets)} WHERE id = ? AND tenant_id = ?", vals)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def delete_quote(quote_id: int, tenant_id: int) -> dict:
    """Delete a quote/invoice."""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM quotes WHERE id = ? AND tenant_id = ?", (quote_id, tenant_id))
        conn.commit()
        if cur.rowcount:
            return {"ok": True}
        return {"ok": False, "error": "Not found"}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  PDF / HTML Generation
# ─────────────────────────────────────────────────────────────────────────────

def render_quote_html(quote: dict, tenant_name: str = "Flash Cargo Global") -> str:
    """Render a quote/invoice as professional HTML."""
    import json
    line_items = quote.get("line_items", "[]")
    if isinstance(line_items, str):
        line_items = json.loads(line_items)

    doc_label = "INVOICE" if quote.get("doc_type") == "invoice" else "RATE QUOTATION"
    currency = quote.get("currency", "USD")
    symbols = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$"}
    sym = symbols.get(currency, currency + " ")

    items_html = ""
    for item in line_items:
        qty = item.get("qty", 1)
        unit = item.get("unit_price", item.get("amount", 0))
        amt = item.get("amount", 0)
        items_html += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #eee;">{item.get('description','')}</td>
            <td style="padding:10px; border-bottom:1px solid #eee; text-align:center;">{qty}</td>
            <td style="padding:10px; border-bottom:1px solid #eee; text-align:right;">{sym}{unit:,.2f}</td>
            <td style="padding:10px; border-bottom:1px solid #eee; text-align:right;">{sym}{amt:,.2f}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Inter',sans-serif; color:#1a1a2e; background:#fff; padding:40px; }}
    .doc-header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:40px; }}
    .brand {{ font-size:24px; font-weight:700; color:#0047AB; }}
    .brand small {{ display:block; font-size:12px; font-weight:400; color:#666; }}
    .doc-title {{ text-align:right; }}
    .doc-title h1 {{ font-size:28px; color:#0047AB; letter-spacing:2px; }}
    .doc-title .doc-num {{ font-size:14px; color:#666; margin-top:4px; }}
    .info-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:30px; margin-bottom:30px; }}
    .info-box h3 {{ font-size:11px; text-transform:uppercase; letter-spacing:1px; color:#999; margin-bottom:8px; }}
    .info-box p {{ font-size:14px; line-height:1.6; }}
    .route-bar {{ background:#f0f4ff; border-left:4px solid #0047AB; padding:15px 20px; margin-bottom:30px; border-radius:0 8px 8px 0; }}
    .route-bar span {{ font-size:18px; font-weight:600; }}
    .route-bar .meta {{ font-size:13px; color:#666; margin-top:4px; }}
    table {{ width:100%; border-collapse:collapse; margin-bottom:20px; }}
    thead th {{ background:#0047AB; color:#fff; padding:12px; text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:1px; }}
    thead th:last-child, thead th:nth-child(3) {{ text-align:right; }}
    thead th:nth-child(2) {{ text-align:center; }}
    .totals {{ text-align:right; margin-top:10px; }}
    .totals .row {{ display:flex; justify-content:flex-end; gap:40px; padding:6px 0; font-size:14px; }}
    .totals .total {{ font-size:20px; font-weight:700; color:#0047AB; border-top:2px solid #0047AB; padding-top:10px; margin-top:6px; }}
    .validity {{ background:#f9fafb; padding:15px 20px; border-radius:8px; margin-top:30px; font-size:13px; color:#666; }}
    .notes {{ margin-top:20px; padding:15px 20px; background:#fffbeb; border-left:4px solid #f59e0b; border-radius:0 8px 8px 0; font-size:13px; }}
    .footer {{ margin-top:40px; text-align:center; font-size:11px; color:#999; border-top:1px solid #eee; padding-top:20px; }}
</style>
</head>
<body>
    <div class="doc-header">
        <div class="brand">{tenant_name}<small>Freight Intelligence Platform</small></div>
        <div class="doc-title">
            <h1>{doc_label}</h1>
            <div class="doc-num">{quote.get('doc_number','')}</div>
        </div>
    </div>

    <div class="info-grid">
        <div class="info-box">
            <h3>Prepared For</h3>
            <p><strong>{quote.get('client_name','')}</strong><br>
            {quote.get('client_company','')}<br>
            {quote.get('client_email','')}</p>
        </div>
        <div class="info-box" style="text-align:right;">
            <h3>Date</h3>
            <p>{quote.get('created_at','')[:10]}</p>
            <h3 style="margin-top:12px;">Valid Until</h3>
            <p>{quote.get('valid_to','')}</p>
        </div>
    </div>

    <div class="route-bar">
        <span>{quote.get('origin','')} → {quote.get('destination','')}</span>
        <div class="meta">
            Carrier: {quote.get('carrier','TBD')} &nbsp;|&nbsp;
            Container: {quote.get('container_type','40ft')} &nbsp;|&nbsp;
            Transit: {quote.get('transit_days',0)} days
        </div>
    </div>

    <table>
        <thead>
            <tr>
                <th>Description</th>
                <th>Qty</th>
                <th>Unit Price</th>
                <th>Amount</th>
            </tr>
        </thead>
        <tbody>
            {items_html}
        </tbody>
    </table>

    <div class="totals">
        <div class="row"><span>Subtotal:</span> <span>{sym}{quote.get('subtotal',0):,.2f}</span></div>
        {"<div class='row'><span>Tax (" + str(quote.get('tax_pct',0)) + "%):</span> <span>" + sym + f"{quote.get('tax_amount',0):,.2f}</span></div>" if quote.get('tax_pct',0) > 0 else ""}
        <div class="row total"><span>Total:</span> <span>{sym}{quote.get('total',0):,.2f} {currency}</span></div>
    </div>

    <div class="validity">
        Valid from <strong>{quote.get('valid_from','')}</strong> to <strong>{quote.get('valid_to','')}</strong>.
        Rates subject to carrier confirmation and space availability.
    </div>

    {"<div class='notes'><strong>Notes:</strong> " + quote.get('notes','') + "</div>" if quote.get('notes') else ""}

    <div class="footer">
        Generated by {tenant_name} — Powered by Freight Intelligence Dashboard<br>
        This is a computer-generated document. No signature required.
    </div>
</body>
</html>"""


def generate_pdf(quote: dict, tenant_name: str = "Flash Cargo Global") -> bytes:
    """Generate PDF from quote. Falls back to HTML if weasyprint not available."""
    html = render_quote_html(quote, tenant_name)
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except ImportError:
        # Fallback: return HTML as bytes (browser can print-to-PDF)
        return html.encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
#  Quick Quote from Rate (convert a rate to a client-facing quote)
# ─────────────────────────────────────────────────────────────────────────────

def quote_from_rate(tenant_id: int, user_id: int, rate_id: int,
                    client_name: str, client_email: str, client_company: str,
                    margin_pct: float = 15.0) -> dict:
    """Create a quote from an existing rate, adding a margin."""
    conn = get_db()
    try:
        rate = conn.execute("SELECT * FROM rates WHERE id = ?", (rate_id,)).fetchone()
        if not rate:
            return {"ok": False, "error": "Rate not found"}

        base = float(rate["rate_40ft"] or rate["rate_20ft"] or 0)
        marked_up = base * (1 + margin_pct / 100)

        return create_quote(tenant_id, user_id, {
            "doc_type": "quote",
            "client_name": client_name,
            "client_email": client_email,
            "client_company": client_company,
            "origin": rate.get("origin", ""),
            "destination": rate.get("destination", ""),
            "origin_locode": rate.get("origin_locode", ""),
            "dest_locode": rate.get("dest_locode", ""),
            "carrier": rate.get("carrier", ""),
            "container_type": "40ft" if rate.get("rate_40ft") else "20ft",
            "rate_amount": round(marked_up, 2),
            "currency": rate.get("currency", "USD"),
            "transit_days": 0,
            "notes": f"Based on carrier rate + {margin_pct}% service fee.",
        })
    finally:
        conn.close()
