"""
contact_engine.py — Contact Intelligence Engine
Handles: behavioral profiling, cultural lines, interest capture,
         live interest tracking, intelligence card generation,
         and timezone-aware email send optimization.
"""

import json
import logging
import random
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

from database import get_db

log = logging.getLogger(__name__)


# ── Country → IANA timezone mappings (all 73 countries from _COUNTRY_MOTTOS) ──
_COUNTRY_TIMEZONES = {
    # Europe
    "italy":            "Europe/Rome",
    "germany":          "Europe/Berlin",
    "france":           "Europe/Paris",
    "spain":            "Europe/Madrid",
    "netherlands":      "Europe/Amsterdam",
    "belgium":          "Europe/Brussels",
    "switzerland":      "Europe/Zurich",
    "austria":          "Europe/Vienna",
    "poland":           "Europe/Warsaw",
    "greece":           "Europe/Athens",
    "turkey":           "Europe/Istanbul",
    "portugal":         "Europe/Lisbon",
    "sweden":           "Europe/Stockholm",
    "denmark":          "Europe/Copenhagen",
    "norway":           "Europe/Oslo",
    "finland":          "Europe/Helsinki",
    "russia":           "Europe/Moscow",
    "ukraine":          "Europe/Kyiv",
    "czech republic":   "Europe/Prague",
    "romania":          "Europe/Bucharest",
    "ireland":          "Europe/Dublin",
    "united kingdom":   "Europe/London",
    "uk":               "Europe/London",
    "hungary":          "Europe/Budapest",
    "croatia":          "Europe/Zagreb",
    # Asia-Pacific
    "china":            "Asia/Shanghai",
    "hong kong":        "Asia/Hong_Kong",
    "taiwan":           "Asia/Taipei",
    "japan":            "Asia/Tokyo",
    "south korea":      "Asia/Seoul",
    "korea":            "Asia/Seoul",
    "india":            "Asia/Kolkata",
    "singapore":        "Asia/Singapore",
    "malaysia":         "Asia/Kuala_Lumpur",
    "indonesia":        "Asia/Jakarta",
    "thailand":         "Asia/Bangkok",
    "vietnam":          "Asia/Ho_Chi_Minh",
    "philippines":      "Asia/Manila",
    "australia":        "Australia/Sydney",
    "new zealand":      "Pacific/Auckland",
    "bangladesh":       "Asia/Dhaka",
    "pakistan":          "Asia/Karachi",
    "sri lanka":        "Asia/Colombo",
    # Americas
    "usa":              "America/New_York",
    "united states":    "America/New_York",
    "brazil":           "America/Sao_Paulo",
    "mexico":           "America/Mexico_City",
    "colombia":         "America/Bogota",
    "argentina":        "America/Argentina/Buenos_Aires",
    "chile":            "America/Santiago",
    "peru":             "America/Lima",
    "canada":           "America/Toronto",
    "ecuador":          "America/Guayaquil",
    "venezuela":        "America/Caracas",
    "costa rica":       "America/Costa_Rica",
    "panama":           "America/Panama",
    # Middle East / Africa
    "uae":              "Asia/Dubai",
    "united arab emirates": "Asia/Dubai",
    "saudi arabia":     "Asia/Riyadh",
    "qatar":            "Asia/Qatar",
    "kuwait":           "Asia/Kuwait",
    "bahrain":          "Asia/Bahrain",
    "oman":             "Asia/Muscat",
    "egypt":            "Africa/Cairo",
    "jordan":           "Asia/Amman",
    "lebanon":          "Asia/Beirut",
    "israel":           "Asia/Jerusalem",
    "south africa":     "Africa/Johannesburg",
    "nigeria":          "Africa/Lagos",
    "kenya":            "Africa/Nairobi",
    "ghana":            "Africa/Accra",
    "tanzania":         "Africa/Dar_es_Salaam",
    "morocco":          "Africa/Casablanca",
}

# ── Default send windows based on research ────────────────────────────────────
# Tue-Thu are optimal; Mon/Fri acceptable; Sat-Sun avoided
_DEFAULT_WINDOWS = {
    "morning":   (8, 10),   # 8:00-10:00 AM local — primary
    "afternoon": (13, 15),  # 1:00-3:00 PM local  — secondary
    "evening":   (20, 22),  # 8:00-10:00 PM local  — skeptical/ghost
}
_PREFERRED_DAYS = {1, 2, 3}       # Tue, Wed, Thu (0=Mon)
_ACCEPTABLE_DAYS = {0, 1, 2, 3, 4}  # Mon-Fri


def get_country_timezone(country: str) -> str:
    """Return IANA timezone string for a country, or UTC if not found."""
    if not country:
        return "UTC"
    return _COUNTRY_TIMEZONES.get(country.strip().lower(), "UTC")


def _utc_now() -> datetime:
    """Current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _to_local(utc_dt: datetime, tz_name: str) -> datetime:
    """Convert a UTC datetime to a local timezone."""
    tz = ZoneInfo(tz_name)
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(tz)


def _to_utc(local_dt: datetime, tz_name: str) -> datetime:
    """Convert a local datetime to UTC."""
    tz = ZoneInfo(tz_name)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


def _randomize_minutes(base_hour: int, base_min: int = 0, jitter: int = 15) -> tuple:
    """Add +-jitter minutes to a time. Returns (hour, minute)."""
    total_min = base_hour * 60 + base_min + random.randint(-jitter, jitter)
    total_min = max(0, min(total_min, 23 * 60 + 59))
    return divmod(total_min, 60)


def get_optimal_send_time(contact_id: int, country: str,
                          behavior_type: str = None) -> dict:
    """
    Calculate the best time to send an email to a specific contact.

    Returns dict with:
        send_at_utc, send_at_local, window, confidence, personality
    """
    tz_name = get_country_timezone(country)
    now_utc = _utc_now()
    now_local = _to_local(now_utc, tz_name)

    # ── Phase 2/3: check for individual data ──────────────────────────────
    profile = _get_timing_profile(contact_id)
    if profile and profile["total_interactions"] >= 3:
        # Phase 3: optimized — full profile
        return _optimized_send_time(profile, tz_name, now_utc)
    elif profile and profile["total_interactions"] >= 1:
        # Phase 2: learned — some individual data
        return _learned_send_time(profile, tz_name, now_utc)

    # ── Phase 1: research defaults ────────────────────────────────────────
    return _default_send_time(tz_name, now_utc, behavior_type)


def _get_timing_profile(contact_id: int) -> dict:
    """Fetch the contact_timing_profile for a contact, or None."""
    if not contact_id:
        return None
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM contact_timing_profile WHERE contact_id = ?",
            (contact_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return None
    except Exception:
        return None


def _default_send_time(tz_name: str, now_utc: datetime,
                       behavior_type: str = None) -> dict:
    """Phase 1: use research defaults — primary window Tue-Thu 8-10 AM local."""
    now_local = _to_local(now_utc, tz_name)

    # Pick window based on behavior
    if behavior_type in ("skeptical", "ghost"):
        window_name = "evening"
    else:
        window_name = "morning"

    win_start, win_end = _DEFAULT_WINDOWS[window_name]

    # Find next good day (prefer Tue-Thu)
    target_local = now_local.replace(second=0, microsecond=0)

    # If we're already past the window today, move to tomorrow
    if target_local.hour >= win_end:
        target_local += timedelta(days=1)

    # Advance to next preferred day if current day is weekend
    for _ in range(7):
        dow = target_local.weekday()
        if dow in _PREFERRED_DAYS:
            break
        if dow in _ACCEPTABLE_DAYS and _ > 0:
            break  # acceptable day after first skip
        target_local += timedelta(days=1)

    # Set hour within window with randomization
    base_hour = random.randint(win_start, win_end - 1)
    base_min = random.randint(0, 45)
    h, m = _randomize_minutes(base_hour, base_min, jitter=15)
    target_local = target_local.replace(hour=h, minute=m, second=0, microsecond=0)

    target_utc = _to_utc(target_local, tz_name)

    return {
        "send_at_utc": target_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "send_at_local": target_local.isoformat(),
        "window": window_name,
        "confidence": "default",
        "personality": "unknown",
    }


def _learned_send_time(profile: dict, tz_name: str,
                       now_utc: datetime) -> dict:
    """Phase 2: use individual reply patterns to pick send time."""
    now_local = _to_local(now_utc, tz_name)
    avg_hour = profile.get("avg_reply_hour_local") or 9.0
    preferred = profile.get("preferred_window") or "morning"
    personality = profile.get("personality_signal") or "unknown"

    # Build window around their reply hour — send 30-75 min before they typically reply
    lead_minutes = random.randint(30, 75)
    base_total_min = int(avg_hour * 60) - lead_minutes
    h, m = _randomize_minutes(base_total_min // 60, base_total_min % 60, jitter=20)

    # Clamp to reasonable hours (6 AM - 10 PM local)
    h = max(6, min(h, 22))

    target_local = now_local.replace(hour=h, minute=m, second=0, microsecond=0)

    # If we're past that time today, go to next acceptable day
    if target_local <= now_local:
        target_local += timedelta(days=1)

    # Advance past weekends
    for _ in range(7):
        if target_local.weekday() in _ACCEPTABLE_DAYS:
            break
        target_local += timedelta(days=1)

    target_utc = _to_utc(target_local, tz_name)

    return {
        "send_at_utc": target_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "send_at_local": target_local.isoformat(),
        "window": preferred,
        "confidence": "learned",
        "personality": personality,
    }


def _optimized_send_time(profile: dict, tz_name: str,
                         now_utc: datetime) -> dict:
    """Phase 3: fully optimized — use personality + optimal hours."""
    now_local = _to_local(now_utc, tz_name)
    personality = profile.get("personality_signal") or "unknown"
    optimal_hours_json = profile.get("optimal_send_hours") or "[]"

    try:
        optimal_hours = json.loads(optimal_hours_json)
    except (json.JSONDecodeError, TypeError):
        optimal_hours = []

    if optimal_hours:
        # Pick a random hour from the optimal list, with slight variation
        chosen_hour = random.choice(optimal_hours)
        h, m = _randomize_minutes(chosen_hour, random.randint(0, 30), jitter=20)
    else:
        # Fall back to personality-based defaults
        if personality == "early_riser":
            h, m = _randomize_minutes(7, 30, jitter=15)
        elif personality == "night_owl":
            h, m = _randomize_minutes(20, 0, jitter=20)
        else:
            h, m = _randomize_minutes(9, 15, jitter=15)

    h = max(6, min(h, 22))

    target_local = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    if target_local <= now_local:
        target_local += timedelta(days=1)

    for _ in range(7):
        if target_local.weekday() in _ACCEPTABLE_DAYS:
            break
        target_local += timedelta(days=1)

    fastest_hour = profile.get("fastest_reply_hour")
    preferred = profile.get("preferred_window") or "morning"

    target_utc = _to_utc(target_local, tz_name)

    return {
        "send_at_utc": target_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "send_at_local": target_local.isoformat(),
        "window": preferred,
        "confidence": "optimized",
        "personality": personality,
    }


# ── Should Send Now — real-time check ─────────────────────────────────────────

def should_send_now(contact_id: int, country: str,
                    behavior_type: str = None) -> dict:
    """
    Check whether NOW is a good time to send to this contact.

    Returns dict:
        send_now (bool), reason (str), next_window_utc (str)
    """
    tz_name = get_country_timezone(country)
    now_utc = _utc_now()
    now_local = _to_local(now_utc, tz_name)
    dow = now_local.weekday()
    hour = now_local.hour

    # Weekend check
    if dow > 4:
        next_mon = now_local + timedelta(days=(7 - dow))
        next_mon = next_mon.replace(hour=8, minute=0, second=0, microsecond=0)
        return {
            "send_now": False,
            "reason": "weekend",
            "next_window_utc": _to_utc(next_mon, tz_name).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }

    # Check individual timing profile
    profile = _get_timing_profile(contact_id)
    if profile and profile.get("total_interactions", 0) >= 1:
        optimal_json = profile.get("optimal_send_hours") or "[]"
        try:
            optimal = json.loads(optimal_json)
        except (json.JSONDecodeError, TypeError):
            optimal = []

        if optimal:
            # Check if current hour is within 1 hour of any optimal hour
            in_window = any(abs(hour - oh) <= 1 for oh in optimal)
            if in_window:
                return {
                    "send_now": True,
                    "reason": "in_optimal_window",
                    "next_window_utc": "",
                }
            else:
                # Find next optimal hour
                future_hours = [oh for oh in optimal if oh > hour]
                if future_hours:
                    next_h = min(future_hours)
                    next_dt = now_local.replace(
                        hour=next_h, minute=0, second=0, microsecond=0
                    )
                else:
                    next_dt = (now_local + timedelta(days=1)).replace(
                        hour=min(optimal), minute=0, second=0, microsecond=0
                    )
                return {
                    "send_now": False,
                    "reason": "outside_optimal_window",
                    "next_window_utc": _to_utc(next_dt, tz_name).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }

    # Fall back to default windows
    if behavior_type in ("skeptical", "ghost"):
        win_start, win_end = _DEFAULT_WINDOWS["evening"]
    else:
        win_start, win_end = _DEFAULT_WINDOWS["morning"]

    # Also accept afternoon window
    afternoon_start, afternoon_end = _DEFAULT_WINDOWS["afternoon"]
    in_primary = win_start <= hour < win_end
    in_afternoon = afternoon_start <= hour < afternoon_end

    if in_primary or in_afternoon:
        return {
            "send_now": True,
            "reason": "in_default_window",
            "next_window_utc": "",
        }

    # Find next window
    if hour < win_start:
        next_dt = now_local.replace(
            hour=win_start, minute=0, second=0, microsecond=0
        )
    elif hour < afternoon_start:
        next_dt = now_local.replace(
            hour=afternoon_start, minute=0, second=0, microsecond=0
        )
    else:
        tomorrow = now_local + timedelta(days=1)
        next_dt = tomorrow.replace(
            hour=win_start, minute=0, second=0, microsecond=0
        )
        # Skip weekend
        while next_dt.weekday() > 4:
            next_dt += timedelta(days=1)

    return {
        "send_now": False,
        "reason": "outside_window",
        "next_window_utc": _to_utc(next_dt, tz_name).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }


# ── Update Contact Timing Profile ─────────────────────────────────────────────

def update_contact_timing(contact_id: int, event_type: str,
                          timestamp_utc: str, country: str) -> None:
    """
    Update contact_timing_profile when a reply/open event occurs.

    event_type: 'reply' or 'open'
    timestamp_utc: ISO format UTC timestamp
    country: for timezone lookup
    """
    if not contact_id or not timestamp_utc:
        return

    tz_name = get_country_timezone(country)
    try:
        utc_dt = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        utc_dt = _utc_now()

    local_dt = _to_local(utc_dt, tz_name)
    reply_hour = local_dt.hour + local_dt.minute / 60.0

    try:
        conn = get_db()

        # Ensure profile row exists
        conn.execute("""
            INSERT OR IGNORE INTO contact_timing_profile
                (contact_id, total_interactions, last_updated)
            VALUES (?, 0, ?)
        """, (contact_id, _utc_now().isoformat()))

        # Get current profile
        row = conn.execute(
            "SELECT * FROM contact_timing_profile WHERE contact_id = ?",
            (contact_id,)
        ).fetchone()

        if not row:
            conn.close()
            return

        profile = dict(row)
        total = profile.get("total_interactions", 0) + 1
        old_avg = profile.get("avg_reply_hour_local") or reply_hour
        new_avg = ((old_avg * (total - 1)) + reply_hour) / total

        # Determine personality signal
        if new_avg < 9.0:
            personality = "early_riser"
        elif new_avg < 14.0:
            personality = "midday_worker"
        else:
            personality = "night_owl"

        # Determine preferred window
        if new_avg < 12.0:
            preferred = "morning"
        elif new_avg < 17.0:
            preferred = "afternoon"
        else:
            preferred = "evening"

        # Track fastest reply hour
        fastest = profile.get("fastest_reply_hour")
        if fastest is None:
            fastest = local_dt.hour
        # Keep the hour where they replied fastest (most recent fastest)

        # Build optimal send hours: cluster around average, +/- 1 hour
        avg_int = int(round(new_avg))
        optimal = sorted(set([
            max(6, avg_int - 1), avg_int, min(22, avg_int + 1)
        ]))

        # If we have a reply speed from email_send_analytics, compute it
        reply_speed = None
        if event_type == "reply":
            try:
                last_sent = conn.execute("""
                    SELECT sent_at_utc FROM email_send_analytics
                    WHERE contact_id = ? AND replied_at_utc = ''
                    ORDER BY sent_at_utc DESC LIMIT 1
                """, (contact_id,)).fetchone()
                if last_sent:
                    sent_dt = datetime.fromisoformat(
                        last_sent[0].replace("Z", "+00:00")
                    )
                    reply_speed = int((utc_dt - sent_dt).total_seconds() / 60)
                    # Update the analytics row too
                    conn.execute("""
                        UPDATE email_send_analytics
                        SET replied_at_utc = ?, reply_hour_local = ?,
                            reply_speed_minutes = ?
                        WHERE contact_id = ? AND replied_at_utc = ''
                        ORDER BY sent_at_utc DESC LIMIT 1
                    """, (
                        utc_dt.isoformat(), local_dt.hour,
                        reply_speed, contact_id
                    ))
            except Exception:
                pass

        avg_speed = profile.get("avg_reply_speed_minutes")
        if reply_speed is not None:
            if avg_speed:
                avg_speed = (avg_speed * (total - 1) + reply_speed) / total
            else:
                avg_speed = float(reply_speed)

        conn.execute("""
            UPDATE contact_timing_profile SET
                avg_reply_hour_local = ?,
                preferred_window = ?,
                avg_reply_speed_minutes = ?,
                fastest_reply_hour = ?,
                total_interactions = ?,
                personality_signal = ?,
                optimal_send_hours = ?,
                last_updated = ?
            WHERE contact_id = ?
        """, (
            round(new_avg, 2), preferred, round(avg_speed, 1) if avg_speed else None,
            fastest, total, personality, json.dumps(optimal),
            _utc_now().isoformat(), contact_id
        ))

        conn.commit()
        conn.close()

    except Exception as exc:
        log.error(f"update_contact_timing failed for contact {contact_id}: {exc}")


def recalculate_all_timing_profiles() -> dict:
    """
    Batch job: rebuild all contact_timing_profiles from email_send_analytics.
    Run weekly. Returns stats dict.
    """
    stats = {"profiles_updated": 0, "country_aggregates": {}}
    try:
        conn = get_db()

        # Get all contacts with analytics data
        rows = conn.execute("""
            SELECT contact_id, country,
                   reply_hour_local, reply_speed_minutes,
                   sent_hour_local, sent_at_utc, replied_at_utc
            FROM email_send_analytics
            WHERE replied_at_utc != ''
            ORDER BY contact_id
        """).fetchall()

        if not rows:
            conn.close()
            return stats

        # Group by contact
        from itertools import groupby
        from operator import itemgetter

        contacts_data = {}
        country_hours = {}  # country -> [reply_hours]

        for row in rows:
            cid = row["contact_id"]
            if cid not in contacts_data:
                contacts_data[cid] = {
                    "reply_hours": [], "reply_speeds": [],
                    "country": row["country"]
                }
            if row["reply_hour_local"] is not None:
                contacts_data[cid]["reply_hours"].append(row["reply_hour_local"])
                country_key = (row["country"] or "").strip().lower()
                if country_key:
                    country_hours.setdefault(country_key, []).append(
                        row["reply_hour_local"]
                    )
            if row["reply_speed_minutes"] is not None:
                contacts_data[cid]["reply_speeds"].append(
                    row["reply_speed_minutes"]
                )

        # Update each contact profile
        for cid, data in contacts_data.items():
            hours = data["reply_hours"]
            speeds = data["reply_speeds"]
            if not hours:
                continue

            avg_hour = sum(hours) / len(hours)
            avg_speed = sum(speeds) / len(speeds) if speeds else None
            fastest_hour = int(min(hours))
            total = len(hours)

            if avg_hour < 9.0:
                personality = "early_riser"
            elif avg_hour < 14.0:
                personality = "midday_worker"
            else:
                personality = "night_owl"

            if avg_hour < 12.0:
                preferred = "morning"
            elif avg_hour < 17.0:
                preferred = "afternoon"
            else:
                preferred = "evening"

            avg_int = int(round(avg_hour))
            optimal = sorted(set([
                max(6, avg_int - 1), avg_int, min(22, avg_int + 1)
            ]))

            conn.execute("""
                INSERT INTO contact_timing_profile
                    (contact_id, avg_reply_hour_local, preferred_window,
                     avg_reply_speed_minutes, fastest_reply_hour,
                     total_interactions, personality_signal,
                     optimal_send_hours, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contact_id) DO UPDATE SET
                    avg_reply_hour_local = excluded.avg_reply_hour_local,
                    preferred_window = excluded.preferred_window,
                    avg_reply_speed_minutes = excluded.avg_reply_speed_minutes,
                    fastest_reply_hour = excluded.fastest_reply_hour,
                    total_interactions = excluded.total_interactions,
                    personality_signal = excluded.personality_signal,
                    optimal_send_hours = excluded.optimal_send_hours,
                    last_updated = excluded.last_updated
            """, (
                cid, round(avg_hour, 2), preferred,
                round(avg_speed, 1) if avg_speed else None,
                fastest_hour, total, personality,
                json.dumps(optimal), _utc_now().isoformat()
            ))
            stats["profiles_updated"] += 1

        # Build per-country aggregates
        for country_key, reply_hrs in country_hours.items():
            avg_h = sum(reply_hrs) / len(reply_hrs)
            stats["country_aggregates"][country_key] = {
                "avg_reply_hour": round(avg_h, 2),
                "sample_count": len(reply_hrs),
            }

        conn.commit()
        conn.close()

    except Exception as exc:
        log.error(f"recalculate_all_timing_profiles failed: {exc}")

    return stats


# ── Record send analytics helper ──────────────────────────────────────────────

def record_send_analytics(contact_id: int, email_type: str, country: str,
                          behavior_type: str = "unknown") -> None:
    """
    Log an email send to email_send_analytics with timezone conversion.
    Called from intro_mailer.py and mailer.py after every email send.
    """
    tz_name = get_country_timezone(country)
    now_utc = _utc_now()
    now_local = _to_local(now_utc, tz_name)

    try:
        conn = get_db()
        conn.execute("""
            INSERT INTO email_send_analytics
                (contact_id, email_type, sent_at_utc, sent_at_local,
                 sent_day_of_week, sent_hour_local, behavior_type, country)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            contact_id,
            email_type,
            now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            now_local.isoformat(),
            now_local.weekday(),
            now_local.hour,
            behavior_type or "unknown",
            country or "",
        ))
        conn.commit()
        conn.close()
    except Exception as exc:
        log.error(f"record_send_analytics failed for contact {contact_id}: {exc}")


# ── Cultural opening lines — port/lane specific per country ───────────────────
# Used on email 1 only. Rotates from pool so it never repeats back-to-back.
_CULTURAL_LINES = {
    # Europe
    "italy": [
        "From Genoa and La Spezia to the US West Coast — we know this lane well.",
        "Italy's export power deserves freight partners who understand the route.",
        "Livorno to Los Angeles — precision and reliability, every sailing.",
    ],
    "germany": [
        "Hamburg to the US West Coast — efficient, as it should be.",
        "From the port of Hamburg, we keep European precision moving west.",
        "Bremerhaven to Long Beach — Germany's export corridor, done right.",
    ],
    "france": [
        "Le Havre to Los Angeles — connecting France to the US West Coast.",
        "From Marseille and Le Havre, we keep French cargo moving.",
        "France's transatlantic lanes deserve a freight partner who knows the route.",
    ],
    "netherlands": [
        "Rotterdam to the US West Coast — the world's gateway, moving west.",
        "From Rotterdam, the busiest port in Europe, we connect you to LA.",
        "Rotterdam to Long Beach — efficiency built into every step.",
    ],
    "belgium": [
        "Antwerp to Los Angeles — one of the world's most connected corridors.",
        "From the port of Antwerp, we keep Belgium's cargo moving west.",
        "Antwerp to Long Beach — reliable, direct, competitive.",
    ],
    "spain": [
        "Barcelona and Valencia to the US West Coast — we know every sailing.",
        "From Algeciras to Los Angeles — Spain's southern gateway, moving west.",
        "Spain's export lanes to the US deserve a freight partner built for the route.",
    ],
    "portugal": [
        "Lisbon and Sines to the US West Coast — Atlantic crossings done right.",
        "From Leixões to Los Angeles — Portugal's freight corridor, covered.",
        "Portugal's Atlantic position makes it a natural bridge to the US. We move it.",
    ],
    "turkey": [
        "From Istanbul and Mersin, connecting East and West since the Silk Road.",
        "Ambarlı to Los Angeles — Turkey's trade corridor, moving west.",
        "Turkey sits at the crossroads. We make sure your cargo keeps moving.",
    ],
    "greece": [
        "Piraeus to the US West Coast — from the ancient trade routes to modern lanes.",
        "From Piraeus, one of the Mediterranean's busiest ports, we connect you west.",
        "Greece's maritime legacy continues — Piraeus to Long Beach.",
    ],
    "poland": [
        "Gdansk to the US West Coast — Poland's Baltic gateway, moving west.",
        "From Gdynia and Gdansk, connecting Central Europe to LA.",
        "Poland's growing export power deserves freight partners who know the lane.",
    ],
    "sweden": [
        "Gothenburg to the US West Coast — Scandinavia's main port, moving west.",
        "From Gothenburg, we connect Sweden to the US freight corridor.",
        "Sweden's precision manufacturing deserves equally precise freight.",
    ],
    "denmark": [
        "From Copenhagen and Aarhus, connecting Scandinavia to the US West Coast.",
        "Denmark's maritime tradition meets modern freight — we move it west.",
        "Aarhus to Los Angeles — Nordic efficiency on every sailing.",
    ],
    "norway": [
        "Bergen to the US West Coast — Norway's deep-sea lanes, covered.",
        "From Oslo and Bergen, connecting Norway's exports to LA.",
        "Norway's maritime expertise meets a freight partner who speaks the language.",
    ],
    "finland": [
        "Helsinki to the US West Coast — Nordic reliability, every sailing.",
        "From the Port of HaminaKotka, Finland's exports move west with us.",
        "Finland's industrial exports deserve freight built on precision.",
    ],
    "switzerland": [
        "Basel to the US West Coast via Rotterdam — land and sea, seamlessly.",
        "Switzerland's exports travel far. We make sure they arrive on time.",
        "From Basel, landlocked but globally connected — we handle the sea leg.",
    ],
    "austria": [
        "Vienna to the US West Coast — Central Europe to LA, handled.",
        "Austria's exports via Hamburg and Rotterdam — we connect every link.",
        "From the heart of Europe to the US West Coast — end to end.",
    ],
    "russia": [
        "St. Petersburg and Vladivostok — connecting Russia's ports to the US.",
        "From Russia's Baltic and Pacific gateways, we keep cargo moving.",
        "Russia's vast geography needs freight partners with global reach.",
    ],
    "ukraine": [
        "Odessa to the US West Coast — connecting Ukraine's Black Sea port west.",
        "From Odessa and Chornomorsk, Ukraine's freight corridor, covered.",
        "Ukraine's resilient trade community deserves freight partners who show up.",
    ],

    # Asia-Pacific
    "china": [
        "Shanghai, Ningbo, Shenzhen — we know every lane to the US West Coast.",
        "From COSCO's home waters to Long Beach — China to the US, covered.",
        "China's manufacturing power meets US West Coast reach. We move it.",
    ],
    "hong kong": [
        "Hong Kong to Los Angeles — one of the world's busiest trade corridors.",
        "From Hong Kong's port, connecting Asia's financial hub to the US.",
        "Hong Kong to Long Beach — a lane we've run for years.",
    ],
    "taiwan": [
        "Kaohsiung to the US West Coast — Taiwan's export engine, moving west.",
        "From Keelung and Kaohsiung, Taiwan's tech exports arrive on time.",
        "Taiwan to Long Beach — a lane built on precision and reliability.",
    ],
    "japan": [
        "Yokohama and Kobe to Long Beach — one of the world's great trade lanes.",
        "From Tokyo Bay to the US West Coast — Japan's export corridor, done right.",
        "Osaka and Nagoya to Los Angeles — reliability on every sailing.",
    ],
    "south korea": [
        "Busan to Long Beach — one of the busiest lanes on the Pacific.",
        "From Busan, the world's sixth largest port, we move Korea's exports west.",
        "Incheon to Los Angeles — Korea's freight corridor, covered.",
    ],
    "korea": [
        "Busan to Long Beach — one of the busiest lanes on the Pacific.",
        "From Busan, the world's sixth largest port, we move Korea's exports west.",
        "Incheon to Los Angeles — Korea's freight corridor, covered.",
    ],
    "india": [
        "JNPT and Mundra to the US West Coast — India's export lanes, covered.",
        "From Mumbai and Chennai, connecting India's manufacturing belt to LA.",
        "India's growing export power deserves freight built for the long haul.",
    ],
    "singapore": [
        "Singapore — the world's second largest port — connected to the US West Coast.",
        "From Singapore's hub, we route Southeast Asia's cargo to LA.",
        "Singapore to Long Beach — the gateway between Asia and the Americas.",
    ],
    "malaysia": [
        "Port Klang and Tanjung Pelepas to the US West Coast — covered.",
        "From Malaysia's ports, connecting Southeast Asia to LA.",
        "Penang to Los Angeles — Malaysia's freight corridor, running on time.",
    ],
    "indonesia": [
        "Tanjung Priok to the US West Coast — Indonesia's main port, moving west.",
        "From Jakarta's port, the world's largest archipelago connects to LA.",
        "Indonesia to Long Beach — a growing corridor we know well.",
    ],
    "thailand": [
        "Laem Chabang to the US West Coast — Thailand's export hub, covered.",
        "From Bangkok and Laem Chabang, Thailand's automotive exports move west.",
        "Thailand to Los Angeles — reliable, consistent, competitive.",
    ],
    "vietnam": [
        "Ho Chi Minh and Haiphong to the US West Coast — Vietnam's boom, moving west.",
        "From Cat Lai port, Vietnam's manufacturing growth connects to LA.",
        "Vietnam to Long Beach — one of the fastest growing lanes on the Pacific.",
    ],
    "philippines": [
        "Manila to the US West Coast — the Pacific's natural midpoint.",
        "From Port of Manila, connecting the Philippines to Los Angeles.",
        "Manila to Long Beach — a Pacific corridor we run every week.",
    ],
    "australia": [
        "Melbourne and Sydney to the US West Coast — the Pacific South covered.",
        "From Fremantle to Los Angeles — Australia's freight corridor, handled.",
        "Australia to Long Beach — a long haul worth getting right every time.",
    ],
    "new zealand": [
        "Auckland and Tauranga to the US West Coast — the South Pacific, connected.",
        "From New Zealand's ports to Los Angeles — precision on the long route.",
        "Tauranga to Long Beach — New Zealand's export lane, done right.",
    ],

    # Americas
    "brazil": [
        "Santos and Rio to the US West Coast — South America's largest economy, moving.",
        "From the Port of Santos, Brazil's export powerhouse connects to LA.",
        "Brazil to Long Beach — a transatlantic lane built on volume and reliability.",
    ],
    "mexico": [
        "Manzanillo and Lázaro Cárdenas to US West Coast ports — a natural corridor.",
        "From Mexico's Pacific ports, connecting to Los Angeles is our lane.",
        "Veracruz to LA — Mexico's trade corridor, running every week.",
    ],
    "colombia": [
        "Cartagena and Buenaventura to the US West Coast — Colombia's ports, covered.",
        "From Cartagena, connecting South America's northern coast to LA.",
        "Colombia to Long Beach — a lane built on reliability and competitive rates.",
    ],
    "argentina": [
        "Buenos Aires to the US West Coast — the Southern Cone, connected.",
        "From Puerto Buenos Aires, Argentina's exports move north and west.",
        "Argentina to Los Angeles — a long lane worth getting right.",
    ],
    "chile": [
        "Valparaíso and San Antonio to the US West Coast — Chile's Pacific ports, covered.",
        "From Chile's copper coast to Los Angeles — a natural Pacific corridor.",
        "San Antonio to Long Beach — Chile's export lane, running reliably.",
    ],
    "canada": [
        "Vancouver and Prince Rupert to the US West Coast — North America's Pacific corridor.",
        "From Canada's Pacific ports, connecting seamlessly to US routes.",
        "Vancouver to Los Angeles — the Canada-US West Coast lane, covered.",
    ],

    # Middle East / Africa
    "uae": [
        "Jebel Ali to Los Angeles — one of the world's most important trade corridors.",
        "From Jebel Ali, the Middle East's largest port, connecting to the US West Coast.",
        "Dubai to Long Beach — a lane that never stops moving.",
    ],
    "united arab emirates": [
        "Jebel Ali to Los Angeles — one of the world's most important trade corridors.",
        "From Jebel Ali, the Middle East's largest port, connecting to the US West Coast.",
        "Dubai to Long Beach — a lane that never stops moving.",
    ],
    "saudi arabia": [
        "King Abdullah Port and Jeddah to the US West Coast — the Kingdom's freight, covered.",
        "From Dammam to Los Angeles — Saudi Arabia's export corridor, handled.",
        "Jeddah to Long Beach — the Red Sea to the Pacific, connected.",
    ],
    "qatar": [
        "Hamad Port to the US West Coast — Qatar's world-class port, moving west.",
        "From Doha's Hamad Port, connecting the Gulf to Los Angeles.",
        "Qatar to Long Beach — a Gulf corridor built on reliability.",
    ],
    "kuwait": [
        "Shuwaikh to the US West Coast — Kuwait's trade lane, covered.",
        "From Kuwait's ports, connecting the Gulf to the US West Coast.",
        "Kuwait to Los Angeles — a lane we run with consistency.",
    ],
    "egypt": [
        "Port Said and Alexandria to the US West Coast — Egypt's gateway, covered.",
        "From Port Said at the Suez Canal, Egypt connects the world. We move it west.",
        "Alexandria to Los Angeles — the Mediterranean to the Pacific, end to end.",
    ],
    "south africa": [
        "Durban and Cape Town to the US West Coast — Africa's southern gateway.",
        "From Durban, Africa's busiest port, connecting to Los Angeles.",
        "South Africa to Long Beach — a route that spans two oceans.",
    ],
    "nigeria": [
        "Apapa and Tin Can Island to the US West Coast — West Africa's hub, connected.",
        "From Lagos, West Africa's largest economy connects to Los Angeles.",
        "Nigeria to Long Beach — West Africa's freight corridor, covered.",
    ],
    "kenya": [
        "Mombasa to the US West Coast — East Africa's gateway port, moving west.",
        "From Mombasa, connecting East Africa to Los Angeles.",
        "Kenya to Long Beach — East Africa's trade lane, running reliably.",
    ],
}

_DEFAULT_CULTURAL_LINES = [
    "Connecting your market to the US West Coast — that's what we do.",
    "Los Angeles, Long Beach — we know every lane to your port.",
    "Reliable freight from your port to the US West Coast, every sailing.",
]

# ── Interest capture questions (rotates so it doesn't repeat) ─────────────────
_INTEREST_QUESTIONS = [
    "Quick one outside of work — what do you follow? Always good to know who we're working with.",
    "One question while I have you — what keeps you busy outside the office?",
    "We like knowing who we're working with — what do you enjoy outside of freight?",
]


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def get_or_create_profile(contact_id):
    """Return the contact_profiles row, creating it if it doesn't exist."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM contact_profiles WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO contact_profiles (contact_id, created_at, updated_at) VALUES (?, ?, ?)",
            (contact_id, _now_iso(), _now_iso()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM contact_profiles WHERE contact_id = ?", (contact_id,)
        ).fetchone()
    conn.close()
    return dict(row)


def update_profile(contact_id, **fields):
    """Update specific fields on a contact profile."""
    fields["updated_at"] = _now_iso()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [contact_id]
    conn = get_db()
    conn.execute(
        f"UPDATE contact_profiles SET {set_clause} WHERE contact_id = ?", values
    )
    conn.commit()
    conn.close()


def log_interaction(contact_id, email_type, cycle="", cultural_line="", interest_asked=False):
    """Record an outbound email interaction."""
    conn = get_db()
    conn.execute(
        """INSERT INTO contact_interactions
           (contact_id, email_type, cycle, sent_at, cultural_line, interest_asked)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (contact_id, email_type, cycle, _now_iso(), cultural_line, int(interest_asked)),
    )
    conn.commit()
    conn.close()


def record_response(contact_id, sent_at_iso):
    """Called when a contact replies. Updates behavioral scoring."""
    try:
        sent = datetime.fromisoformat(sent_at_iso)
        responded = datetime.now()
        hours = (responded - sent).total_seconds() / 3600
    except Exception:
        hours = None

    conn = get_db()

    # Update the most recent interaction
    conn.execute(
        """UPDATE contact_interactions
           SET responded_at = ?, response_hours = ?
           WHERE contact_id = ? AND responded_at = ''
           ORDER BY sent_at DESC LIMIT 1""",
        (_now_iso(), hours, contact_id),
    )

    profile = get_or_create_profile(contact_id)
    new_response_count = profile["response_count"] + 1

    # Rolling average response time
    if hours is not None:
        old_avg = profile["avg_response_hours"] or 0
        new_avg = ((old_avg * profile["response_count"]) + hours) / new_response_count
    else:
        new_avg = profile["avg_response_hours"]

    behavior = _classify_behavior(new_avg, new_response_count, profile.get("email_count", 0))
    email_style, subject_tone = _behavior_to_style(behavior)

    conn.execute(
        """UPDATE contact_profiles SET
           response_count = ?, avg_response_hours = ?, behavior_type = ?,
           email_style = ?, subject_tone = ?, last_responded_at = ?, updated_at = ?
           WHERE contact_id = ?""",
        (new_response_count, new_avg, behavior, email_style, subject_tone,
         _now_iso(), _now_iso(), contact_id),
    )
    conn.commit()
    conn.close()
    return {"behavior": behavior, "avg_hours": round(new_avg, 1) if new_avg else None}


def _classify_behavior(avg_hours, response_count, email_count=0):
    """
    Classify contact behavior based on average response time and engagement.
    7-type psychological profile system.
    """
    if response_count == 0:
        if email_count >= 2:
            return "ghost"      # sent 2+ emails, zero response — disengaged
        return "unknown"
    if avg_hours is None:
        return "unknown"
    if avg_hours < 1:
        return "decisive"   # action-oriented, values efficiency
    if avg_hours < 6:
        return "engaged"    # professional, interested, data-driven
    if avg_hours < 24:
        return "thoughtful" # methodical, weighing options
    if avg_hours < 48:
        return "cautious"   # needs trust first, relationship-oriented
    if avg_hours < 72:
        return "busy"       # overwhelmed, time-poor
    return "skeptical"      # been pitched too many times, hard to reach



# ── Psychological behavior profiles (book-driven) ───────────────────────────────
# Each behavior type maps to a full psychological profile with principles from
# the 6 books and specific email copywriting techniques.
_BEHAVIOR_PROFILES = {
    "decisive": {
        "style": "short", "tone": "functional",
        "label": "Decisive — replies within an hour. Respects efficiency.",
        "psychology": "Action-oriented, values efficiency, fast decision-maker",
        "principles": ["respect_time", "be_direct", "proactive", "no_fluff"],
        "strategy": "Short, direct, clear next step. No fluff. Mirror their pace.",
        "book_techniques": {
            "7_habits": "Be Proactive — mirror their action-oriented nature",
            "atomic_habits": "Make it Obvious — clear next step, zero ambiguity",
            "never_split": "Mirror — match their pace and directness exactly",
            "win_friends": "Respect their time — brevity IS the compliment",
            "influence": "Authority — signal competence fast, no warm-up needed",
            "think_grow_rich": "Definiteness of purpose — one clear ask, one clear outcome",
        },
        "email_rules": [
            "Max 4 sentences in body",
            "Subject line under 8 words",
            "Single CTA — never offer options",
            "No pleasantries — straight to business",
            "Use bullet points over paragraphs",
        ],
    },
    "engaged": {
        "style": "standard", "tone": "functional",
        "label": "Engaged — responds same day. Professional and interested.",
        "psychology": "Professional, data-driven, interested in specifics",
        "principles": ["show_data", "structured_value", "definiteness", "specificity"],
        "strategy": "Data-driven, structured, show clear value proposition.",
        "book_techniques": {
            "think_grow_rich": "Definiteness of Purpose — specific numbers, clear goals",
            "influence": "Authority + Social Proof — volume stats, network size",
            "7_habits": "Think Win-Win — mutual benefit framing",
            "atomic_habits": "Make it Satisfying — show results they can expect",
            "never_split": "Calibrated questions — ask about their operation specifics",
            "win_friends": "Talk in terms of their interests — their market, their lanes",
        },
        "email_rules": [
            "Include specific numbers (container volumes, country count)",
            "Structured format with clear sections",
            "Medium length — enough detail to be credible",
            "Professional tone — peer-to-peer, not sales pitch",
            "Reference their specific market or corridor",
        ],
    },
    "thoughtful": {
        "style": "standard", "tone": "data-driven",
        "label": "Thoughtful — takes a day. Weighing options carefully.",
        "psychology": "Methodical, analytical, weighing options before committing",
        "principles": ["provide_proof", "social_validation", "credibility_signals", "patience"],
        "strategy": "Provide proof, social validation, credibility signals. Let them decide.",
        "book_techniques": {
            "influence": "Social Proof — '40+ countries', agent testimonials, network stats",
            "7_habits": "Seek First to Understand — ask before pitching",
            "think_grow_rich": "Mastermind — frame as joining a network of top agents",
            "never_split": "Labels — 'It seems like quality partnerships matter to you...'",
            "atomic_habits": "Make it Obvious — lay out exactly what happens next",
            "win_friends": "Let them feel the idea is theirs — present options, don't push",
        },
        "email_rules": [
            "Include social proof in every email",
            "Provide options — don't force a single path",
            "Reference other agents or network size naturally",
            "Give them room to evaluate — no pressure language",
            "Medium-to-detailed length — they want substance",
        ],
    },
    "cautious": {
        "style": "warm", "tone": "warm",
        "label": "Cautious — takes 1-2 days. Needs trust first.",
        "psychology": "Relationship-oriented, needs trust before business, risk-averse",
        "principles": ["build_trust", "genuine_interest", "relationship_first", "warmth"],
        "strategy": "Warm, relationship-first. Show you understand their world.",
        "book_techniques": {
            "win_friends": "Genuine Interest — ask about THEIR operation, THEIR challenges",
            "never_split": "Tactical Empathy — 'We know choosing a partner is a big decision...'",
            "influence": "Reciprocity — give value first (market insights, lane data)",
            "7_habits": "Seek First to Understand — learn their world before selling",
            "atomic_habits": "Make it Easy — low-commitment first step",
            "think_grow_rich": "Burning Desire — show your passion for the partnership",
        },
        "email_rules": [
            "Lead with warmth — personal greeting, hope they're well",
            "Ask about their business before making any ask",
            "Reference their country/city/port specifically",
            "Offer value before requesting anything",
            "Longer emails OK — relationships take words",
        ],
    },
    "busy": {
        "style": "short", "tone": "functional",
        "label": "Busy — takes 2-3 days. Overwhelmed, time-poor.",
        "psychology": "Overwhelmed, time-poor, filters aggressively, values brevity",
        "principles": ["remove_friction", "one_click", "ultra_brief", "respect_time"],
        "strategy": "Ultra-brief, remove all friction. One-click everything.",
        "book_techniques": {
            "atomic_habits": "Make it Easy — one-click responses, zero friction",
            "never_split": "Accusation audit — 'We know you're slammed...'",
            "influence": "Scarcity — 'Rate round closes Friday' — create urgency",
            "7_habits": "Be Proactive — do the work for them, pre-fill everything",
            "win_friends": "Respect their time — the shortest email wins",
            "think_grow_rich": "Definiteness — one single ask, unmissable",
        },
        "email_rules": [
            "Max 3 sentences total",
            "One-click CTA — no multi-step process",
            "Subject line must scream 'this is fast'",
            "Remove all pleasantries — get to the point",
            "Bold the single ask so they can skim",
        ],
    },
    "skeptical": {
        "style": "short", "tone": "empathetic",
        "label": "Skeptical — 3+ days or hostile tone. Been pitched too many times.",
        "psychology": "Jaded, over-pitched, guards up, filters ruthlessly",
        "principles": ["pattern_interrupt", "tactical_empathy", "differentiate", "acknowledge"],
        "strategy": "Accusation audit, pattern interrupt, acknowledge their skepticism.",
        "book_techniques": {
            "never_split": "Accusation Audit — 'You probably get a hundred of these...'",
            "influence": "Contrast Principle — show how you're different from the noise",
            "win_friends": "Avoid argument — never push back on resistance",
            "atomic_habits": "Change the Cue — completely different subject line format",
            "7_habits": "Be Proactive — acknowledge their position before asking anything",
            "think_grow_rich": "Persistence — respectful persistence without pressure",
        },
        "email_rules": [
            "Open with accusation audit — name what they're thinking",
            "Pattern-interrupt subject line — no 'partnership' or 'rates'",
            "Short and honest — no corporate speak",
            "Differentiate in first sentence — why THIS email is different",
            "Low-pressure CTA — 'no rush, no obligation'",
        ],
    },
    "ghost": {
        "style": "standard", "tone": "warm",
        "label": "Ghost — no response after multiple emails.",
        "psychology": "Disengaged, inbox overload, or timing was wrong",
        "principles": ["change_angle", "curiosity_trigger", "break_pattern", "respect"],
        "strategy": "Complete angle change. Curiosity trigger. Break the pattern.",
        "book_techniques": {
            "power_of_habit": "Change the Routine — completely new approach",
            "never_split": "Late-night FM DJ voice — calm, non-threatening tone",
            "influence": "Scarcity — 'Last time reaching out...' creates decision pressure",
            "win_friends": "Arouse curiosity — lead with something unexpected",
            "atomic_habits": "Make it Attractive — reframe the value proposition entirely",
            "think_grow_rich": "Persistence with purpose — not spam, strategic re-engagement",
        },
        "email_rules": [
            "Completely different angle from previous emails",
            "New subject line format — question, curiosity, or humor",
            "Acknowledge the silence — 'I know you're busy'",
            "One simple question — not a pitch",
            "Option to opt out — shows respect, reduces resistance",
        ],
    },
    "unknown": {
        "style": "standard", "tone": "functional",
        "label": "New contact — no response data yet.",
        "psychology": "Unknown — first impression matters most",
        "principles": ["strong_first_impression", "genuine_interest", "make_it_easy", "credibility"],
        "strategy": "Genuine interest + make it easy. Strong first impression.",
        "book_techniques": {
            "win_friends": "Begin with genuine interest — their company, their market",
            "atomic_habits": "Make it Easy — frictionless first response",
            "influence": "Social Proof + Authority — establish credibility immediately",
            "never_split": "Mirror — adapt to whatever signals they give",
            "7_habits": "Think Win-Win — frame as mutual opportunity",
            "think_grow_rich": "Definiteness of Purpose — clear about what you want",
        },
        "email_rules": [
            "Professional but not stiff",
            "Establish credibility in first paragraph",
            "Clear, single CTA",
            "Medium length — enough to be credible",
            "Include one social proof element",
        ],
    },
}


def _behavior_to_style(behavior):
    """Return (email_style, subject_tone) for a behavior type."""
    profile = _BEHAVIOR_PROFILES.get(behavior, _BEHAVIOR_PROFILES["unknown"])
    return (profile["style"], profile["tone"])


# ── Country mottos / national slogans ─────────────────────────────────────────
# Used as cultural trust signals in emails. 55+ countries covered.
_COUNTRY_MOTTOS = {
    # Europe
    "italy":           {"original": "L'Italia è una Repubblica fondata sul lavoro", "translation": "Italy is a Republic founded on work", "theme": "work ethic"},
    "germany":         {"original": "Einigkeit und Recht und Freiheit", "translation": "Unity and Justice and Freedom", "theme": "unity"},
    "france":          {"original": "Liberté, égalité, fraternité", "translation": "Liberty, Equality, Fraternity", "theme": "equality"},
    "spain":           {"original": "Plus Ultra", "translation": "Further Beyond", "theme": "ambition"},
    "netherlands":     {"original": "Je maintiendrai", "translation": "I will maintain", "theme": "persistence"},
    "belgium":         {"original": "L'union fait la force", "translation": "Strength through Unity", "theme": "unity"},
    "switzerland":     {"original": "Unus pro omnibus, omnes pro uno", "translation": "One for all, all for one", "theme": "solidarity"},
    "austria":         {"original": "Es ist Österreichs Bestimmung", "translation": "It is Austria's destiny", "theme": "destiny"},
    "poland":          {"original": "Bóg, Honor, Ojczyzna", "translation": "God, Honour, Fatherland", "theme": "honour"},
    "greece":          {"original": "Ελευθερία ή Θάνατος", "translation": "Freedom or Death", "theme": "freedom"},
    "turkey":          {"original": "Yurtta sulh, cihanda sulh", "translation": "Peace at Home, Peace in the World", "theme": "peace"},
    "portugal":        {"original": "Esta é a ditosa pátria minha amada", "translation": "This is my beloved fortunate homeland", "theme": "homeland"},
    "sweden":          {"original": "För Sverige – i tiden", "translation": "For Sweden, with the times", "theme": "progress"},
    "denmark":         {"original": "Guds hjælp, folkets kærlighed, Danmarks styrke", "translation": "God's help, the people's love, Denmark's strength", "theme": "strength"},
    "norway":          {"original": "Alt for Norge", "translation": "Everything for Norway", "theme": "dedication"},
    "finland":         {"original": "Sisu", "translation": "Inner strength and determination", "theme": "resilience"},
    "russia":          {"original": "С нами Бог", "translation": "God is with us", "theme": "faith"},
    "ukraine":         {"original": "Воля і Злагода", "translation": "Freedom and Harmony", "theme": "harmony"},
    "czech republic":  {"original": "Pravda vítězí", "translation": "Truth prevails", "theme": "truth"},
    "romania":         {"original": "Nihil sine Deo", "translation": "Nothing without God", "theme": "faith"},
    "ireland":         {"original": "Éire go Brách", "translation": "Ireland Forever", "theme": "endurance"},
    "united kingdom":  {"original": "Dieu et mon droit", "translation": "God and my right", "theme": "authority"},
    "uk":              {"original": "Dieu et mon droit", "translation": "God and my right", "theme": "authority"},
    "hungary":         {"original": "Regnum Mariae Patrona Hungariae", "translation": "Kingdom of Mary, Patron of Hungary", "theme": "tradition"},
    "croatia":         {"original": "Bog i Hrvati", "translation": "God and Croats", "theme": "identity"},
    # Asia-Pacific
    "china":           {"original": "为人民服务", "translation": "Serve the People", "theme": "service"},
    "hong kong":       {"original": "为人民服务", "translation": "Serve the People", "theme": "service"},
    "taiwan":          {"original": "三民主義", "translation": "Three Principles of the People", "theme": "principles"},
    "japan":           {"original": "和", "translation": "Harmony", "theme": "harmony"},
    "south korea":     {"original": "홍익인간", "translation": "Benefit broadly the human world", "theme": "benefit"},
    "korea":           {"original": "홍익인간", "translation": "Benefit broadly the human world", "theme": "benefit"},
    "india":           {"original": "सत्यमेव जयते", "translation": "Truth Alone Triumphs", "theme": "truth"},
    "singapore":       {"original": "Majulah Singapura", "translation": "Onward Singapore", "theme": "progress"},
    "malaysia":        {"original": "Bersekutu Bertambah Mutu", "translation": "Unity is Strength", "theme": "unity"},
    "indonesia":       {"original": "Bhinneka Tunggal Ika", "translation": "Unity in Diversity", "theme": "diversity"},
    "thailand":        {"original": "ชาติ ศาสนา พระมหากษัตริย์", "translation": "Nation, Religion, King", "theme": "tradition"},
    "vietnam":         {"original": "Độc lập, Tự do, Hạnh phúc", "translation": "Independence, Freedom, Happiness", "theme": "independence"},
    "philippines":     {"original": "Maka-Diyos, Maka-Tao, Makakalikasan at Makabansa", "translation": "For God, People, Nature and Country", "theme": "community"},
    "australia":       {"original": "Advance Australia Fair", "translation": "Advance Australia Fair", "theme": "progress"},
    "new zealand":     {"original": "Aotearoa", "translation": "Land of the Long White Cloud", "theme": "nature"},
    "pakistan":         {"original": "ایمان، اتحاد، نظم", "translation": "Faith, Unity, Discipline", "theme": "discipline"},
    "bangladesh":      {"original": "জয় বাংলা", "translation": "Victory to Bengal", "theme": "victory"},
    "sri lanka":       {"original": "ශ්‍රී ලංකා", "translation": "Resplendent Island", "theme": "beauty"},
    # Americas
    "usa":             {"original": "In God We Trust", "translation": "In God We Trust", "theme": "trust"},
    "united states":   {"original": "In God We Trust", "translation": "In God We Trust", "theme": "trust"},
    "brazil":          {"original": "Ordem e Progresso", "translation": "Order and Progress", "theme": "progress"},
    "mexico":          {"original": "La Patria Es Primero", "translation": "The Homeland is First", "theme": "homeland"},
    "colombia":        {"original": "Libertad y Orden", "translation": "Liberty and Order", "theme": "liberty"},
    "argentina":       {"original": "En unión y libertad", "translation": "In Unity and Freedom", "theme": "unity"},
    "chile":           {"original": "Por la razón o la fuerza", "translation": "By right or might", "theme": "determination"},
    "peru":            {"original": "Firme y feliz por la unión", "translation": "Firm and happy through union", "theme": "union"},
    "canada":          {"original": "A Mari Usque Ad Mare", "translation": "From Sea to Sea", "theme": "reach"},
    "ecuador":         {"original": "Dios, Patria y Libertad", "translation": "God, Homeland, and Liberty", "theme": "liberty"},
    "panama":          {"original": "Pro Mundi Beneficio", "translation": "For the Benefit of the World", "theme": "global benefit"},
    "costa rica":      {"original": "Vivan siempre el trabajo y la paz", "translation": "May work and peace live forever", "theme": "peace"},
    "venezuela":       {"original": "Dios y Federación", "translation": "God and Federation", "theme": "federation"},
    # Middle East / Africa
    "uae":             {"original": "الله، الوطن، الرئيس", "translation": "God, Nation, President", "theme": "devotion"},
    "united arab emirates": {"original": "الله، الوطن، الرئيس", "translation": "God, Nation, President", "theme": "devotion"},
    "saudi arabia":    {"original": "لا إله إلا الله", "translation": "There is no god but God", "theme": "faith"},
    "qatar":           {"original": "الله، الوطن، الأمير", "translation": "God, Nation, Emir", "theme": "devotion"},
    "kuwait":          {"original": "الله، الوطن، الأمير", "translation": "God, Nation, Emir", "theme": "devotion"},
    "egypt":           {"original": "جمهورية مصر العربية", "translation": "Arab Republic of Egypt", "theme": "republic"},
    "israel":          {"original": "תקוותנו", "translation": "Our Hope", "theme": "hope"},
    "south africa":    {"original": "!ke e: /xarra //ke", "translation": "Diverse people unite", "theme": "diversity"},
    "nigeria":         {"original": "Unity and Faith, Peace and Progress", "translation": "Unity and Faith, Peace and Progress", "theme": "unity"},
    "kenya":           {"original": "Harambee", "translation": "Let us all pull together", "theme": "teamwork"},
    "ghana":           {"original": "Freedom and Justice", "translation": "Freedom and Justice", "theme": "justice"},
    "morocco":         {"original": "الله، الوطن، الملك", "translation": "God, Homeland, King", "theme": "devotion"},
    "jordan":          {"original": "الله، الوطن، الملك", "translation": "God, Homeland, King", "theme": "devotion"},
    "lebanon":         {"original": "Kulluna lil-watan", "translation": "All of us for the homeland", "theme": "solidarity"},
    "tanzania":        {"original": "Uhuru na Umoja", "translation": "Freedom and Unity", "theme": "freedom"},
    "bahrain":         {"original": "الله، الوطن، الملك", "translation": "God, Homeland, King", "theme": "devotion"},
    "oman":            {"original": "الله، الوطن، السلطان", "translation": "God, Homeland, Sultan", "theme": "devotion"},
}


def get_country_motto(country):
    """Return motto dict for a country, or None if not found."""
    return _COUNTRY_MOTTOS.get((country or "").strip().lower())


# ── Book Techniques — email copywriting methods from each book ────────────────
# Maps each book to specific techniques that get woven into email copy.
# Selected based on behavior_type + email_count in the sequence.
_BOOK_TECHNIQUES = {
    "never_split_the_difference": {
        "name": "Never Split the Difference (Chris Voss)",
        "core_principle": "Tactical empathy and calibrated questions win negotiations",
        "techniques": {
            "calibrated_questions": [
                "How do you typically handle freight from {country}?",
                "What does your ideal freight partnership look like?",
                "How do you usually decide which forwarders to work with?",
                "What's the biggest challenge moving cargo from {country} right now?",
                "How does your team approach rate requests from new partners?",
                "What would need to be true for this to work for you?",
                "How can we make this easy for your team?",
                "What's most important to you in a forwarding partner?",
            ],
            "labels": [
                "It seems like you value reliability above all else...",
                "It sounds like the {country} corridor is a key lane for you...",
                "It seems like you've been looking for a US partner who understands your market...",
                "It looks like timing matters a lot in your operation...",
                "It seems like you prefer partners who get straight to the point...",
                "It sounds like you've had mixed experiences with new forwarders...",
            ],
            "accusation_audits": [
                "You probably get a hundred partnership emails a week...",
                "You're probably thinking 'another forwarder who'll disappear after one quote'...",
                "We know you might be skeptical — everyone claims to be 'global'...",
                "You've probably heard every pitch in the book by now...",
                "We realize cold emails aren't anyone's favorite thing...",
                "You might be wondering why another US forwarder is reaching out...",
            ],
        },
    },
    "how_to_win_friends": {
        "name": "How to Win Friends and Influence People (Dale Carnegie)",
        "core_principle": "Genuine interest in others is the foundation of influence",
        "techniques": {
            "talk_their_market": [
                "The {country} freight market has been fascinating to watch this year.",
                "We've been following the growth in {country}'s export volumes closely.",
                "{country} is one of the most dynamic freight corridors we work with.",
                "The shipping landscape out of {country} keeps getting more interesting.",
                "Every time we look at {country}, we see opportunity.",
            ],
            "genuine_questions": [
                "What lanes are you seeing the most movement on right now?",
                "How has the market been treating you lately?",
                "What's your team's strongest corridor?",
                "Are you seeing any shifts in cargo volumes from your region?",
                "What's your take on the current freight market in {country}?",
            ],
            "make_them_important": [
                "Your expertise in the {country} market is exactly what we need.",
                "We specifically sought out agents with your kind of local knowledge.",
                "Your operation in {city} gives you an edge that's hard to match.",
                "Agents like you are the backbone of global freight — we don't forget that.",
                "We're selective about who we partner with — your company stood out.",
            ],
        },
    },
    "influence": {
        "name": "Influence: The Psychology of Persuasion (Robert Cialdini)",
        "core_principle": "Six weapons of influence drive human decision-making",
        "techniques": {
            "social_proof": [
                "We work with freight agents across 40+ countries.",
                "Our network spans 6 continents and over 400 active partners.",
                "Hundreds of agents already receive our rate rounds.",
                "Agents in {country} have been some of our most active partners.",
                "Our partners consistently tell us we're the easiest team to work with.",
                "Last month alone, we processed rate requests from 35 countries.",
                "Our {country} corridor has grown 40% year over year.",
                "More agents joined our network last quarter than any previous period.",
            ],
            "reciprocity": [
                "We can share market insights on the {country} to US corridor anytime.",
                "We'll send you lane benchmarks so you know where your rates stand.",
                "Happy to share what we're seeing on freight volumes from your region.",
                "We publish bi-weekly rate trend reports — happy to include you.",
                "We'll add you to our market intelligence updates — no strings attached.",
                "Here's what we're seeing on the {country} to US West Coast lane this month.",
            ],
            "scarcity": [
                "Our next rate round closes this Friday.",
                "We're finalizing our {country} partner list this week.",
                "Spots for new agents in this rate cycle are limited.",
                "We're locking in partners for the next quarter — timing is now.",
                "This rate round is closing soon — don't want you to miss it.",
            ],
            "authority": [
                "Our US West Coast team processes 500+ containers monthly.",
                "We've been in the freight forwarding business for over a decade.",
                "Our pricing team analyzes thousands of rate submissions every cycle.",
                "We handle some of the most complex multi-modal shipments in the industry.",
                "Our compliance and documentation team ensures zero delays at US customs.",
            ],
        },
    },
    "atomic_habits": {
        "name": "Atomic Habits (James Clear)",
        "core_principle": "Make the desired behavior easy, obvious, attractive, and satisfying",
        "techniques": {
            "make_it_easy": [
                "One click and you're done — no forms, no calls.",
                "Takes under 60 seconds — just pick your lanes and confirm.",
                "No signup, no login, no meeting — just click and respond.",
                "We've made this as simple as possible — one button, done.",
                "Reply with your rates — that's literally all we need.",
            ],
            "make_it_obvious": [
                "Here's exactly what we need: your best rates for the lanes below.",
                "Three steps: 1) Check the lanes. 2) Send rates. 3) Get cargo.",
                "The next step is simple — reply with your numbers.",
                "What we need is clear: rates for these lanes, in USD per container.",
            ],
            "make_it_attractive": [
                "Once you're in our system, cargo inquiries come to you automatically.",
                "Agents who respond to our rate rounds get first priority on bookings.",
                "You send rates, we send cargo — it's that straightforward.",
                "Our most active partners tell us it's the easiest volume they get.",
            ],
            "make_it_satisfying": [
                "As soon as we hear back, you're on the list for our next cargo round.",
                "You'll receive a confirmation and your first cargo inquiry within days.",
                "Once confirmed, we'll match you with live cargo immediately.",
                "Reply and you're in — we'll start routing inquiries your way.",
            ],
        },
    },
    "seven_habits": {
        "name": "The 7 Habits of Highly Effective People (Stephen Covey)",
        "core_principle": "Effectiveness comes from character, proactivity, and mutual benefit",
        "techniques": {
            "seek_first_to_understand": [
                "Before we talk rates — what lanes matter most to your operation?",
                "We'd rather understand your business first than jump straight to pricing.",
                "What's your team focused on this quarter?",
                "We like to learn how our partners operate before we start sending requests.",
                "Tell us about your strongest corridors — we'll match accordingly.",
            ],
            "think_win_win": [
                "This works best when both sides win — and we're set up for that.",
                "Our model is simple: we bring the cargo, you bring the local expertise.",
                "We're not looking for vendors — we're looking for real partners.",
                "When you grow, we grow. That's how we see this.",
                "A good partnership means consistent volume for you and reliable service for us.",
            ],
            "be_proactive": [
                "We're reaching out before the next cargo wave hits your corridor.",
                "We like to have partners in place before demand spikes — not after.",
                "Proactive partnerships beat reactive ones every time.",
                "We're building our {country} network now — ahead of peak season.",
            ],
        },
    },
    "think_and_grow_rich": {
        "name": "Think and Grow Rich (Napoleon Hill)",
        "core_principle": "Definiteness of purpose, burning desire, and mastermind alliances",
        "techniques": {
            "definiteness_of_purpose": [
                "We have one goal: build the best freight agent network in the world.",
                "Here's exactly what we need from you: rates for these lanes.",
                "Our mission is simple — connect the best agents with real cargo.",
                "We know exactly what we're looking for: a reliable partner in {country}.",
            ],
            "burning_desire": [
                "We're actively building something special — and {country} is a key piece.",
                "This isn't just another email blast — we chose your company specifically.",
                "We're passionate about getting this right — the right partner matters more than the fastest one.",
                "We've been planning our {country} expansion carefully — your name keeps coming up.",
            ],
            "mastermind": [
                "Join our network of top-tier agents across 40+ countries.",
                "Our best partnerships feel like a mastermind — we share insights, market data, and opportunities.",
                "You'd be joining a network where agents help each other win.",
                "The agents in our network don't just get cargo — they get market intelligence.",
            ],
        },
    },
}


# ── Response quality signal detection ─────────────────────────────────────
# Analyzes reply content to detect engagement level beyond just response time.
_RESPONSE_QUALITY_SIGNALS = {
    "partial_reply": {
        "psychology": "Interested but guarded — testing the waters",
        "strategy": "Thank them, fill gaps yourself, make next step even easier",
        "next_behavior_adjust": "cautious",
    },
    "detailed_reply": {
        "psychology": "Engaged, wants partnership — mirror their effort level",
        "strategy": "Match their detail level, show appreciation, escalate to call",
        "next_behavior_adjust": "engaged",
    },
    "hostile_reply": {
        "psychology": "Pitched too many times — respect the boundary",
        "strategy": "Acknowledge, differentiate, one final soft touch then stop",
        "next_behavior_adjust": "skeptical",
    },
    "question_reply": {
        "psychology": "Curious, needs information — they're interested but need proof",
        "strategy": "Answer completely, include social proof, easy CTA",
        "next_behavior_adjust": "thoughtful",
    },
    "forwarded_reply": {
        "psychology": "Interested — moving it to the right person internally",
        "strategy": "Thank them, address the new person warmly, re-introduce briefly",
        "next_behavior_adjust": "engaged",
    },
    "delayed_interest": {
        "psychology": "Interested but was genuinely unavailable — not disengaged",
        "strategy": "Warm response, no guilt, make re-entry easy",
        "next_behavior_adjust": "cautious",
    },
}


def classify_response_quality(reply_text):
    """
    Analyze a reply to detect engagement quality signals.
    Returns the signal dict with psychology/strategy/adjustment, or None.
    """
    if not reply_text:
        return None
    text = reply_text.lower().strip()

    # Check hostile first (highest priority)
    hostile_kws = ["not interested", "stop emailing", "unsubscribe", "remove me",
                   "do not contact", "no thanks", "don't email", "take me off",
                   "opt out", "leave me alone"]
    if any(kw in text for kw in hostile_kws):
        return _RESPONSE_QUALITY_SIGNALS["hostile_reply"]

    # Forwarded
    forward_kws = ["forwarded", "copying my", "cc'd", "passed to", "introduced you to",
                   "looping in", "adding my colleague"]
    if any(kw in text for kw in forward_kws):
        return _RESPONSE_QUALITY_SIGNALS["forwarded_reply"]

    # Delayed interest
    delay_kws = ["sorry for the delay", "just seeing this", "been traveling",
                 "was on leave", "apologies for the late", "just got back"]
    if any(kw in text for kw in delay_kws):
        return _RESPONSE_QUALITY_SIGNALS["delayed_interest"]

    # Question reply
    question_kws = ["what rates", "which lanes", "tell me more", "what do you offer",
                    "what services", "how does it work", "can you explain", "interested to know"]
    if any(kw in text for kw in question_kws):
        return _RESPONSE_QUALITY_SIGNALS["question_reply"]

    # Detailed reply (long, structured)
    if len(text) > 200 or text.count("\n") > 5:
        return _RESPONSE_QUALITY_SIGNALS["detailed_reply"]

    # Partial reply (short, some info)
    if 20 < len(text) < 200:
        return _RESPONSE_QUALITY_SIGNALS["partial_reply"]

    return None


# ── Psychological email elements (book-driven) ────────────────────────────
# These get injected into emails based on behavior type and email sequence.

def get_psych_elements(contact, behavior, email_count, email_stage=None):
    """
    Generate psychological email elements based on behavior type, email position,
    and — critically — the EMAIL STAGE in the relationship.

    email_stage controls which techniques are allowed:
      "intro"          — first contact, they don't know us
      "follow_up"      — they opened but didn't respond (email 2)
      "engaged"        — they responded at least once (email 3+)
      "re_engagement"  — ghost, no reply after 2+ emails

    If email_stage is None, it is inferred from email_count and behavior.

    Stage rules (ENFORCED — not optional):
      INTRO:         social_proof, make_easy, make_obvious only.
                     NO calibrated_q, labels, accusation audit, scarcity, win-win.
      FOLLOW_UP:     + win_win, value_offer (reciprocity), proactive hooks.
                     NO calibrated_q, accusation audit, scarcity.
      ENGAGED:       + calibrated_q, labels, authority, definiteness.
      RE_ENGAGEMENT: + accusation audit, scarcity, pattern interrupt.

    Returns dict with: opening_hook, social_proof, calibrated_q, value_offer,
    motto_line, behavior, profile, book_technique, label_line, win_win_line,
    scarcity_line, make_easy_line
    (Banned keys for a stage are set to None so callers don't accidentally use them.)
    """
    contact_id = contact.get("id", 0)
    country = (contact.get("country") or "").strip()
    city = (contact.get("city") or "").strip()
    company = (contact.get("company_name") or "").strip()
    name = (contact.get("contact_name") or "").strip().split()[0] if contact.get("contact_name") else ""
    email = (contact.get("email") or "").strip()

    _seed = hash(f"psych-{contact_id}-{email}-{date.today().isoformat()}")
    _rng = random.Random(_seed)

    # ── Infer email stage if not explicitly provided ─────────────────────────
    if email_stage is None:
        if behavior == "ghost":
            email_stage = "re_engagement"
        elif email_count == 0:
            email_stage = "intro"
        elif email_count == 1:
            email_stage = "follow_up"
        else:
            email_stage = "engaged"

    motto = get_country_motto(country)
    country_display = country or "your market"
    city_display = city or "your city"

    # ── Opening hooks — varies by behavior type ──────────────────────────────
    _HOOKS = {
        "decisive": [
            "Straight to the point — we know your time is valuable.",
            "No long preamble — here\u2019s exactly what we need.",
            "You move fast, so will we.",
            "Quick and direct — the way it should be.",
            "Cutting right to it — here\u2019s why we\u2019re writing.",
        ],
        "engaged": [
            f"We\u2019ve been watching the {country_display} freight corridor closely.",
            f"The {country_display} market is moving — and we want to move with you.",
            "We see strong potential for a data-driven partnership here.",
            f"The numbers on the {country_display} corridor speak for themselves.",
            f"We\u2019ve been tracking volume trends from {country_display} — impressive growth.",
        ],
        "thoughtful": [
            "Agents in over 40 countries already trust us with their lanes.",
            "Our US West Coast team handles 500+ containers monthly — and growing.",
            "We\u2019ve built our network one great partner at a time.",
            "Our track record speaks louder than any pitch.",
            "The agents in our network stay because the partnership works.",
        ],
        "cautious": [
            "We know trust is earned, not assumed — especially in freight.",
            "Before we talk rates, we\u2019d like to understand how you operate.",
            "We believe the best partnerships start with listening.",
            "No pressure, no rush — we\u2019re here when the timing is right.",
            "We\u2019d rather build a real relationship than rush into transactions.",
        ],
        "busy": [
            "This will take 30 seconds — one click and you\u2019re done.",
            "We\u2019ll keep this short — we know you\u2019re busy.",
            "Quick one for you — no meeting, no call, just one click.",
            "15-second read. One ask. Done.",
            "Shortest email you\u2019ll get today — promise.",
        ],
        "skeptical": [
            "You probably get a hundred of these emails — we get it.",
            "We know you\u2019ve heard it all before. This is different.",
            "Not another generic pitch — here\u2019s why we\u2019re reaching out specifically to you.",
            "We\u2019re not going to pretend we\u2019re the only option — but we might be the right one.",
            "Before you delete this — 30 seconds. That\u2019s all we ask.",
        ],
        "ghost": [
            "We noticed you haven\u2019t had a chance to respond — no pressure at all.",
            "Different approach this time — just one question.",
            "We\u2019re not going anywhere — whenever the timing is right for you.",
            "Last thing we want is to be noise in your inbox. So here\u2019s something different.",
            "Changing gears — forget everything we\u2019ve said before. Just one question.",
        ],
        "unknown": [
            f"We\u2019re reaching out to select agents in {country_display} — you made the list.",
            f"Your company caught our eye while mapping freight partners in {country_display}.",
            "We\u2019re particular about who we work with — and you stood out.",
            f"Looking for the right partner in {country_display} — and your name came up.",
            f"We\u2019ve been building our {country_display} network carefully. Your company fits.",
        ],
    }

    # ── Social proof lines (Influence — Cialdini) ────────────────────
    _SOCIAL_PROOF = [
        "We work with freight agents across 40+ countries.",
        "Our network spans 6 continents and growing.",
        "Hundreds of agents already receive our rate rounds.",
        f"We\u2019re actively moving cargo through {country_display} every month.",
        "Our partners consistently tell us: \u201Cyou\u2019re the easiest team to work with.\u201D",
        f"Agents in {country_display} have been some of our most responsive partners.",
        "Last month alone, we processed rate requests from 35 countries.",
        "More agents joined our network last quarter than any previous period.",
        f"Our {country_display} corridor has grown 40% year over year.",
        "Over 400 freight agents worldwide trust us with their lanes.",
    ]

    # ── Calibrated questions (Never Split the Difference) ────────────────
    _CALIBRATED_QS = [
        f"How does your team typically handle US-bound freight from {country_display}?",
        "What\u2019s your biggest challenge with international rate requests right now?",
        f"What would make a freight partnership from {country_display} actually worth your time?",
        "What does your ideal cargo flow look like?",
        "How do you usually decide which forwarders to work with?",
        f"What\u2019s the biggest bottleneck moving cargo out of {country_display}?",
        "How does your team prioritize rate requests when they come in?",
        "What would need to change for you to try a new freight partner?",
    ]

    # ── Value offers (Reciprocity — give before asking) ──────────────────
    _VALUE_OFFERS = [
        f"We can share market insights on the {country_display} to US corridor anytime.",
        "We\u2019ll send you lane benchmarks so you know where your rates stand.",
        "Happy to share what we\u2019re seeing on freight volumes from your region.",
        "We publish bi-weekly rate trend reports — happy to include you.",
        f"We\u2019ll add you to our {country_display} market intelligence updates — no strings.",
        "We share lane-specific volume data with our partners every month.",
    ]

    # ── Label lines (Never Split — tactical empathy) ──────────────────
    _LABELS = [
        f"It seems like the {country_display} corridor is a key lane for you...",
        "It sounds like you value reliability above all else...",
        f"It looks like you\u2019ve been looking for a US partner who gets {country_display}...",
        "It seems like timing matters a lot in your operation...",
        "It sounds like you prefer partners who get straight to the point...",
    ]

    # ── Win-win lines (7 Habits) ───────────────────────────────────
    _WIN_WIN = [
        "This works best when both sides win — and we\u2019re set up for that.",
        "We bring the cargo, you bring the local expertise. Simple.",
        "We\u2019re not looking for vendors — we\u2019re looking for real partners.",
        "When you grow, we grow. That\u2019s how we see this.",
    ]

    # ── Scarcity lines (Influence) ──────────────────────────────────
    _SCARCITY = [
        "Our next rate round closes this Friday.",
        f"We\u2019re finalizing our {country_display} partner list this week.",
        "Spots for new agents in this rate cycle are limited.",
        "We\u2019re locking in partners for the next quarter — timing is now.",
    ]

    # ── Make-it-easy lines (Atomic Habits) ────────────────────────────
    _MAKE_EASY = [
        "One click and you\u2019re done — no forms, no calls.",
        "Takes under 60 seconds — just pick your lanes and confirm.",
        "No signup, no login, no meeting — just click and respond.",
        "Reply with your rates — that\u2019s literally all we need.",
    ]

    # ── Motto integration lines ──────────────────────────────────────
    motto_line = None
    if motto:
        _MOTTO_LINES = [
            f"As they say in {country_display}: <em>\u201C{motto['original']}\u201D</em> — {motto['translation']}. That\u2019s the spirit we bring to every partnership.",
            f"<em>\u201C{motto['translation']}\u201D</em> — a principle we share.",
            f"In the spirit of <em>\u201C{motto['original']}\u201D</em> — let\u2019s build something together.",
            f"We believe in \u201C{motto['translation']}\u201D — {motto['theme']} is at the heart of what we do.",
            f"Your national spirit of {motto['theme']} is something we admire and share.",
        ]
        motto_line = _rng.choice(_MOTTO_LINES)

    hooks = _HOOKS.get(behavior, _HOOKS["unknown"])

    # ── Stage-based technique filtering ──────────────────────────────────────
    # Build the full pool, then NULL out anything banned for this stage.
    # This makes it IMPOSSIBLE for callers to accidentally use a banned technique.
    result = {
        "opening_hook":  _rng.choice(hooks),
        "social_proof":  _rng.choice(_SOCIAL_PROOF),
        "calibrated_q":  _rng.choice(_CALIBRATED_QS),
        "value_offer":   _rng.choice(_VALUE_OFFERS),
        "motto_line":    motto_line,
        "behavior":      behavior,
        "email_stage":   email_stage,
        "profile":       _BEHAVIOR_PROFILES.get(behavior, _BEHAVIOR_PROFILES["unknown"]),
        "label_line":    _rng.choice(_LABELS),
        "win_win_line":  _rng.choice(_WIN_WIN),
        "scarcity_line": _rng.choice(_SCARCITY),
        "make_easy_line": _rng.choice(_MAKE_EASY),
    }

    if email_stage == "intro":
        # ALLOWED: social_proof, make_easy_line, opening_hook (unknown/neutral only)
        # BANNED: calibrated_q, label_line, scarcity_line, win_win_line, value_offer, motto
        # Motto feels forced in a cold email — only use in follow-up+ once there is a relationship.
        result["calibrated_q"]  = None
        result["label_line"]    = None
        result["scarcity_line"] = None
        result["win_win_line"]  = None
        result["value_offer"]   = None
        result["motto_line"]    = None
        # Force opening hook to intro-safe pool (no accusation audit, no empathy)
        _INTRO_HOOKS = [
            f"We're reaching out to select agents in {country_display} — you made the list.",
            f"Your company caught our eye while mapping freight partners in {country_display}.",
            "We're particular about who we work with — and you stood out.",
            f"Looking for the right partner in {country_display} — and your name came up.",
            f"We've been building our {country_display} network carefully. Your company fits.",
        ]
        result["opening_hook"] = _rng.choice(_INTRO_HOOKS)

    elif email_stage == "follow_up":
        # ALLOWED: social_proof, make_easy_line, win_win_line, value_offer, opening_hook
        # BANNED: calibrated_q, label_line, scarcity_line
        result["calibrated_q"]  = None
        result["label_line"]    = None
        result["scarcity_line"] = None

    elif email_stage == "engaged":
        # ALLOWED: everything EXCEPT scarcity (that's for re-engagement)
        result["scarcity_line"] = None

    elif email_stage == "re_engagement":
        # ALLOWED: everything — scarcity, accusation audit (via hooks), pattern interrupt
        pass  # all techniques available

    return result

def get_cultural_line(contact_id, country):
    """
    Return a cultural opening line for this contact.
    Rotates through the pool so the same line isn't reused.
    Returns None if all lines have been used (stops repeating).
    """
    pool = _CULTURAL_LINES.get((country or "").strip().lower(), _DEFAULT_CULTURAL_LINES)
    profile = get_or_create_profile(contact_id)
    used = json.loads(profile.get("cultural_lines_used") or "[]")

    # Find first unused line
    for line in pool:
        if line not in used:
            used.append(line)
            update_profile(
                contact_id,
                cultural_lines_used=json.dumps(used),
                last_cultural_line=line,
            )
            return line

    # All lines used — return None (caller will omit the cultural block)
    return None


def should_ask_interest(contact_id):
    """
    Returns True if it's time to ask the interest question.
    Rules: email_count >= 2, interest not yet captured, question not yet sent.
    """
    profile = get_or_create_profile(contact_id)
    if profile["interest_question_sent"]:
        return False
    interests = json.loads(profile.get("interests") or "[]")
    if interests:
        return False
    return profile["email_count"] >= 2


def get_interest_question(contact_id):
    """Return the interest question to append, mark as sent."""
    profile = get_or_create_profile(contact_id)
    used_count = profile.get("email_count", 0)
    question = _INTEREST_QUESTIONS[used_count % len(_INTEREST_QUESTIONS)]
    update_profile(
        contact_id,
        interest_question_sent=1,
        interest_question_at=_now_iso(),
    )
    return question


def store_interests(contact_id, interests_list):
    """Store confirmed interests from a parsed reply."""
    update_profile(
        contact_id,
        interests=json.dumps(interests_list),
        interests_updated_at=_now_iso(),
    )


def parse_interests_from_reply(reply_text):
    """
    Lightweight interest extractor — finds topics from a reply.
    Returns a list of interest strings.
    No AI needed — keyword matching covers 90% of cases.
    """
    text = reply_text.lower()
    found = []

    checks = [
        # Sports
        (["football", "soccer", "premier league", "champions league", "la liga", "serie a",
          "bundesliga", "ligue 1", "mls", "world cup"], "football"),
        (["cricket", "ipl", "test match", "odi", "t20"], "cricket"),
        (["basketball", "nba", "euroleague"], "basketball"),
        (["tennis", "wimbledon", "us open", "roland garros", "australian open"], "tennis"),
        (["formula 1", "f1", "motogp", "formula one"], "Formula 1"),
        (["golf", "pga", "masters", "ryder cup"], "golf"),
        (["rugby", "six nations", "world rugby"], "rugby"),
        (["cycling", "tour de france", "giro d'italia"], "cycling"),
        (["baseball", "mlb", "world series"], "baseball"),
        (["american football", "nfl", "super bowl"], "American football"),
        # Lifestyle
        (["cooking", "chef", "recipe", "cuisine", "food", "baking", "bbq", "grill"], "cooking"),
        (["travel", "travelling", "traveling", "backpacking", "exploring"], "travel"),
        (["reading", "books", "novels", "literature", "author", "fiction"], "reading"),
        (["music", "guitar", "piano", "concerts", "jazz", "classical", "rock", "hip hop"], "music"),
        (["art", "painting", "sculpture", "museum", "gallery", "drawing"], "art"),
        (["photography", "camera", "photos", "shooting"], "photography"),
        (["hiking", "trekking", "mountains", "trail"], "hiking"),
        (["fitness", "gym", "weightlifting", "crossfit", "running", "marathon"], "fitness"),
        (["yoga", "meditation", "mindfulness"], "yoga/meditation"),
        (["gaming", "video games", "esports", "playstation", "xbox", "pc gaming"], "gaming"),
        # Interests
        (["space", "nasa", "astronomy", "james webb", "telescope", "mars", "rockets",
          "spacex", "satellites"], "space/astronomy"),
        (["technology", "tech", "ai", "machine learning", "coding", "programming",
          "startups", "silicon valley"], "technology"),
        (["wine", "sommelier", "vineyard", "winery", "tasting"], "wine"),
        (["coffee", "espresso", "barista", "specialty coffee"], "coffee"),
        (["cars", "automobiles", "motorsport", "classic cars", "supercar"], "cars"),
        (["history", "archaeology", "ancient", "history books"], "history"),
        (["finance", "investing", "stocks", "crypto", "bitcoin", "markets"], "investing"),
        (["sailing", "yacht", "boats", "rowing"], "sailing"),
        (["diving", "scuba", "snorkeling", "ocean", "marine"], "diving"),
        (["chess", "board games", "strategy games"], "chess/board games"),
        (["family", "kids", "children", "parenting"], "family"),
    ]

    for keywords, label in checks:
        if any(kw in text for kw in keywords):
            if label not in found:
                found.append(label)

    return found


def fetch_interest_news(interests):
    """
    Fetch a current news snippet for each interest using DuckDuckGo Instant Answer API.
    Returns dict of {interest: snippet_or_None}.
    Free, no API key needed.
    """
    results = {}
    for interest in interests[:5]:  # cap at 5 to avoid slow sends
        try:
            query = urllib.parse.quote_plus(f"{interest} latest news 2025")
            url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "FreightDashboard/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            abstract = (data.get("AbstractText") or "").strip()
            if abstract and len(abstract) > 30:
                results[interest] = abstract[:200]
            else:
                results[interest] = None
        except Exception:
            results[interest] = None
    return results


def get_interest_opener(contact_id):
    """
    Build a personalized opening line based on confirmed interests + live news.
    Returns a string to prepend to the email body, or None if no interests on file.
    """
    profile = get_or_create_profile(contact_id)
    interests = json.loads(profile.get("interests") or "[]")
    if not interests:
        return None

    # Refresh news cache if older than 6 hours
    cache_str = profile.get("interest_news_cache") or "{}"
    fetched_at_str = profile.get("interest_news_fetched_at") or ""
    cache = json.loads(cache_str)
    needs_refresh = True
    if fetched_at_str:
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if datetime.now() - fetched_at < timedelta(hours=6):
                needs_refresh = False
        except Exception:
            pass

    if needs_refresh:
        cache = fetch_interest_news(interests)
        update_profile(
            contact_id,
            interest_news_cache=json.dumps(cache),
            interest_news_fetched_at=_now_iso(),
        )

    # Build opener from first interest that has news
    for interest in interests:
        snippet = cache.get(interest)
        if snippet:
            return (
                f"<p style='color:#555;font-size:13px;border-left:3px solid #0066cc;"
                f"padding-left:10px;margin-bottom:16px;'>"
                f"<em>We noticed you follow {interest} — {snippet[:150]}...</em></p>"
            )

    # Interests known but no live news — generic reference
    interest_str = " and ".join(interests[:2])
    return (
        f"<p style='color:#555;font-size:13px;border-left:3px solid #0066cc;"
        f"padding-left:10px;margin-bottom:16px;'>"
        f"<em>Hope things are going well on your end — both in freight and in {interest_str}.</em></p>"
    )


def build_email_context(contact):
    """
    Build full email context for a contact before drafting an email.
    Returns dict with: opener, cultural_line, interest_question, style, subject_tone.
    """
    contact_id = contact["id"]
    country    = contact.get("country", "")

    profile    = get_or_create_profile(contact_id)
    email_count = profile["email_count"]
    interests  = json.loads(profile.get("interests") or "[]")
    behavior   = profile.get("behavior_type", "unknown")
    style      = profile.get("email_style", "standard")
    subject_tone = profile.get("subject_tone", "functional")

    opener           = None
    cultural_line    = None
    interest_question = None

    if interests:
        # Email 3+: interest opener replaces cultural line
        opener = get_interest_opener(contact_id)
    elif email_count == 0:
        # Email 1: cultural/port line
        cultural_line = get_cultural_line(contact_id, country)
    # Email 2: no cultural line, but ask interest question below

    # Ask interest question from email 2 onwards (if not yet asked)
    if should_ask_interest(contact_id):
        interest_question = get_interest_question(contact_id)

    # Bump email count
    update_profile(
        contact_id,
        email_count=email_count + 1,
        last_contacted_at=_now_iso(),
    )

    # ── Derive email stage from email_count + behavior ──────────────────────
    if behavior == "ghost":
        email_stage = "re_engagement"
    elif email_count == 0:
        email_stage = "intro"
    elif email_count == 1:
        email_stage = "follow_up"
    else:
        email_stage = "engaged"

    # Build psychological elements based on behavior + email sequence + STAGE
    psych = get_psych_elements(contact, behavior, email_count, email_stage=email_stage)

    return {
        "opener":            opener,
        "cultural_line":     cultural_line,
        "interest_question": interest_question,
        "style":             style,
        "subject_tone":      subject_tone,
        "behavior":          behavior,
        "email_count":       email_count,
        "email_stage":       email_stage,
        "psych":             psych,
    }


def get_intelligence_card(contact_id):
    """
    Build the full intelligence briefing for a contact.
    Used by the dashboard and by humans before a call.
    """
    conn = get_db()

    contact = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if not contact:
        conn.close()
        return None
    contact = dict(contact)

    profile = get_or_create_profile(contact_id)

    interactions = conn.execute(
        """SELECT * FROM contact_interactions
           WHERE contact_id = ? ORDER BY sent_at DESC LIMIT 20""",
        (contact_id,),
    ).fetchall()
    interactions = [dict(i) for i in interactions]

    rates = conn.execute(
        """SELECT * FROM rates WHERE contact_id = ? ORDER BY received_at DESC LIMIT 10""",
        (contact_id,),
    ).fetchall()
    rates = [dict(r) for r in rates]

    conn.close()

    interests = json.loads(profile.get("interests") or "[]")
    interest_news = json.loads(profile.get("interest_news_cache") or "{}")
    behavior = profile.get("behavior_type", "unknown")
    avg_hours = profile.get("avg_response_hours")

    behavior_label = {
        "decisive":   "Decisive — replies within an hour. Keep emails short and direct. (7 Habits: Be Proactive)",
        "engaged":    "Engaged — responds same day. Data-driven, structured approach. (Think & Grow Rich)",
        "thoughtful": "Thoughtful — takes a day. Provide proof and social validation. (Influence)",
        "cautious":   "Cautious — takes 1-2 days. Warm, relationship-first. (Win Friends)",
        "busy":       "Busy — takes 2-3 days. Ultra-brief, remove all friction. (Atomic Habits)",
        "skeptical":  "Skeptical — 3+ days. Tactical empathy, pattern interrupt. (Never Split)",
        "ghost":      "Ghost — no response. Change the angle completely. (Power of Habit)",
        # Legacy mappings for backward compatibility
        "fast":     "Decisive responder — gets back quickly. Keep emails short and direct.",
        "balanced": "Engaged responder — replies within a day. Standard professional tone.",
        "relaxed":  "Thoughtful responder — takes 1-3 days. Warmer tone works well.",
        "slow":     "Skeptical or busy. Keep it pure business, short, no fluff.",
        "unknown":  "Response pattern not yet established.",
    }.get(behavior, "Unknown behavior pattern.")

    # Rate reliability
    total_rates = len(rates)
    complete_rates = sum(1 for r in rates if r.get("rate_20ft") and r.get("rate_40ft"))
    reliability = round((complete_rates / total_rates * 100) if total_rates else 0)

    # Interest current news
    interest_bullets = []
    for interest in interests:
        news = interest_news.get(interest)
        if news:
            interest_bullets.append(f"{interest}: {news[:120]}...")
        else:
            interest_bullets.append(f"{interest}: (no recent news cached)")

    # Last interaction summary
    last_interaction = interactions[0] if interactions else None

    return {
        "contact": {
            "id":           contact["id"],
            "name":         contact.get("contact_name", ""),
            "company":      contact.get("company_name", ""),
            "country":      contact.get("country", ""),
            "city":         contact.get("city", ""),
            "email":        contact.get("email", ""),
            "phone":        contact.get("phone_number", ""),
            "network":      contact.get("network", ""),
            "verified":     contact.get("verified_status", ""),
            "score":        contact.get("verified_score", 0),
            "website":      contact.get("website_url", ""),
            "linkedin":     contact.get("linkedin_url", ""),
        },
        "behavior": {
            "type":           behavior,
            "label":          behavior_label,
            "avg_hours":      round(avg_hours, 1) if avg_hours else None,
            "email_count":    profile["email_count"],
            "response_count": profile["response_count"],
            "last_contacted": profile.get("last_contacted_at", ""),
            "last_responded": profile.get("last_responded_at", ""),
        },
        "rates": {
            "total_received":   total_rates,
            "complete":         complete_rates,
            "reliability_pct":  reliability,
            "recent":           rates[:3],
        },
        "interests": {
            "confirmed":   interests,
            "news_bullets": interest_bullets,
        },
        "call_prep": _build_call_prep(contact, profile, interactions, rates, interests, interest_news),
    }


def _build_call_prep(contact, profile, interactions, rates, interests, interest_news):
    """Generate point-form call prep notes for a human agent."""
    lines = []

    name = contact.get("contact_name") or contact.get("company_name", "Contact")
    country = contact.get("country", "")
    behavior = profile.get("behavior_type", "unknown")
    avg_hours = profile.get("avg_response_hours")

    lines.append(f"WHO: {name} — {contact.get('company_name', '')} — {country}")
    lines.append(f"EMAIL: {contact.get('email', '')}  |  PHONE: {contact.get('phone_number', '')}")

    if avg_hours:
        lines.append(f"RESPONSE PATTERN: {behavior.upper()} — avg {round(avg_hours, 1)}h reply time")
    else:
        lines.append("RESPONSE PATTERN: Not yet established")

    if rates:
        latest = rates[0]
        lines.append(
            f"LAST RATE: {latest.get('origin','')} → {latest.get('destination','')} | "
            f"20ft: ${latest.get('rate_20ft','?')} | 40ft: ${latest.get('rate_40ft','?')} | "
            f"{latest.get('carrier','')}"
        )

    if interests:
        lines.append(f"INTERESTS: {', '.join(interests)}")
        for interest in interests[:2]:
            news = interest_news.get(interest)
            if news:
                lines.append(f"  — {interest} NOW: {news[:100]}...")

    if interactions:
        last = interactions[0]
        lines.append(f"LAST CONTACT: {last.get('sent_at','')[:10]} via {last.get('email_type','')}")

    lines.append(f"HISTORY: {profile['email_count']} emails sent | {profile['response_count']} responses")

    return lines


# ─────────────────────────────────────────────────────────────────────────────
#  Lane intelligence — origin country → destination regions
# ─────────────────────────────────────────────────────────────────────────────

_ORIGIN_LANES = {
    # Middle East / Turkey
    "turkey": ["USA", "Canada", "Mexico", "Brazil", "Colombia", "Argentina", "Chile", "Peru", "Middle East", "Europe"],
    "uae": ["USA", "Canada", "Europe", "South America", "Far East"],
    "united arab emirates": ["USA", "Canada", "Europe", "South America", "Far East"],
    "saudi arabia": ["USA", "Canada", "Europe", "South America", "Far East"],
    "qatar": ["USA", "Canada", "Europe", "South America", "Far East"],
    "kuwait": ["USA", "Canada", "Europe", "South America", "Far East"],
    # South Asia
    "india": ["USA", "Canada", "Europe", "Middle East", "South America", "Far East", "Africa"],
    "pakistan": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "sri lanka": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "bangladesh": ["USA", "Canada", "Europe", "Middle East"],
    # East Asia
    "china": ["USA", "Canada", "Europe", "Middle East", "South America", "Africa", "Australia"],
    "hong kong": ["USA", "Canada", "Europe", "Middle East", "South America", "Africa"],
    "taiwan": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "japan": ["USA", "Canada", "Europe", "Middle East", "South America", "Australia"],
    "south korea": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "korea": ["USA", "Canada", "Europe", "Middle East", "South America"],
    # Southeast Asia
    "singapore": ["USA", "Canada", "Europe", "Middle East", "South America", "Africa"],
    "malaysia": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "indonesia": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "thailand": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "vietnam": ["USA", "Canada", "Europe", "Middle East", "South America"],
    "philippines": ["USA", "Canada", "Europe", "Middle East", "South America"],
    # Europe
    "germany": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "france": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "italy": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "spain": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "netherlands": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "belgium": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "poland": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "greece": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "portugal": ["USA", "Canada", "Middle East", "Far East", "South America", "Africa"],
    "switzerland": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "austria": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "sweden": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "denmark": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "norway": ["USA", "Canada", "Middle East", "Far East", "South America"],
    "finland": ["USA", "Canada", "Middle East", "Far East", "South America"],
    # Americas
    "brazil": ["USA", "Canada", "Europe", "Middle East", "Far East", "Africa"],
    "colombia": ["USA", "Canada", "Europe", "Middle East", "Far East", "South America"],
    "argentina": ["USA", "Canada", "Europe", "Middle East", "Far East"],
    "chile": ["USA", "Canada", "Europe", "Middle East", "Far East"],
    "peru": ["USA", "Canada", "Europe", "Middle East", "Far East"],
    "mexico": ["USA", "Canada", "Europe", "Middle East", "Far East", "South America"],
    # Africa
    "south africa": ["USA", "Canada", "Europe", "Middle East", "Far East"],
    "nigeria": ["USA", "Canada", "Europe", "Middle East"],
    "kenya": ["USA", "Canada", "Europe", "Middle East"],
    "egypt": ["USA", "Canada", "Europe", "Middle East", "Far East"],
    # Oceania
    "australia": ["USA", "Canada", "Europe", "Middle East", "Far East", "South America"],
    "new zealand": ["USA", "Canada", "Europe", "Middle East", "Far East"],
}


def get_lanes_for_country(country: str) -> list:
    """Return list of destination regions for a given origin country."""
    if not country:
        return ["USA", "Canada", "Europe", "Middle East", "Far East", "South America"]
    return _ORIGIN_LANES.get(country.strip().lower(),
                              ["USA", "Canada", "Europe", "Middle East", "Far East", "South America"])
