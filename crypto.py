"""
crypto.py  —  Field-level encryption at rest using Fernet (AES-128-CBC + HMAC-SHA256)
Derives key from SECRET_KEY via PBKDF2.
"""

import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from config import SECRET_KEY

# ── Derive Fernet key from SECRET_KEY ─────────────────────────────────────────
_SALT = b"freight-intelligence-v1"  # Fixed salt — changing this invalidates all encrypted data

_kdf = PBKDF2HMAC(
    algorithm=hashes.SHA256(),
    length=32,
    salt=_SALT,
    iterations=480000,
)
_key = base64.urlsafe_b64encode(_kdf.derive(SECRET_KEY.encode()))
_fernet = Fernet(_key)


def encrypt_field(plaintext: str) -> str:
    """Encrypt a string field. Returns base64 ciphertext."""
    if not plaintext:
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext."""
    if not ciphertext:
        return ""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # If decryption fails, return empty — could be unencrypted legacy data
        return ""


def hash_token(token: str) -> str:
    """One-way hash for tokens like API keys (not reversible)."""
    return hashlib.sha256(token.encode()).hexdigest()
