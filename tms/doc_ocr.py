"""Document OCR — extract shipment data from uploaded images/PDFs."""
import os
import re
import sqlite3
import json
from datetime import datetime

DB_PATH = os.getenv("TMS_CONTACTS_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "contacts.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_ocr_tables():
    conn = get_db()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS ocr_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            raw_text TEXT DEFAULT '',
            extracted_data TEXT DEFAULT '{}',
            shipment_ref TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            error TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.commit()
    finally:
        conn.close()


init_ocr_tables()


def extract_text_from_image(file_path: str) -> str:
    """Extract text from image using pytesseract if available, else return empty string."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(file_path)
        return pytesseract.image_to_string(img)
    except ImportError:
        return ""
    except Exception as e:
        return f"OCR_ERROR: {e}"


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF using pdfplumber if available."""
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += (page.extract_text() or "") + "\n"
        return text
    except ImportError:
        return ""
    except Exception as e:
        return f"PDF_ERROR: {e}"


def parse_bol_fields(text: str) -> dict:
    """
    Parse common BOL fields from raw OCR text using regex patterns.
    Returns dict of extracted fields.
    """
    fields = {}

    # BOL Number
    bol_match = re.search(r'(?:BOL|B/L|Bill of Lading)[#:\s]+([A-Z0-9\-]+)', text, re.I)
    if bol_match:
        fields['bol_number'] = bol_match.group(1).strip()

    # Shipper/Origin
    ship_match = re.search(r'(?:SHIPPER|FROM|ORIGIN)[:\s]+([^\n]+)', text, re.I)
    if ship_match:
        fields['origin'] = ship_match.group(1).strip()[:100]

    # Consignee/Destination
    cons_match = re.search(r'(?:CONSIGNEE|TO|DESTINATION|DELIVER TO)[:\s]+([^\n]+)', text, re.I)
    if cons_match:
        fields['destination'] = cons_match.group(1).strip()[:100]

    # Weight
    weight_match = re.search(r'(?:WEIGHT|WT)[:\s]*([\d,]+)\s*(?:LBS?|KGS?)?', text, re.I)
    if weight_match:
        fields['weight'] = weight_match.group(1).replace(',', '')

    # Pieces/Units
    pieces_match = re.search(r'(?:PIECES|PCS|UNITS|QTY)[:\s]*([\d]+)', text, re.I)
    if pieces_match:
        fields['pieces'] = pieces_match.group(1)

    # PRO Number
    pro_match = re.search(r'(?:PRO|PRO#|PRO NO)[:\s]+([A-Z0-9\-]+)', text, re.I)
    if pro_match:
        fields['pro_number'] = pro_match.group(1).strip()

    # Date
    date_match = re.search(r'(?:DATE|SHIP DATE)[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})', text, re.I)
    if date_match:
        fields['ship_date'] = date_match.group(1)

    # Carrier
    carrier_match = re.search(r'(?:CARRIER|TRUCKING CO)[:\s]+([^\n]+)', text, re.I)
    if carrier_match:
        fields['carrier'] = carrier_match.group(1).strip()[:80]

    # Description of goods
    desc_match = re.search(r'(?:DESCRIPTION|COMMODITY|GOODS)[:\s]+([^\n]+)', text, re.I)
    if desc_match:
        fields['cargo_description'] = desc_match.group(1).strip()[:200]

    # Freight class
    class_match = re.search(r'(?:CLASS|FREIGHT CLASS)[:\s]*([\d]+(?:\.\d+)?)', text, re.I)
    if class_match:
        fields['freight_class'] = class_match.group(1)

    return fields


def process_ocr_upload(file_path: str, filename: str) -> dict:
    """Process uploaded file: extract text, parse fields, save job."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.pdf':
        text = extract_text_from_pdf(file_path)
    else:
        text = extract_text_from_image(file_path)

    fields = parse_bol_fields(text) if text and not text.startswith(('OCR_ERROR', 'PDF_ERROR')) else {}

    status = 'Extracted' if fields else ('Failed' if not text else 'Extracted')
    error = text if text.startswith(('OCR_ERROR', 'PDF_ERROR')) else ''

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO ocr_jobs (filename, file_path, raw_text, extracted_data, status, error) VALUES (?,?,?,?,?,?)",
            (filename, file_path, text[:5000], json.dumps(fields), status, error)
        )
        conn.commit()
        return {"job_id": cur.lastrowid, "fields": fields, "status": status, "raw_text": text[:2000]}
    finally:
        conn.close()


def get_ocr_job(job_id: int) -> dict:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM ocr_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return {}
        r = dict(row)
        r['extracted_data'] = json.loads(r.get('extracted_data', '{}'))
        return r
    finally:
        conn.close()


def mark_ocr_applied(job_id: int, shipment_ref: str):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE ocr_jobs SET status='Applied', shipment_ref=? WHERE id=?",
            (shipment_ref, job_id)
        )
        conn.commit()
    finally:
        conn.close()


def get_ocr_history():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM ocr_jobs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
