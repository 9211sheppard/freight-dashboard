"""
rate_limiter.py  —  Simple in-memory rate limiter for registration and API endpoints

No external dependencies. Uses a sliding window counter per IP address.
Designed for Azure App Service (single instance). For multi-instance,
switch to Redis-based limiter.
"""

import time
import threading
from collections import defaultdict


class RateLimiter:
    """Sliding window rate limiter.

    Usage:
        limiter = RateLimiter(max_requests=5, window_seconds=3600)
        if not limiter.allow(ip_address):
            return "Too many requests", 429
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = defaultdict(list)  # ip → [timestamp, ...]
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Check if a request from this key (usually IP) is allowed."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            # Clean old entries
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]

            # Check limit
            if len(self._requests[key]) >= self.max_requests:
                return False

            # Record this request
            self._requests[key].append(now)
            return True

    def remaining(self, key: str) -> int:
        """How many requests remain for this key."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]
            return max(0, self.max_requests - len(self._requests[key]))

    def cleanup(self):
        """Remove expired entries to prevent memory growth."""
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._requests.items()
                       if not v or max(v) < now - self.window_seconds]
            for k in expired:
                del self._requests[k]


# Pre-configured limiters for common use cases
registration_limiter = RateLimiter(max_requests=5, window_seconds=3600)    # 5 signups/hour/IP
login_limiter = RateLimiter(max_requests=10, window_seconds=300)           # 10 attempts/5min/IP
api_limiter = RateLimiter(max_requests=100, window_seconds=60)             # 100 calls/min/IP
spin_limiter = RateLimiter(max_requests=3, window_seconds=86400)           # 3 spins/day/IP


# ── Simple Math CAPTCHA (no external service needed) ─────────────────────────

import random
import hashlib


def generate_captcha() -> dict:
    """Generate a simple math captcha.
    Returns {"question": "What is 7 + 3?", "answer_hash": "sha256...", "token": "..."}
    The answer_hash is stored in the form; the user submits their answer; we hash and compare.
    """
    a = random.randint(2, 15)
    b = random.randint(2, 15)
    op = random.choice(["+", "+", "+", "-"])  # bias toward addition (easier)
    if op == "-" and b > a:
        a, b = b, a  # avoid negative answers

    answer = a + b if op == "+" else a - b
    question = f"What is {a} {op} {b}?"

    # Hash the answer with a salt so it can't be trivially reversed
    salt = str(random.randint(10000, 99999))
    answer_hash = hashlib.sha256(f"{answer}:{salt}".encode()).hexdigest()

    return {
        "question": question,
        "answer_hash": answer_hash,
        "salt": salt,
    }


def verify_captcha(user_answer: str, answer_hash: str, salt: str) -> bool:
    """Verify the user's captcha answer against the stored hash."""
    try:
        user_answer = user_answer.strip()
        check_hash = hashlib.sha256(f"{user_answer}:{salt}".encode()).hexdigest()
        return check_hash == answer_hash
    except Exception:
        return False
