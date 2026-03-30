import io
import os
import re
from datetime import datetime
from pathlib import Path

import fitz
import pdfplumber
from werkzeug.utils import secure_filename

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None
    ImageOps = None

try:
    import pytesseract
except ImportError:
    pytesseract = None


INTAKE_FIELD_ORDER = (
    "shipper",
    "consignee",
    "origin",
    "destination",
    "cargo_description",
    "weight",
    "containers",
    "etd",
    "eta",
    "incoterm",
    "currency",
    "rate",
)

_PARTY_LABELS = {
    "shipper": ("shipper", "ship from", "shipper name", "exporter", "seller"),
    "consignee": ("consignee", "ship to", "delivery to", "consignee name", "importer", "buyer"),
}
_LOCATION_LABELS = {
    "origin": ("origin", "origin port", "port of loading", "pol", "pickup", "pick up"),
    "destination": ("destination", "destination port", "port of discharge", "pod", "delivery", "final destination"),
}
_CARGO_LABELS = ("cargo description", "cargo", "commodity", "goods", "description", "product")
_WEIGHT_LABELS = ("weight", "gross weight", "net weight", "cargo weight")
_CONTAINER_LABELS = ("containers", "container", "equipment", "equipment type", "container size", "equipment size")
_RATE_LABELS = ("rate", "freight rate", "quoted rate", "quote", "offer", "price", "all in", "all-in")
_CURRENCY_LABELS = ("currency",)
_ETD_LABELS = ("etd", "departure", "departure date", "sailing date")
_ETA_LABELS = ("eta", "arrival", "arrival date", "delivery date")
_INCOTERM_LABELS = ("incoterm", "incoterms", "terms")
_STOP_LABEL_WORDS = {
    *[value.upper() for values in _PARTY_LABELS.values() for value in values],
    *[value.upper() for values in _LOCATION_LABELS.values() for value in values],
    *[value.upper() for value in _CARGO_LABELS],
    *[value.upper() for value in _WEIGHT_LABELS],
    *[value.upper() for value in _CONTAINER_LABELS],
    *[value.upper() for value in _RATE_LABELS],
    *[value.upper() for value in _CURRENCY_LABELS],
    *[value.upper() for value in _ETD_LABELS],
    *[value.upper() for value in _ETA_LABELS],
    *[value.upper() for value in _INCOTERM_LABELS],
}
_INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")
_CURRENCY_CODES = ("USD", "CAD", "EUR", "GBP", "AUD", "NZD", "SGD", "CNY", "JPY", "MXN", "INR")
_SYMBOL_TO_CURRENCY = {
    "US$": "USD",
    "USD$": "USD",
    "C$": "CAD",
    "CA$": "CAD",
    "A$": "AUD",
    "EUR": "EUR",
    "€": "EUR",
    "£": "GBP",
}
_WEIGHT_PATTERN = re.compile(
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>kg|kgs|kilograms?|lb|lbs|pounds?|mt|metric tons?|tonnes?)\b",
    re.IGNORECASE,
)
_CONTAINER_PATTERNS = (
    re.compile(r"\b\d+\s*(?:x|X)\s*\d{2}\s*(?:HC|HQ|GP|DV|RF)\b"),
    re.compile(r"\b\d{2}\s*(?:HC|HQ|GP|DV|RF)\b"),
    re.compile(r"\b53'?\s*(?:Dry Van|Reefer)\b", re.IGNORECASE),
    re.compile(r"\b(?:FCL|LCL|Pallets?)\b", re.IGNORECASE),
)
_DATE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{4}/\d{2}/\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{4}\b", re.IGNORECASE),
)


def extract_intake_payload(*, email_text="", uploaded_file=None):
    warnings = []
    source_kind = ""
    source_name = ""
    raw_text = ""

    if uploaded_file and getattr(uploaded_file, "filename", ""):
        source_name = secure_filename((uploaded_file.filename or "").strip()) or "order.pdf"
        if Path(source_name).suffix.lower() != ".pdf":
            raise ValueError("Upload a PDF for document intake, or paste email text.")
        blob = uploaded_file.read()
        if not blob:
            raise ValueError("The uploaded PDF is empty.")
        raw_text, extraction_warnings = _extract_pdf_text(blob)
        warnings.extend(extraction_warnings)
        source_kind = "pdf"
    else:
        raw_text = email_text or ""
        source_name = "Email text"
        source_kind = "email_text"

    normalized_text = _normalize_text_block(raw_text)
    if not _has_meaningful_text(normalized_text):
        raise ValueError("No readable order details were found in the provided email text or PDF.")

    fields, field_warnings = extract_intake_fields(normalized_text)
    warnings.extend(field_warnings)
    confidence = _overall_confidence(fields)

    return {
        "source_kind": source_kind,
        "source_name": source_name,
        "text_excerpt": normalized_text[:4000],
        "warnings": warnings,
        "fields": fields,
        "confidence": confidence,
        "reviewed_at": "",
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }, normalized_text


def extract_intake_fields(text):
    warnings = []
    route_pair = _extract_route_pair(text)
    rate_field, rate_currency_field = _extract_rate_and_currency(text)
    explicit_currency_field = _extract_currency(text)
    currency_field = _best_candidate(explicit_currency_field, rate_currency_field)

    etd_field, etd_warning = _extract_date_field(text, _ETD_LABELS)
    eta_field, eta_warning = _extract_date_field(text, _ETA_LABELS)
    if etd_warning:
        warnings.append(etd_warning)
    if eta_warning:
        warnings.append(eta_warning)

    fields = {
        "shipper": _extract_named_field(text, _PARTY_LABELS["shipper"]),
        "consignee": _extract_named_field(text, _PARTY_LABELS["consignee"]),
        "origin": _best_candidate(_extract_named_field(text, _LOCATION_LABELS["origin"]), route_pair["origin"]),
        "destination": _best_candidate(_extract_named_field(text, _LOCATION_LABELS["destination"]), route_pair["destination"]),
        "cargo_description": _extract_cargo_description(text),
        "weight": _extract_weight(text),
        "containers": _extract_containers(text),
        "etd": etd_field,
        "eta": eta_field,
        "incoterm": _extract_incoterm(text),
        "currency": currency_field,
        "rate": rate_field,
    }
    return fields, warnings


def _extract_pdf_text(blob):
    warnings = []

    text = _extract_pdf_text_with_pdfplumber(blob)
    if _has_meaningful_text(text):
        return text, warnings

    fitz_text = _extract_pdf_text_with_fitz(blob)
    if _has_meaningful_text(fitz_text):
        warnings.append("Used PyMuPDF fallback for PDF text extraction.")
        return fitz_text, warnings

    if pytesseract is not None and Image is not None and ImageOps is not None:
        try:
            ocr_text = _extract_pdf_text_with_ocr(blob)
        except Exception as exc:
            warnings.append(f"OCR fallback failed: {exc}")
        else:
            if _has_meaningful_text(ocr_text):
                warnings.append("Used OCR fallback for scanned PDF extraction.")
                return ocr_text, warnings

    raise ValueError("No readable text was extracted from the uploaded PDF.")


def _extract_pdf_text_with_pdfplumber(blob):
    pages = []
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text)
    return "\n\n".join(pages)


def _extract_pdf_text_with_fitz(blob):
    pages = []
    with fitz.open(stream=blob, filetype="pdf") as document:
        for page in document:
            page_text = page.get_text("text") or ""
            if page_text.strip():
                pages.append(page_text)
    return "\n\n".join(pages)


def _extract_pdf_text_with_ocr(blob):
    _configure_tesseract()
    chunks = []
    with fitz.open(stream=blob, filetype="pdf") as document:
        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            image.load()
            chunks.append(_ocr_pil_image(image))
    return "\n\n".join(chunks)


def _ocr_pil_image(image):
    prepared = ImageOps.exif_transpose(image)
    if prepared.mode not in {"RGB", "L"}:
        prepared = prepared.convert("RGB")
    prepared = ImageOps.grayscale(prepared)
    prepared = ImageOps.autocontrast(prepared)
    return pytesseract.image_to_string(prepared, config="--psm 6")


def _configure_tesseract():
    for candidate in (
        os.getenv("TESSERACT_CMD", "").strip(),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe"),
    ):
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return
    raise ValueError("Tesseract OCR executable was not found on this machine.")


def _extract_named_field(text, labels):
    return _extract_labeled_field(text, labels, base_confidence=96, continuation_confidence=90)


def _extract_cargo_description(text):
    return _best_candidate(
        _extract_labeled_field(text, _CARGO_LABELS, base_confidence=95, continuation_confidence=88),
        _extract_line_match(text, re.compile(r"\b(?:commodity|cargo)\b\s*(?:is|:|-)\s*(.+)", re.IGNORECASE), 78),
    )


def _extract_weight(text):
    labeled = _extract_labeled_field(
        text,
        _WEIGHT_LABELS,
        base_confidence=94,
        continuation_confidence=86,
        cleaner=_extract_weight_expression,
    )
    fallback = _extract_first_pattern(text, _WEIGHT_PATTERN, 72)
    return _best_candidate(labeled, fallback)


def _extract_containers(text):
    labeled = _extract_labeled_field(
        text,
        _CONTAINER_LABELS,
        base_confidence=94,
        continuation_confidence=86,
        cleaner=_extract_container_expression,
    )
    fallback = None
    for pattern in _CONTAINER_PATTERNS:
        fallback = _extract_first_pattern(text, pattern, 72)
        if fallback["value"]:
            break
    return _best_candidate(labeled, fallback or _blank_field())


def _extract_incoterm(text):
    labeled = _extract_labeled_field(
        text,
        _INCOTERM_LABELS,
        base_confidence=94,
        continuation_confidence=88,
        cleaner=_extract_incoterm_value,
    )
    standalone = _extract_line_match(
        text,
        re.compile(r"\b(" + "|".join(_INCOTERMS) + r")\b"),
        68,
        cleaner=lambda value: value.upper(),
    )
    return _best_candidate(labeled, standalone)


def _extract_currency(text):
    labeled = _extract_labeled_field(
        text,
        _CURRENCY_LABELS,
        base_confidence=94,
        continuation_confidence=88,
        cleaner=_extract_currency_value,
    )
    standalone = _extract_line_match(
        text,
        re.compile(r"\b(" + "|".join(_CURRENCY_CODES) + r")\b"),
        60,
        cleaner=lambda value: value.upper(),
    )
    return _best_candidate(labeled, standalone)


def _extract_rate_and_currency(text):
    lines = _text_lines(text)
    best_rate = _blank_field()
    best_currency = _blank_field()
    for line in lines:
        if not any(label in line.lower() for label in _RATE_LABELS):
            continue
        money = _extract_money_from_text(line)
        if money["amount"]:
            rate_confidence = 95 if money["currency"] else 88
            candidate = _candidate(money["amount"], rate_confidence, line)
            best_rate = _best_candidate(best_rate, candidate)
            if money["currency"]:
                best_currency = _best_candidate(best_currency, _candidate(money["currency"], rate_confidence, line))
        else:
            numeric_match = re.search(r"(\d[\d,]*(?:\.\d{1,2})?)", line)
            if numeric_match:
                best_rate = _best_candidate(best_rate, _candidate(_normalize_number_string(numeric_match.group(1)), 76, line))

    if best_rate["value"]:
        return best_rate, best_currency

    for line in lines:
        money = _extract_money_from_text(line)
        if not money["amount"] or not money["currency"]:
            continue
        return _candidate(money["amount"], 70, line), _candidate(money["currency"], 70, line)
    return _blank_field(), _blank_field()


def _extract_date_field(text, labels):
    lines = _text_lines(text)
    for index, line in enumerate(lines):
        if not any(re.search(rf"\b{re.escape(label)}\b", line, re.IGNORECASE) for label in labels):
            continue
        value = _value_after_labels(line, labels)
        parsed, warning = _parse_date_value(value)
        if parsed:
            return _candidate(parsed, 95, line), warning
        for continuation in lines[index + 1:index + 3]:
            if _looks_like_new_label(continuation):
                break
            parsed, warning = _parse_date_value(continuation)
            if parsed:
                return _candidate(parsed, 88, continuation), warning
    return _blank_field(), ""


def _extract_route_pair(text):
    lines = _text_lines(text)
    for line in lines:
        match = re.search(r"\bfrom\s+(?P<origin>.+?)\s+to\s+(?P<destination>.+)", line, re.IGNORECASE)
        if not match:
            match = re.search(r"\broute\b\s*[:#-]?\s*(?P<origin>.+?)\s+(?:to|->)\s+(?P<destination>.+)", line, re.IGNORECASE)
        if not match:
            continue
        origin = _clean_value(match.group("origin"))
        destination = _clean_value(match.group("destination"))
        if origin and destination:
            return {
                "origin": _candidate(origin, 74, line),
                "destination": _candidate(destination, 74, line),
            }
    return {"origin": _blank_field(), "destination": _blank_field()}


def _extract_labeled_field(text, labels, *, base_confidence, continuation_confidence, cleaner=None):
    lines = _text_lines(text)
    for index, line in enumerate(lines):
        value = _value_after_labels(line, labels)
        if value is None:
            continue
        cleaned_value = cleaner(value) if cleaner else _clean_value(value)
        if cleaned_value:
            return _candidate(cleaned_value, base_confidence, line)

        continuation_parts = []
        for continuation in lines[index + 1:index + 3]:
            if _looks_like_new_label(continuation):
                break
            continuation_parts.append(continuation.strip())
        if continuation_parts:
            continuation_value = cleaner(" ".join(continuation_parts)) if cleaner else _clean_value(" ".join(continuation_parts))
            if continuation_value:
                return _candidate(continuation_value, continuation_confidence, " ".join(continuation_parts))
    return _blank_field()


def _extract_line_match(text, pattern, confidence, cleaner=None):
    for line in _text_lines(text):
        match = pattern.search(line)
        if not match:
            continue
        raw_value = match.group(1).strip() if match.groups() else match.group(0).strip()
        value = cleaner(raw_value) if cleaner else _clean_value(raw_value)
        if value:
            return _candidate(value, confidence, line)
    return _blank_field()


def _extract_first_pattern(text, pattern, confidence):
    for line in _text_lines(text):
        match = pattern.search(line)
        if not match:
            continue
        value = _clean_value(match.group(0))
        if value:
            return _candidate(value, confidence, line)
    return _blank_field()


def _extract_weight_expression(value):
    match = _WEIGHT_PATTERN.search(value or "")
    if match:
        return _clean_value(match.group(0))
    numeric_match = re.search(r"(\d[\d,]*(?:\.\d+)?)", value or "")
    if numeric_match:
        return _normalize_number_string(numeric_match.group(1))
    return _clean_value(value)


def _extract_container_expression(value):
    for pattern in _CONTAINER_PATTERNS:
        match = pattern.search(value or "")
        if match:
            return _clean_value(match.group(0))
    return _clean_value(value)


def _extract_incoterm_value(value):
    match = re.search(r"\b(" + "|".join(_INCOTERMS) + r")\b", value or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _extract_currency_value(value):
    money = _extract_money_from_text(value or "")
    if money["currency"]:
        return money["currency"]
    match = re.search(r"\b(" + "|".join(_CURRENCY_CODES) + r")\b", value or "", re.IGNORECASE)
    return match.group(1).upper() if match else ""


def _extract_money_from_text(value):
    for pattern in (
        re.compile(r"\b(?P<currency>" + "|".join(_CURRENCY_CODES) + r")\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\b", re.IGNORECASE),
        re.compile(r"(?P<symbol>US\$|USD\$|C\$|CA\$|A\$|€|£)\s*(?P<amount>\d[\d,]*(?:\.\d{1,2})?)", re.IGNORECASE),
        re.compile(r"\b(?P<amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<currency>" + "|".join(_CURRENCY_CODES) + r")\b", re.IGNORECASE),
    ):
        match = pattern.search(value or "")
        if not match:
            continue
        currency = match.groupdict().get("currency") or _SYMBOL_TO_CURRENCY.get((match.groupdict().get("symbol") or "").upper(), "")
        amount = _normalize_number_string(match.group("amount"))
        if amount:
            return {"amount": amount, "currency": currency.upper() if currency else ""}
    return {"amount": "", "currency": ""}


def _parse_date_value(value):
    raw_value = _clean_value(value)
    if not raw_value:
        return "", ""

    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw_value)
        if not match:
            continue
        raw_date = match.group(0)
        parsed = _coerce_date(raw_date)
        if parsed:
            return parsed, ""
        if "/" in raw_date:
            return "", f"Skipped ambiguous date '{raw_date}'. Review ETD/ETA manually."
    return "", ""


def _coerce_date(raw_date):
    raw_value = (raw_date or "").strip()
    if not raw_value:
        return ""

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw_value, fmt).date().isoformat()
        except ValueError:
            continue

    if "/" in raw_value:
        first, second, year = raw_value.split("/")
        try:
            first_number = int(first)
            second_number = int(second)
        except ValueError:
            return ""
        if first_number > 12:
            fmt = "%d/%m/%Y" if len(year) == 4 else "%d/%m/%y"
        elif second_number > 12:
            fmt = "%m/%d/%Y" if len(year) == 4 else "%m/%d/%y"
        else:
            return ""
        try:
            return datetime.strptime(raw_value, fmt).date().isoformat()
        except ValueError:
            return ""
    return ""


def _value_after_labels(line, labels):
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\b\s*[:#-]?\s*(.*)", line, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _blank_field():
    return {"value": "", "confidence": 0, "source": ""}


def _candidate(value, confidence, source):
    return {
        "value": _clean_value(value),
        "confidence": int(max(min(confidence, 100), 0)),
        "source": _clean_value(source)[:200],
    }


def _best_candidate(*candidates):
    valid = [candidate for candidate in candidates if candidate and candidate.get("value")]
    if not valid:
        return _blank_field()
    return max(valid, key=lambda candidate: (candidate.get("confidence", 0), len(candidate.get("value", ""))))


def _overall_confidence(fields):
    scores = [field.get("confidence", 0) for field in (fields or {}).values() if field.get("value")]
    return int(round(sum(scores) / len(scores))) if scores else 0


def _normalize_number_string(value):
    raw = re.sub(r"[,\s]", "", value or "")
    if not raw:
        return ""
    try:
        number = float(raw)
    except ValueError:
        return ""
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _clean_value(value):
    cleaned = re.sub(r"\s+", " ", (value or "")).strip(" \t\r\n:-")
    return cleaned[:250]


def _text_lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _looks_like_new_label(value):
    upper_value = _clean_value(value).upper()
    if not upper_value:
        return False
    if any(upper_value.startswith(stop_word) for stop_word in _STOP_LABEL_WORDS):
        return True
    return bool(re.match(r"^[A-Z][A-Z /]{2,20}\s*[:#-]", upper_value))


def _normalize_text_block(text):
    lines = []
    for raw_line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _has_meaningful_text(text):
    return len(re.sub(r"[^A-Za-z0-9]", "", text or "")) >= 20
