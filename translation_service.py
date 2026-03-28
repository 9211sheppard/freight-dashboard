"""
translation_service.py — Language detection and translation for Flash Cargo Global

Strategy:
  1. If Azure Translator API credentials are available (TRANSLATOR_KEY env var),
     use Microsoft Azure Translator (free tier: 2M chars/month).
  2. Otherwise, fall back to deep-translator (Google Translate, no API key).
  3. Language detection uses a fast heuristic first (character-set based),
     then refines with API if available.
"""

import logging
import os
import re

log = logging.getLogger(__name__)

# ── Azure Translator config ──────────────────────────────────────────────────
TRANSLATOR_KEY = os.environ.get("TRANSLATOR_KEY", "")
TRANSLATOR_REGION = os.environ.get("TRANSLATOR_REGION", "eastus")
TRANSLATOR_ENDPOINT = os.environ.get(
    "TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com",
)

# ── Country → ISO 639-1 language code mapping ───────────────────────────────
_COUNTRY_TO_LANG = {
    "turkey":       "tr",
    "germany":      "de",
    "france":       "fr",
    "brazil":       "pt",
    "japan":        "ja",
    "china":        "zh-Hans",
    "south korea":  "ko",
    "india":        "hi",
    "spain":        "es",
    "italy":        "it",
    "portugal":     "pt-pt",
    "russia":       "ru",
    "mexico":       "es",
    "colombia":     "es",
    "argentina":    "es",
    "chile":        "es",
    "peru":         "es",
    "saudi arabia": "ar",
    "uae":          "ar",
    "indonesia":    "id",
    # Common extras
    "united states": "en",
    "usa":          "en",
    "uk":           "en",
    "canada":       "en",
    "australia":    "en",
    "netherlands":  "nl",
    "belgium":      "nl",
    "poland":       "pl",
    "thailand":     "th",
    "vietnam":      "vi",
    "egypt":        "ar",
    "greece":       "el",
    "czech republic": "cs",
    "sweden":       "sv",
    "norway":       "no",
    "denmark":      "da",
    "finland":      "fi",
}


def get_language_for_country(country: str) -> str:
    """Map country name to ISO 639-1 language code. Returns 'en' if unknown."""
    if not country:
        return "en"
    return _COUNTRY_TO_LANG.get(country.strip().lower(), "en")


# ── Character-set heuristic for language detection ───────────────────────────

# CJK Unified Ideographs
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
# Hiragana / Katakana
_JAPANESE_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")
# Hangul
_KOREAN_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")
# Arabic
_ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
# Cyrillic
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
# Devanagari (Hindi)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")
# Thai
_THAI_RE = re.compile(r"[\u0e00-\u0e7f]")


def _heuristic_detect(text: str) -> str | None:
    """Fast character-set heuristic. Returns ISO code or None."""
    if not text or len(text.strip()) < 3:
        return None

    # Count script characters
    if _JAPANESE_RE.search(text):
        return "ja"
    if _KOREAN_RE.search(text):
        return "ko"
    if _CJK_RE.search(text):
        return "zh-Hans"
    if _DEVANAGARI_RE.search(text):
        return "hi"
    if _ARABIC_RE.search(text):
        return "ar"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _THAI_RE.search(text):
        return "th"

    return None


def _azure_available() -> bool:
    return bool(TRANSLATOR_KEY)


def _azure_detect(text: str) -> str | None:
    """Detect language using Azure Translator API."""
    if not _azure_available():
        return None
    try:
        import requests
        url = f"{TRANSLATOR_ENDPOINT}/detect?api-version=3.0"
        headers = {
            "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
            "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, json=[{"Text": text[:500]}], timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and data[0].get("language"):
            return data[0]["language"]
    except Exception as exc:
        log.warning("Azure detect failed: %s", exc)
    return None


def _azure_translate(text: str, target_lang: str, source_lang: str | None = None) -> str | None:
    """Translate using Azure Translator API."""
    if not _azure_available():
        return None
    try:
        import requests
        params = {"api-version": "3.0", "to": target_lang}
        if source_lang:
            params["from"] = source_lang
        url = f"{TRANSLATOR_ENDPOINT}/translate"
        headers = {
            "Ocp-Apim-Subscription-Key": TRANSLATOR_KEY,
            "Ocp-Apim-Subscription-Region": TRANSLATOR_REGION,
            "Content-Type": "application/json",
        }
        resp = requests.post(url, headers=headers, params=params,
                             json=[{"Text": text}], timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data and data[0].get("translations"):
            return data[0]["translations"][0]["text"]
    except Exception as exc:
        log.warning("Azure translate failed: %s", exc)
    return None


def _deep_translate(text: str, source: str, target: str) -> str | None:
    """Translate using deep-translator (Google Translate, free, no API key)."""
    try:
        from deep_translator import GoogleTranslator
        # deep-translator uses 'auto' for auto-detect
        src = source if source and source != "auto" else "auto"
        result = GoogleTranslator(source=src, target=target).translate(text)
        return result
    except ImportError:
        log.error("deep-translator not installed — pip install deep-translator")
        return None
    except Exception as exc:
        log.warning("deep-translator failed: %s", exc)
        return None


# ── Public API ───────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """
    Detect the language of input text.

    Strategy:
      1. Character-set heuristic (instant, no API call)
      2. Azure Translator API if available
      3. deep-translator auto-detect as last resort
      4. Default to 'en' if all fail

    Returns ISO 639-1 language code.
    """
    if not text or not text.strip():
        return "en"

    # Step 1: heuristic
    heur = _heuristic_detect(text)
    if heur:
        return heur

    # Step 2: Azure
    azure_lang = _azure_detect(text)
    if azure_lang:
        return azure_lang

    # Step 3: deep-translator auto-detect
    try:
        from deep_translator import single_detection
        lang = single_detection(text[:200], api_key="")
        if lang:
            return lang
    except Exception:
        pass

    return "en"


def translate_to_english(text: str, source_lang: str | None = None) -> dict:
    """
    Translate text to English.

    Returns dict: {"translated": str, "source_lang": str, "target_lang": "en"}
    """
    if not text or not text.strip():
        return {"translated": text, "source_lang": source_lang or "en", "target_lang": "en"}

    src = source_lang or detect_language(text)
    if src == "en":
        return {"translated": text, "source_lang": "en", "target_lang": "en"}

    # Try Azure first
    result = _azure_translate(text, "en", source_lang=src)
    if result:
        return {"translated": result, "source_lang": src, "target_lang": "en"}

    # Fallback: deep-translator
    result = _deep_translate(text, src, "en")
    if result:
        return {"translated": result, "source_lang": src, "target_lang": "en"}

    return {"translated": text, "source_lang": src, "target_lang": "en",
            "error": "Translation failed — returned original text"}


def translate_from_english(text: str, target_lang: str) -> dict:
    """
    Translate English text to target language.

    Returns dict: {"translated": str, "source_lang": "en", "target_lang": str}
    """
    if not text or not text.strip():
        return {"translated": text, "source_lang": "en", "target_lang": target_lang}

    if target_lang == "en":
        return {"translated": text, "source_lang": "en", "target_lang": "en"}

    # Try Azure first
    result = _azure_translate(text, target_lang, source_lang="en")
    if result:
        return {"translated": result, "source_lang": "en", "target_lang": target_lang}

    # Fallback: deep-translator
    result = _deep_translate(text, "en", target_lang)
    if result:
        return {"translated": result, "source_lang": "en", "target_lang": target_lang}

    return {"translated": text, "source_lang": "en", "target_lang": target_lang,
            "error": "Translation failed — returned original text"}


def translate_text(text: str, target_lang: str, source_lang: str | None = None) -> dict:
    """
    General translation: any language → any language.

    Returns dict: {"translated": str, "source_lang": str, "target_lang": str}
    """
    if not text or not text.strip():
        return {"translated": text, "source_lang": source_lang or "en", "target_lang": target_lang}

    src = source_lang or detect_language(text)

    if src == target_lang:
        return {"translated": text, "source_lang": src, "target_lang": target_lang}

    if target_lang == "en":
        return translate_to_english(text, source_lang=src)

    if src == "en":
        return translate_from_english(text, target_lang)

    # Non-English → Non-English: pivot through English
    to_en = translate_to_english(text, source_lang=src)
    if to_en.get("error"):
        return {"translated": text, "source_lang": src, "target_lang": target_lang,
                "error": to_en["error"]}
    return translate_from_english(to_en["translated"], target_lang)
