import io
import os
import re
import shutil
from pathlib import Path

import fitz
import pdfplumber
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

try:
    import pytesseract
except ImportError:
    pytesseract = None


DOCUMENT_TYPE_CHOICES = ("Unknown", "BOL", "Invoice", "PackingList", "Customs")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}
_FIELD_LABELS = {
    "shipper": ("SHIPPER", "SHIP FROM", "EXPORTER", "SELLER"),
    "consignee": ("CONSIGNEE", "SHIP TO", "IMPORTER", "BUYER"),
    "origin": ("ORIGIN", "PORT OF LOADING", "PLACE OF RECEIPT", "POL"),
    "destination": ("DESTINATION", "FINAL DESTINATION", "PORT OF DISCHARGE", "POD"),
}
_LABEL_STOP_WORDS = {
    "SHIPPER",
    "SHIP FROM",
    "EXPORTER",
    "SELLER",
    "CONSIGNEE",
    "SHIP TO",
    "IMPORTER",
    "BUYER",
    "ORIGIN",
    "DESTINATION",
    "PORT OF LOADING",
    "PORT OF DISCHARGE",
    "FINAL DESTINATION",
    "AMOUNT",
    "TOTAL",
    "DATE",
    "INVOICE",
    "REFERENCE",
    "SHIPMENT",
    "DESCRIPTION",
    "CUSTOMS",
    "BROKER",
}
_DOC_TYPE_KEYWORDS = {
    "BOL": (
        "BILL OF LADING",
        "STRAIGHT BILL OF LADING",
        "B/L",
        "NOTIFY PARTY",
        "PORT OF LOADING",
        "PORT OF DISCHARGE",
    ),
    "Invoice": (
        "COMMERCIAL INVOICE",
        "INVOICE",
        "AMOUNT DUE",
        "INVOICE TOTAL",
        "TOTAL VALUE",
        "BILL TO",
    ),
    "PackingList": (
        "PACKING LIST",
        "PACKING SLIP",
        "TOTAL CARTONS",
        "NET WEIGHT",
        "GROSS WEIGHT",
        "PACKAGE COUNT",
    ),
    "Customs": (
        "CUSTOMS",
        "ENTRY NUMBER",
        "HS CODE",
        "IMPORTER OF RECORD",
        "CUSTOMS BROKER",
        "DECLARATION",
    ),
}


def extract_document_payload(uploaded_file, known_shipment_refs=None, preferred_shipment_ref=""):
    filename = secure_filename((getattr(uploaded_file, "filename", "") or "").strip()) or "document"
    blob = uploaded_file.read()
    if not blob:
        raise ValueError("The uploaded document is empty.")

    extracted_text, extraction_method, warnings = _extract_text(blob, filename)
    normalized_text = _normalize_text_block(extracted_text)
    if not _has_meaningful_text(normalized_text):
        raise ValueError("No readable text was extracted from the uploaded document.")

    fields = extract_key_fields(
        normalized_text,
        known_shipment_refs=known_shipment_refs or [],
        preferred_shipment_ref=preferred_shipment_ref,
    )
    return {
        "filename": filename,
        "doc_type": detect_document_type(normalized_text),
        "extraction_method": extraction_method,
        "warnings": warnings,
        "text_excerpt": normalized_text[:2000],
        "fields": fields,
    }


def detect_document_type(text):
    upper_text = (text or "").upper()
    best_type = "Unknown"
    best_score = 0
    for doc_type, keywords in _DOC_TYPE_KEYWORDS.items():
        score = sum(2 if keyword in upper_text else 0 for keyword in keywords)
        if score > best_score:
            best_type = doc_type
            best_score = score
    return best_type if best_score else "Unknown"


def extract_key_fields(text, known_shipment_refs=None, preferred_shipment_ref=""):
    shipment_ref = _extract_shipment_ref(text, known_shipment_refs or [])
    if not shipment_ref and preferred_shipment_ref:
        shipment_ref = preferred_shipment_ref.strip()

    dates = _extract_dates(text)
    return {
        "shipment_ref": shipment_ref or "",
        "shipper": _extract_labeled_value(text, _FIELD_LABELS["shipper"]),
        "consignee": _extract_labeled_value(text, _FIELD_LABELS["consignee"]),
        "origin": _extract_labeled_value(text, _FIELD_LABELS["origin"]),
        "destination": _extract_labeled_value(text, _FIELD_LABELS["destination"]),
        "amount": _extract_amount(text),
        "dates": ", ".join(dates[:6]),
    }


def _extract_text(blob, filename):
    suffix = Path(filename).suffix.lower()
    warnings = []

    if suffix == ".pdf":
        ocr_error = None
        ocr_text = ""
        try:
            ocr_text = _ocr_pdf(blob)
        except Exception as exc:
            ocr_error = exc

        if _has_meaningful_text(ocr_text):
            return ocr_text, "pytesseract", warnings

        fallback_text = _extract_pdf_text_with_pdfplumber(blob)
        if _has_meaningful_text(fallback_text):
            warnings.append("Used pdfplumber fallback for PDF extraction.")
            if ocr_error:
                warnings.append(str(ocr_error))
            return fallback_text, "pdfplumber", warnings

        if ocr_error:
            raise ValueError(f"Unable to extract text from PDF. {ocr_error}")
        raise ValueError("Unable to extract text from the uploaded PDF.")

    if suffix in _IMAGE_SUFFIXES:
        return _ocr_image(blob), "pytesseract", warnings

    raise ValueError("Unsupported file type. Upload a PDF or common image format.")


def _extract_pdf_text_with_pdfplumber(blob):
    pages = []
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text)
    return "\n\n".join(pages)


def _ocr_pdf(blob):
    _configure_tesseract()
    chunks = []
    with fitz.open(stream=blob, filetype="pdf") as document:
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            image.load()
            chunks.append(_ocr_pil_image(image))
    return "\n\n".join(chunks)


def _ocr_image(blob):
    _configure_tesseract()
    image = Image.open(io.BytesIO(blob))
    image.load()
    return _ocr_pil_image(image)


def _ocr_pil_image(image):
    prepared = ImageOps.exif_transpose(image)
    if prepared.mode not in {"RGB", "L"}:
        prepared = prepared.convert("RGB")
    prepared = ImageOps.grayscale(prepared)
    prepared = ImageOps.autocontrast(prepared)
    return pytesseract.image_to_string(prepared, config="--psm 6")


def _configure_tesseract():
    if pytesseract is None:
        raise ValueError("pytesseract is not installed. Install it before using OCR uploads.")

    for candidate in _tesseract_candidates():
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return candidate

    raise ValueError("Tesseract OCR executable was not found on this machine.")


def _tesseract_candidates():
    local_appdata = os.getenv("LOCALAPPDATA", "")
    return [
        os.getenv("TESSERACT_CMD", "").strip(),
        shutil.which("tesseract") or "",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(local_appdata, "Programs", "Tesseract-OCR", "tesseract.exe"),
    ]


def _has_meaningful_text(text):
    return len(re.sub(r"[^A-Za-z0-9]", "", text or "")) >= 20


def _normalize_text_block(text):
    lines = []
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _extract_shipment_ref(text, known_shipment_refs):
    upper_text = (text or "").upper()
    for reference in sorted({ref for ref in known_shipment_refs if ref}, key=len, reverse=True):
        if reference.upper() in upper_text:
            return reference

    patterns = [
        r"(?:SHIPMENT(?: REF(?:ERENCE)?)?|REFERENCE(?: NUMBER)?|BOOKING(?: NUMBER| NO)?|LOAD(?: NUMBER| NO)?|REF)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-\/]{3,})",
        r"(?:BOL(?: NUMBER| NO)?|INVOICE(?: NUMBER| NO)?)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-\/]{3,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _extract_labeled_value(text, labels):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        for label in labels:
            match = re.search(rf"\b{re.escape(label)}\b\s*[:#-]?\s*(.*)", line, re.IGNORECASE)
            if not match:
                continue

            value = _clean_captured_value(match.group(1))
            if value:
                return value

            continuation = []
            for next_line in lines[index + 1:index + 3]:
                if _looks_like_label(next_line):
                    break
                continuation.append(next_line.strip())
            if continuation:
                return _clean_captured_value(" ".join(continuation))
    return ""


def _extract_amount(text):
    patterns = [
        r"(?:INVOICE TOTAL|TOTAL VALUE|TOTAL AMOUNT|AMOUNT DUE|BALANCE DUE|TOTAL DUE)\s*[:#-]?\s*([A-Z]{3}\s*[\d,]+(?:\.\d+)?|[$€£]\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*[A-Z]{3})",
        r"(?:AMOUNT|TOTAL)\s*[:#-]?\s*([A-Z]{3}\s*[\d,]+(?:\.\d+)?|[$€£]\s*[\d,]+(?:\.\d+)?|[\d,]+(?:\.\d+)?\s*[A-Z]{3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _extract_dates(text):
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
    ]

    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", re.IGNORECASE):
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            if value not in found:
                found.append(value)
    return found


def _looks_like_label(value):
    upper_value = (value or "").strip().upper()
    return any(upper_value.startswith(label) for label in _LABEL_STOP_WORDS)


def _clean_captured_value(value):
    cleaned = re.sub(r"\s+", " ", value or "").strip(" :#-")
    if not cleaned:
        return ""
    if _looks_like_label(cleaned):
        return ""
    return cleaned[:160]
