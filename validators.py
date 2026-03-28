"""
validators.py  —  Input validation, sanitization, password policy, breach detection, bot protection
"""

import hashlib
import re
import os
import urllib.request
import urllib.parse

# ── Common weak passwords (top 100) ──────────────────────────────────────────
_COMMON_PASSWORDS = frozenset([
    "password", "123456", "12345678", "qwerty", "abc123", "monkey", "1234567",
    "letmein", "trustno1", "dragon", "baseball", "iloveyou", "master", "sunshine",
    "ashley", "michael", "shadow", "123123", "654321", "superman", "qazwsx",
    "admin123", "admin", "password1", "password123", "welcome", "welcome1",
    "p@ssw0rd", "passw0rd", "football", "charlie", "donald", "login",
    "princess", "solo", "access", "flower", "hello", "jesus", "ninja",
    "mustang", "test", "test123", "love", "money", "starwars", "freedom",
    "whatever", "qwerty123", "1234", "123456789", "1234567890", "000000",
    "111111", "121212", "555555", "666666", "696969", "7777777", "888888",
    "abcdef", "abcabc", "changeme", "default", "guest", "pass", "pass123",
    "passwd", "root", "secret", "summer", "winter", "spring", "autumn",
    "zaq1zaq1", "qwer1234", "asdf1234", "1q2w3e4r", "1qaz2wsx", "zxcvbnm",
    "aaaaaa", "bailey", "bandit", "buster", "cookie", "ginger", "harley",
    "hunter", "killer", "lucky", "maggie", "max", "merlin", "pepper",
    "ranger", "robert", "sammy", "smokey", "sparky", "thomas", "tigger",
    "trustno1", "wizard", "jordan", "hockey", "soccer", "tennis", "computer",
    "internet", "george",
])


def validate_password(password: str, email: str = None) -> tuple:
    """Validate password strength. Returns (is_valid, error_message)."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if len(password) > 128:
        return False, "Password must be at most 128 characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
        return False, "Password must contain at least one special character."
    if password.lower() in _COMMON_PASSWORDS:
        return False, "This password is too common. Please choose a stronger one."
    if email:
        local = email.split("@")[0].lower()
        if len(local) >= 3 and local in password.lower():
            return False, "Password must not contain your email address."
    return True, ""


def check_password_breach(password: str) -> tuple:
    """Check password against HaveIBeenPwned using k-anonymity (only first 5 chars of SHA1 sent).
    Returns (is_breached, breach_count). Graceful fallback if API unavailable."""
    try:
        sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix = sha1[:5]
        suffix = sha1[5:]
        url = f"https://api.pwnedpasswords.com/range/{prefix}"
        req = urllib.request.Request(url, headers={"User-Agent": "FreightDashboard-SecurityCheck"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")
        for line in body.splitlines():
            parts = line.strip().split(":")
            if len(parts) == 2 and parts[0] == suffix:
                return True, int(parts[1])
        return False, 0
    except Exception:
        return False, 0  # Fail open — don't block if API is down


def verify_captcha(token: str) -> bool:
    """Verify hCaptcha token server-side. Returns True if valid or if hCaptcha is not configured."""
    try:
        from config import HCAPTCHA_SECRET_KEY
        if not HCAPTCHA_SECRET_KEY:
            return True  # Not configured — skip
        if not token:
            return False
        data = urllib.parse.urlencode({
            "secret": HCAPTCHA_SECRET_KEY,
            "response": token,
        }).encode()
        req = urllib.request.Request("https://hcaptcha.com/siteverify", data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            import json
            result = json.loads(resp.read())
            return result.get("success", False)
    except Exception:
        return True  # Fail open — don't block users if hCaptcha API is down


def sanitize_string(value: str, max_length: int = 255) -> str:
    """Strip whitespace, remove null bytes, and truncate to max_length."""
    if not isinstance(value, str):
        return ""
    return value.strip().replace("\x00", "")[:max_length]


def validate_email_format(email: str) -> bool:
    """Validate email format using a reasonable regex."""
    if not email or len(email) > 254:
        return False
    pattern = r'^[a-zA-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_filename(filename: str) -> str:
    """Remove path traversal characters and dangerous patterns from a filename."""
    if not filename:
        return "unnamed"
    # Remove directory separators and traversal
    name = os.path.basename(filename)
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    # Remove null bytes
    name = name.replace("\x00", "")
    # Only allow safe characters
    name = re.sub(r'[^\w\s.\-]', '_', name)
    if not name or name.startswith("."):
        name = "unnamed" + name
    return name[:200]
