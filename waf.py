"""
waf.py  —  WAF integration, DDoS protection, IP reputation, and abuse prevention
Pre-wired for Cloudflare, AWS ALB, and standalone deployment.
Set env vars to activate — zero-config when disabled.
"""

import time
import threading
from datetime import datetime, timedelta
from config import (
    BEHIND_PROXY, TRUSTED_PROXY_IPS, CLOUDFLARE_ENABLED,
    DDOS_RATE_LIMIT, DDOS_BAN_THRESHOLD, DDOS_BAN_DURATION_MIN,
)


# ── In-memory IP ban store ────────────────────────────────────────────────────
_ban_store = {}          # {ip: ban_expires_timestamp}
_request_counter = {}    # {ip: [timestamps]}
_ban_lock = threading.Lock()
_CLEANUP_COUNTER = 0


# ── Cloudflare header validation ─────────────────────────────────────────────
# Cloudflare IPs (IPv4) — update periodically from https://www.cloudflare.com/ips-v4
CLOUDFLARE_IP_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
]

_cf_networks = None


def _get_cf_networks():
    global _cf_networks
    if _cf_networks is None:
        import ipaddress
        _cf_networks = [ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_IP_RANGES]
    return _cf_networks


def is_cloudflare_ip(ip: str) -> bool:
    """Check if an IP belongs to Cloudflare's network."""
    try:
        import ipaddress
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _get_cf_networks())
    except Exception:
        return False


def get_real_ip(request) -> str:
    """Extract the real client IP, handling proxies and Cloudflare.
    Priority: CF-Connecting-IP > X-Real-IP > X-Forwarded-For > remote_addr"""
    if CLOUDFLARE_ENABLED:
        cf_ip = request.headers.get("CF-Connecting-IP", "")
        if cf_ip:
            # Verify the request actually came through Cloudflare
            proxy_ip = request.remote_addr or ""
            if is_cloudflare_ip(proxy_ip) or proxy_ip in TRUSTED_PROXY_IPS:
                return cf_ip.strip()

    if BEHIND_PROXY:
        # Trust X-Real-IP or X-Forwarded-For from trusted proxies
        proxy_ip = request.remote_addr or ""
        if proxy_ip in TRUSTED_PROXY_IPS:
            real_ip = request.headers.get("X-Real-IP", "")
            if real_ip:
                return real_ip.strip()
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip()

    return request.remote_addr or "unknown"


# ── DDoS / Abuse Protection ──────────────────────────────────────────────────

def is_ip_banned(ip: str) -> bool:
    """Check if an IP is currently banned."""
    with _ban_lock:
        if ip in _ban_store:
            if time.time() < _ban_store[ip]:
                return True
            else:
                del _ban_store[ip]
    return False


def ban_ip(ip: str, duration_minutes: int = None):
    """Manually ban an IP address."""
    duration = duration_minutes or DDOS_BAN_DURATION_MIN
    with _ban_lock:
        _ban_store[ip] = time.time() + (duration * 60)


def unban_ip(ip: str):
    """Remove an IP from the ban list."""
    with _ban_lock:
        _ban_store.pop(ip, None)


def check_ddos(ip: str) -> bool:
    """Check if an IP exceeds DDoS thresholds. Returns True if allowed, False if blocked.
    Auto-bans IPs that exceed DDOS_BAN_THRESHOLD."""
    global _CLEANUP_COUNTER
    now = time.time()

    # Periodic cleanup
    _CLEANUP_COUNTER += 1
    if _CLEANUP_COUNTER >= 1000:
        _CLEANUP_COUNTER = 0
        _cleanup_counters(now)

    if ip not in _request_counter:
        _request_counter[ip] = []

    # Purge entries older than 60 seconds
    _request_counter[ip] = [t for t in _request_counter[ip] if now - t < 60]
    count = len(_request_counter[ip])

    # Auto-ban check
    if count >= DDOS_BAN_THRESHOLD:
        ban_ip(ip)
        try:
            from audit import log_event
            log_event(None, None, "ip_auto_banned",
                      details=f"ip={ip}, requests_per_min={count}",
                      ip=ip)
        except Exception:
            pass
        return False

    # Rate limit check
    if count >= DDOS_RATE_LIMIT:
        return False

    _request_counter[ip].append(now)
    return True


def _cleanup_counters(now):
    """Remove stale entries from the request counter."""
    stale = [ip for ip, times in _request_counter.items()
             if not times or now - times[-1] > 120]
    for ip in stale:
        _request_counter.pop(ip, None)

    # Clean expired bans
    with _ban_lock:
        expired = [ip for ip, exp in _ban_store.items() if now >= exp]
        for ip in expired:
            del _ban_store[ip]


# ── Cloudflare WAF headers ───────────────────────────────────────────────────

def get_cloudflare_context(request) -> dict:
    """Extract Cloudflare security headers for logging/decisions."""
    if not CLOUDFLARE_ENABLED:
        return {}
    return {
        "cf_ray":           request.headers.get("CF-RAY", ""),
        "cf_country":       request.headers.get("CF-IPCountry", ""),
        "cf_threat_score":  request.headers.get("CF-Threat-Score", ""),
        "cf_bot_score":     request.headers.get("CF-Bot-Score", ""),
        "cf_waf_action":    request.headers.get("CF-WAF-Action", ""),
        "cf_connecting_ip": request.headers.get("CF-Connecting-IP", ""),
    }


def is_known_bot(request) -> bool:
    """Detect known bots via Cloudflare Bot Management or User-Agent heuristics."""
    if CLOUDFLARE_ENABLED:
        bot_score = request.headers.get("CF-Bot-Score", "")
        if bot_score:
            try:
                score = int(bot_score)
                return score < 30  # Score < 30 = likely bot
            except ValueError:
                pass

    # Fallback: basic UA-based bot detection
    ua = (request.headers.get("User-Agent", "") or "").lower()
    bot_indicators = [
        "bot", "crawler", "spider", "scraper", "curl", "wget",
        "python-requests", "httpclient", "java/", "go-http",
    ]
    # Allow legitimate bots for health checks
    if any(ind in ua for ind in bot_indicators):
        return True
    if not ua:  # No user agent = suspicious
        return True
    return False


# ── Admin API helpers ─────────────────────────────────────────────────────────

def get_banned_ips() -> list:
    """Return list of currently banned IPs with expiry times."""
    now = time.time()
    with _ban_lock:
        return [
            {"ip": ip, "expires_at": datetime.fromtimestamp(exp).isoformat(),
             "remaining_minutes": max(0, int((exp - now) / 60))}
            for ip, exp in _ban_store.items()
            if now < exp
        ]


def get_top_requesters(limit: int = 20) -> list:
    """Return IPs with highest request counts in the current window."""
    now = time.time()
    counts = []
    for ip, times in _request_counter.items():
        active = [t for t in times if now - t < 60]
        if active:
            counts.append({"ip": ip, "requests_per_min": len(active)})
    counts.sort(key=lambda x: x["requests_per_min"], reverse=True)
    return counts[:limit]
