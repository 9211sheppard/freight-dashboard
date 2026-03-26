import sqlite3
import os
import re
from config import DB_PATH, DATABASE_URL

# ── Postgres availability ────────────────────────────────────────────────────
_USE_POSTGRES = bool(DATABASE_URL)
if _USE_POSTGRES:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("[db] WARNING: DATABASE_URL set but psycopg2 not installed — falling back to SQLite")
        _USE_POSTGRES = False


class _DictRow(dict):
    """Lightweight dict subclass that supports both dict-style and attribute access,
    matching sqlite3.Row interface used throughout the codebase."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

    def keys(self):
        return super().keys()


def _sqlite_to_pg(sql):
    """Translate SQLite SQL to PostgreSQL dialect on the fly."""
    s = sql
    # AUTOINCREMENT → GENERATED ALWAYS AS IDENTITY (or just SERIAL)
    s = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', s, flags=re.IGNORECASE)
    # PRAGMA statements → skip (handled separately)
    if s.strip().upper().startswith('PRAGMA'):
        return None
    # datetime('now') → NOW()
    s = re.sub(r"datetime\('now'\)", 'NOW()', s, flags=re.IGNORECASE)
    # ? → %s for parameter placeholders
    s = s.replace('?', '%s')
    return s


class _PgConnectionWrapper:
    """Wraps a psycopg2 connection to provide an sqlite3-compatible interface."""

    def __init__(self, conn):
        self._conn = conn
        self._conn.autocommit = False

    def execute(self, sql, params=None):
        translated = _sqlite_to_pg(sql)
        if translated is None:
            return _EmptyCursor()
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(translated, params or ())
        return _PgCursorWrapper(cur)

    def executemany(self, sql, params_list):
        translated = _sqlite_to_pg(sql)
        if translated is None:
            return
        cur = self._conn.cursor()
        cur.executemany(translated, params_list)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class _PgCursorWrapper:
    """Wraps psycopg2 cursor to return _DictRow objects like sqlite3.Row."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _DictRow(row)

    def fetchall(self):
        return [_DictRow(r) for r in self._cursor.fetchall()]

    @property
    def lastrowid(self):
        try:
            self._cursor.execute("SELECT lastval()")
            return self._cursor.fetchone()['lastval']
        except Exception:
            return None

    @property
    def rowcount(self):
        return self._cursor.rowcount


class _EmptyCursor:
    """No-op cursor for skipped PRAGMA statements."""
    def fetchone(self): return None
    def fetchall(self): return []
    lastrowid = None
    rowcount = 0


def get_db():
    """Open a database connection — PostgreSQL if DATABASE_URL is set, else SQLite."""
    if _USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return _PgConnectionWrapper(conn)
    else:
        os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn


def _get_existing_columns(conn, table_name):
    """Get existing column names for a table — works with both SQLite and Postgres."""
    if _USE_POSTGRES:
        cur = conn._conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,)
        )
        return {row[0] for row in cur.fetchall()}
    else:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def init_tenants_db():
    """Create the tenants table — foundation of multi-tenancy."""
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            slug            TEXT    UNIQUE NOT NULL,
            plan            TEXT    DEFAULT 'trial',
            stripe_customer_id   TEXT DEFAULT '',
            stripe_subscription_id TEXT DEFAULT '',
            trial_ends_at   TEXT    DEFAULT '',
            subscription_status TEXT DEFAULT 'trialing',
            max_users       INTEGER DEFAULT 10,
            max_contacts    INTEGER DEFAULT 5000,
            created_at      TEXT    DEFAULT '',
            updated_at      TEXT    DEFAULT ''
        )
    """)

    # System health / support tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER,
            user_id         INTEGER,
            category        TEXT    DEFAULT 'general',
            subject         TEXT    DEFAULT '',
            description     TEXT    DEFAULT '',
            status          TEXT    DEFAULT 'open',
            priority        TEXT    DEFAULT 'normal',
            auto_resolved   INTEGER DEFAULT 0,
            resolution_note TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT '',
            resolved_at     TEXT    DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_health_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            check_type      TEXT    NOT NULL,
            status          TEXT    DEFAULT 'ok',
            details         TEXT    DEFAULT '',
            checked_at      TEXT    DEFAULT ''
        )
    """)

    # ── Referral tracking ─────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_tenant_id  INTEGER NOT NULL,
            referrer_user_id    INTEGER NOT NULL,
            referral_code       TEXT    UNIQUE NOT NULL,
            referred_email      TEXT    DEFAULT '',
            referred_tenant_id  INTEGER DEFAULT NULL,
            status              TEXT    DEFAULT 'pending',
            free_month_applied  INTEGER DEFAULT 0,
            created_at          TEXT    DEFAULT '',
            converted_at        TEXT    DEFAULT ''
        )
    """)

    # ── Spin-to-win results ───────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS spin_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            prize_type      TEXT    NOT NULL,
            prize_value     TEXT    NOT NULL,
            discount_pct    INTEGER DEFAULT 0,
            free_months     INTEGER DEFAULT 0,
            applied         INTEGER DEFAULT 0,
            created_at      TEXT    DEFAULT ''
        )
    """)

    # ── Admin activity log ────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_activity_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            action          TEXT    NOT NULL,
            details         TEXT    DEFAULT '',
            admin_user_id   INTEGER,
            created_at      TEXT    DEFAULT ''
        )
    """)

    # ── Pitch scores (adaptive presentation feedback) ─────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pitch_scores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_name    TEXT    DEFAULT '',
            profession_key  TEXT    DEFAULT '',
            profession_label TEXT   DEFAULT '',
            score           INTEGER DEFAULT 5,
            risk_answer     TEXT    DEFAULT '',
            advice_answer   TEXT    DEFAULT '',
            fund_answer     TEXT    DEFAULT '',
            scoring_answers TEXT    DEFAULT '',
            ip_address      TEXT    DEFAULT '',
            user_agent      TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT ''
        )
    """)

    conn.commit()
    conn.close()


def init_db():
    """Create the contacts table and migrate any missing columns."""
    if not _USE_POSTGRES:
        os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            network      TEXT    DEFAULT '',
            company_name TEXT,
            contact_name TEXT    DEFAULT '',
            email        TEXT,
            phone_number TEXT,
            country      TEXT,
            city         TEXT    DEFAULT ''
        )
    """)

    # Auto-migration: add new columns to existing databases without breaking them
    existing = _get_existing_columns(conn, "contacts")
    migrations = [
        ("tenant_id",       "INTEGER DEFAULT 1"),
        ("network",         "TEXT    DEFAULT ''"),
        ("contact_name",    "TEXT    DEFAULT ''"),
        ("city",            "TEXT    DEFAULT ''"),
        ("verified_status", "TEXT    DEFAULT 'unverified'"),
        ("verified_score",  "INTEGER DEFAULT 0"),
        ("verified_date",   "TEXT    DEFAULT ''"),
        ("website_url",     "TEXT    DEFAULT ''"),
        ("linkedin_url",    "TEXT    DEFAULT ''"),
        ("verify_notes",    "TEXT    DEFAULT ''"),
        # Legal compliance fields
        ("data_source",     "TEXT    DEFAULT ''"),      # where the contact was obtained (e.g., 'fiata_public', 'user_import', 'manual')
        ("data_source_type","TEXT    DEFAULT 'unknown'"),# 'public_directory', 'user_import', 'manual_entry', 'partnership'
        ("opt_out",         "INTEGER DEFAULT 0"),       # 1 = contact has opted out of communications
        ("opt_out_date",    "TEXT    DEFAULT ''"),       # when they opted out
        ("consent_basis",   "TEXT    DEFAULT ''"),       # GDPR lawful basis: 'legitimate_interest', 'consent', 'contract'
    ]
    for col, definition in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE contacts ADD COLUMN {col} {definition}")

    conn.commit()
    conn.close()



def init_lanes_db():
    """Create the lanes table in the same SQLite database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lanes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            lane_key     TEXT,
            origin_name  TEXT,
            destination_name TEXT,
            lane_status  TEXT,
            last_checked TEXT,
            sailing_id   TEXT,
            etd          TEXT,
            eta          TEXT,
            vessel       TEXT,
            transit      TEXT,
            route        TEXT,
            booking_url  TEXT
        )
    """)
    conn.commit()
    conn.close()


def init_rates_db():
    """Create rate system tables: rate_cycles, rate_outreach, rates, rate_gaps.
    Also keeps legacy rate_requests table for backward compat."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()

    # ── New cycle-based schema ─────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_cycles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_name      TEXT,
            valid_from      TEXT,
            valid_to        TEXT,
            send_date       TEXT,
            reminder_hours  INTEGER DEFAULT 24,
            status          TEXT    DEFAULT 'pending'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_outreach (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id         INTEGER,
            contact_id       INTEGER,
            contact_email    TEXT    DEFAULT '',
            contact_company  TEXT    DEFAULT '',
            contact_country  TEXT    DEFAULT '',
            contact_network  TEXT    DEFAULT '',
            lanes_requested  TEXT    DEFAULT '[]',
            sent_at          TEXT    DEFAULT '',
            reminded_at      TEXT    DEFAULT '',
            responded_at     TEXT    DEFAULT '',
            status           TEXT    DEFAULT 'pending',
            response_raw     TEXT    DEFAULT '',
            gap_flags        TEXT    DEFAULT '[]'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS rates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            cycle_id     INTEGER,
            contact_id   INTEGER,
            carrier      TEXT    DEFAULT '',
            origin       TEXT    DEFAULT '',
            destination  TEXT    DEFAULT '',
            rate_20ft    REAL,
            rate_40ft    REAL,
            valid_from   TEXT    DEFAULT '',
            valid_to     TEXT    DEFAULT '',
            etd          TEXT    DEFAULT '',
            vessel       TEXT    DEFAULT '',
            service      TEXT    DEFAULT '',
            currency     TEXT    DEFAULT 'USD',
            received_at  TEXT    DEFAULT '',
            verified     INTEGER DEFAULT 0,
            notes        TEXT    DEFAULT '',
            raw_text     TEXT    DEFAULT '',
            -- legacy compat columns kept for old rate_engine functions
            source_email TEXT    DEFAULT '',
            parsed_at    TEXT    DEFAULT '',
            cycle        TEXT    DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_gaps (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id   INTEGER,
            region       TEXT    DEFAULT '',
            gap_field    TEXT    DEFAULT '',
            occurrences  INTEGER DEFAULT 1,
            last_seen    TEXT    DEFAULT ''
        )
    """)

    # ── Legacy table kept for old rate_engine send/remind functions ────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_requests (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id       INTEGER REFERENCES contacts(id),
            sent_at          TEXT    DEFAULT '',
            cycle            TEXT    DEFAULT '',
            lanes_requested  TEXT    DEFAULT '[]',
            reminder_sent    INTEGER DEFAULT 0,
            responded        INTEGER DEFAULT 0,
            response_at      TEXT    DEFAULT '',
            response_quality INTEGER DEFAULT 0
        )
    """)

    # ── Auto-migrate rates table if legacy columns missing ─────────────────
    rate_cols = _get_existing_columns(conn, "rates")
    rate_migrations = [
        ("tenant_id",   "INTEGER DEFAULT 1"),
        ("cycle_id",    "INTEGER"),
        ("etd",         "TEXT DEFAULT ''"),
        ("vessel",      "TEXT DEFAULT ''"),
        ("service",     "TEXT DEFAULT ''"),
        ("received_at", "TEXT DEFAULT ''"),
        ("raw_text",    "TEXT DEFAULT ''"),
        ("source_email","TEXT DEFAULT ''"),
        ("parsed_at",   "TEXT DEFAULT ''"),
        ("cycle",       "TEXT DEFAULT ''"),
    ]
    for col, definition in rate_migrations:
        if col not in rate_cols:
            conn.execute(f"ALTER TABLE rates ADD COLUMN {col} {definition}")

    # ── Auto-migrate rate_gaps if it has old schema ────────────────────────
    gap_cols = _get_existing_columns(conn, "rate_gaps")
    gap_migrations = [
        ("region",      "TEXT DEFAULT ''"),
        ("gap_field",   "TEXT DEFAULT ''"),
        ("occurrences", "INTEGER DEFAULT 1"),
        ("last_seen",   "TEXT DEFAULT ''"),
    ]
    for col, definition in gap_migrations:
        if col not in gap_cols:
            conn.execute(f"ALTER TABLE rate_gaps ADD COLUMN {col} {definition}")

    conn.commit()
    conn.close()


def init_email_outreach_db():
    """Create the intro_outreach table for first-contact email tracking."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS intro_outreach (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id          INTEGER NOT NULL,
            email               TEXT    NOT NULL,
            sender_name         TEXT    DEFAULT '',
            country             TEXT    DEFAULT '',
            sent_at             TEXT    DEFAULT '',
            status              TEXT    DEFAULT 'sent',
            reply_received      INTEGER DEFAULT 0,
            lanes_confirmed     TEXT    DEFAULT '',
            carriers_confirmed  TEXT    DEFAULT '',
            bounce_code         TEXT    DEFAULT '',
            new_email           TEXT    DEFAULT '',
            notes               TEXT    DEFAULT '',
            click_token         TEXT    DEFAULT '',
            lane_clicks         TEXT    DEFAULT '[]',
            carrier_clicks      TEXT    DEFAULT '[]'
        )
    """)
    conn.commit()
    conn.close()


def _to_locode(name):
    from rate_engine_v2 import to_locode

    return to_locode(name)


def _populate_lane_locodes(conn):
    updates = []
    rows = conn.execute("""
        SELECT id, origin_name, destination_name, locode_origin, locode_dest
        FROM lanes
    """).fetchall()

    for row in rows:
        current_origin = (row["locode_origin"] or "").strip()
        current_dest = (row["locode_dest"] or "").strip()
        origin_name = (row["origin_name"] or "").strip()
        destination_name = (row["destination_name"] or "").strip()

        next_origin = current_origin or (_to_locode(origin_name) if origin_name else "")
        next_dest = current_dest or (_to_locode(destination_name) if destination_name else "")

        if next_origin != current_origin or next_dest != current_dest:
            updates.append((next_origin, next_dest, row["id"]))

    if updates:
        conn.executemany(
            "UPDATE lanes SET locode_origin=?, locode_dest=? WHERE id=?",
            updates,
        )


def _populate_lane_keys(conn):
    updates = []
    rows = conn.execute("""
        SELECT id, lane_key, origin_name, destination_name, locode_origin, locode_dest
        FROM lanes
    """).fetchall()

    for row in rows:
        lane_key = (row["lane_key"] or "").strip()
        if lane_key:
            continue

        origin_name = (row["origin_name"] or "").strip()
        destination_name = (row["destination_name"] or "").strip()
        origin_locode = (row["locode_origin"] or "").strip() or (
            _to_locode(origin_name) if origin_name else ""
        )
        dest_locode = (row["locode_dest"] or "").strip() or (
            _to_locode(destination_name) if destination_name else ""
        )

        if origin_locode and dest_locode:
            updates.append((f"{origin_locode}__{dest_locode}", row["id"]))

    if updates:
        conn.executemany(
            "UPDATE lanes SET lane_key=? WHERE id=?",
            updates,
        )


def init_contact_intelligence_db():
    """Create contact intelligence tables: profiles, interactions, interests."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()

    # ── Contact profile (behavioral + interest layer) ──────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_profiles (
            contact_id              INTEGER PRIMARY KEY,
            email_count             INTEGER DEFAULT 0,
            response_count          INTEGER DEFAULT 0,
            avg_response_hours      REAL    DEFAULT 0,
            behavior_type           TEXT    DEFAULT 'unknown',
            email_style             TEXT    DEFAULT 'standard',
            subject_tone            TEXT    DEFAULT 'functional',
            interest_question_sent  INTEGER DEFAULT 0,
            interest_question_at    TEXT    DEFAULT '',
            interests               TEXT    DEFAULT '[]',
            interests_updated_at    TEXT    DEFAULT '',
            interest_news_cache     TEXT    DEFAULT '{}',
            interest_news_fetched_at TEXT   DEFAULT '',
            cultural_lines_used     TEXT    DEFAULT '[]',
            last_cultural_line      TEXT    DEFAULT '',
            notes                   TEXT    DEFAULT '',
            last_contacted_at       TEXT    DEFAULT '',
            last_responded_at       TEXT    DEFAULT '',
            created_at              TEXT    DEFAULT '',
            updated_at              TEXT    DEFAULT ''
        )
    """)

    # ── Per-email interaction log ──────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_interactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id      INTEGER,
            email_type      TEXT    DEFAULT 'rate_request',
            cycle           TEXT    DEFAULT '',
            sent_at         TEXT    DEFAULT '',
            responded_at    TEXT    DEFAULT '',
            response_hours  REAL,
            cultural_line   TEXT    DEFAULT '',
            interest_asked  INTEGER DEFAULT 0,
            notes           TEXT    DEFAULT ''
        )
    """)

    # ── Auto-migrate contact_profiles if new columns added later ──────────
    prof_cols = _get_existing_columns(conn, "contact_profiles")
    prof_migrations = [
        ("subject_tone",             "TEXT DEFAULT 'functional'"),
        ("interest_news_fetched_at", "TEXT DEFAULT ''"),
        ("cultural_lines_used",      "TEXT DEFAULT '[]'"),
        ("last_cultural_line",       "TEXT DEFAULT ''"),
    ]
    for col, defn in prof_migrations:
        if col not in prof_cols:
            conn.execute(f"ALTER TABLE contact_profiles ADD COLUMN {col} {defn}")

    conn.commit()
    conn.close()


def init_users_db():
    """Create user auth, learning, agent scoring, and rate intelligence tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()

    # ── User accounts ──────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     INTEGER DEFAULT 1,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    DEFAULT 'user',
            created_at    TEXT    DEFAULT '',
            last_login    TEXT    DEFAULT '',
            login_count   INTEGER DEFAULT 0,
            onboarding_completed INTEGER DEFAULT 0,
            onboarding_step TEXT DEFAULT NULL
        )
    """)

    # ── Password reset tokens ──────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT    NOT NULL,
            token      TEXT    NOT NULL,
            expires_at TEXT    NOT NULL,
            used       INTEGER DEFAULT 0
        )
    """)

    # ── Learning progress ──────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_progress (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            book         TEXT    NOT NULL,
            lesson       TEXT    NOT NULL,
            score        INTEGER DEFAULT 10,
            completed_at TEXT    DEFAULT '',
            UNIQUE(user_id, book, lesson)
        )
    """)

    # ── Learning streaks ───────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS learning_streaks (
            user_id        INTEGER PRIMARY KEY,
            current_streak INTEGER DEFAULT 0,
            longest_streak INTEGER DEFAULT 0,
            last_activity  TEXT    DEFAULT ''
        )
    """)

    # ── Agent scores ───────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_scores (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id          INTEGER UNIQUE,
            response_time_score REAL    DEFAULT 50,
            data_quality_score  REAL    DEFAULT 50,
            consistency_score   REAL    DEFAULT 50,
            lane_coverage_score REAL    DEFAULT 50,
            negotiation_score   REAL    DEFAULT 50,
            overall_score       REAL    DEFAULT 50,
            win_count           INTEGER DEFAULT 0,
            total_submissions   INTEGER DEFAULT 0,
            updated_at          TEXT    DEFAULT ''
        )
    """)

    # ── Rate benchmarks per lane ───────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_benchmarks (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            origin_locode TEXT    NOT NULL,
            dest_locode   TEXT    NOT NULL,
            carrier       TEXT    DEFAULT '',
            floor_20ft    REAL,
            mid_20ft      REAL,
            max_20ft      REAL,
            floor_40ft    REAL,
            mid_40ft      REAL,
            max_40ft      REAL,
            confidence    TEXT    DEFAULT 'low',
            sample_count  INTEGER DEFAULT 0,
            cycle_id      INTEGER,
            calculated_at TEXT    DEFAULT '',
            UNIQUE(origin_locode, dest_locode, carrier, cycle_id)
        )
    """)

    # ── Nudge log ──────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nudge_log (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id        INTEGER,
            cycle_id          INTEGER,
            rate_id           INTEGER,
            deviation_pct     REAL,
            sent_at           TEXT    DEFAULT '',
            response_type     TEXT    DEFAULT 'pending',
            response_at       TEXT    DEFAULT '',
            adjusted_rate     REAL,
            negotiation_delta REAL    DEFAULT 0
        )
    """)

    # ── Rate flags ─────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_flags (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id     INTEGER,
            cycle_id       INTEGER,
            reason         TEXT    DEFAULT '',
            flagged_at     TEXT    DEFAULT '',
            clean_cycles   INTEGER DEFAULT 0,
            auto_recovered INTEGER DEFAULT 0,
            recovered_at   TEXT    DEFAULT ''
        )
    """)

    # ── Rate history (archive — never delete) ──────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rate_history (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            rate_id           INTEGER,
            contact_id        INTEGER,
            cycle_id          INTEGER,
            origin_locode     TEXT    DEFAULT '',
            dest_locode       TEXT    DEFAULT '',
            carrier           TEXT    DEFAULT '',
            rate_20ft         REAL,
            rate_40ft         REAL,
            validation_status TEXT    DEFAULT 'valid',
            confidence        TEXT    DEFAULT 'low',
            archived_at       TEXT    DEFAULT '',
            win               INTEGER DEFAULT 0
        )
    """)

    # ── Migrate existing rates table ───────────────────────────────────────
    rate_cols = _get_existing_columns(conn, "rates")
    for col, defn in [
        ("origin_locode",     "TEXT DEFAULT ''"),
        ("dest_locode",       "TEXT DEFAULT ''"),
        ("validation_status", "TEXT DEFAULT 'valid'"),
        ("confidence",        "TEXT DEFAULT 'low'"),
        ("win",               "INTEGER DEFAULT 0"),
        ("archived",          "INTEGER DEFAULT 0"),
        ("deviation_pct",     "REAL DEFAULT 0"),
    ]:
        if col not in rate_cols:
            conn.execute(f"ALTER TABLE rates ADD COLUMN {col} {defn}")

    # ── Migrate lanes table ────────────────────────────────────────────────
    lane_cols = _get_existing_columns(conn, "lanes")
    for col, defn in [
        ("carrier",       "TEXT DEFAULT ''"),
        ("alliance",      "TEXT DEFAULT ''"),
        ("service",       "TEXT DEFAULT ''"),
        ("frequency",     "TEXT DEFAULT ''"),
        ("etd",           "TEXT DEFAULT ''"),
        ("eta",           "TEXT DEFAULT ''"),
        ("vessel",        "TEXT DEFAULT ''"),
        ("transit",       "TEXT DEFAULT ''"),
        ("source",        "TEXT DEFAULT ''"),
        ("confidence",    "TEXT DEFAULT ''"),
        ("locode_origin", "TEXT DEFAULT ''"),
        ("locode_dest",   "TEXT DEFAULT ''"),
    ]:
        if col not in lane_cols:
            conn.execute(f"ALTER TABLE lanes ADD COLUMN {col} {defn}")

    _populate_lane_locodes(conn)
    _populate_lane_keys(conn)

    # ── User login history ────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_logins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            login_at   TEXT    NOT NULL,
            ip_address TEXT    DEFAULT ''
        )
    """)

    # ── Migrate users table: add login_count + security columns ─────────
    user_cols = _get_existing_columns(conn, "users")
    for col, defn in [
        ("tenant_id",             "INTEGER DEFAULT 1"),
        ("login_count",           "INTEGER DEFAULT 0"),
        ("onboarding_completed",  "INTEGER DEFAULT 0"),
        ("onboarding_step",       "TEXT DEFAULT NULL"),
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("locked_until",          "TEXT DEFAULT ''"),
        ("mfa_secret",            "TEXT DEFAULT ''"),
        ("mfa_enabled",           "INTEGER DEFAULT 0"),
        ("mfa_backup_codes",      "TEXT DEFAULT ''"),
        ("login_notifications_enabled", "INTEGER DEFAULT 1"),
        ("oauth_provider",        "TEXT DEFAULT ''"),
    ]:
        if col not in user_cols:
            try:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
            except Exception:
                pass

    # ── Email send analytics (timezone-aware send optimization) ──────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_send_analytics (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id          INTEGER,
            email_type          TEXT    DEFAULT 'intro',
            sent_at_utc         TEXT    NOT NULL,
            sent_at_local       TEXT    NOT NULL,
            sent_day_of_week    INTEGER,
            sent_hour_local     INTEGER,
            opened_at_utc       TEXT    DEFAULT '',
            replied_at_utc      TEXT    DEFAULT '',
            reply_hour_local    INTEGER,
            reply_speed_minutes INTEGER,
            behavior_type       TEXT    DEFAULT 'unknown',
            country             TEXT    DEFAULT ''
        )
    """)

    # ── Individual contact timing profile ────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_timing_profile (
            contact_id              INTEGER PRIMARY KEY,
            avg_reply_hour_local    REAL,
            preferred_window        TEXT    DEFAULT 'morning',
            avg_reply_speed_minutes REAL,
            fastest_reply_hour      INTEGER,
            total_interactions      INTEGER DEFAULT 0,
            personality_signal      TEXT    DEFAULT '',
            optimal_send_hours      TEXT    DEFAULT '[]',
            last_updated            TEXT    DEFAULT ''
        )
    """)

    # ── Security: user permissions ────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            tenant_id   INTEGER NOT NULL,
            feature     TEXT    NOT NULL,
            can_read    INTEGER DEFAULT 0,
            can_write   INTEGER DEFAULT 0,
            can_delete  INTEGER DEFAULT 0,
            can_export  INTEGER DEFAULT 0,
            granted_by  INTEGER,
            granted_at  TEXT    DEFAULT '',
            UNIQUE(user_id, feature)
        )
    """)

    # ── Security: permission templates ────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS permission_templates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER NOT NULL,
            template_name   TEXT    NOT NULL,
            permissions     TEXT    NOT NULL,
            created_by      INTEGER,
            created_at      TEXT    DEFAULT ''
        )
    """)

    # ── Security: audit log ───────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER,
            user_id     INTEGER,
            action      TEXT    NOT NULL,
            resource    TEXT    DEFAULT '',
            details     TEXT    DEFAULT '',
            ip_address  TEXT    DEFAULT '',
            user_agent  TEXT    DEFAULT '',
            created_at  TEXT    DEFAULT ''
        )
    """)
    # Indexes for audit queries
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit_log(tenant_id, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, action)")
    except Exception:
        pass

    # ── Security: API keys ────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            key_hash    TEXT    NOT NULL,
            key_prefix  TEXT    NOT NULL,
            name        TEXT    DEFAULT '',
            permissions TEXT    DEFAULT '{}',
            last_used   TEXT    DEFAULT '',
            expires_at  TEXT    DEFAULT '',
            revoked     INTEGER DEFAULT 0,
            created_at  TEXT    DEFAULT ''
        )
    """)

    # ── Security: password history ────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS password_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            password_hash   TEXT    NOT NULL,
            created_at      TEXT    DEFAULT ''
        )
    """)

    # ── Security: IP allowlist ────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ip_allowlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id   INTEGER NOT NULL,
            ip_address  TEXT    NOT NULL,
            label       TEXT    DEFAULT '',
            created_by  INTEGER,
            created_at  TEXT    DEFAULT ''
        )
    """)

    # ── Security: trusted devices ─────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trusted_devices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            device_id       TEXT    NOT NULL UNIQUE,
            fingerprint_hash TEXT   NOT NULL,
            name            TEXT    DEFAULT '',
            last_used       TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT '',
            expires_at      TEXT    DEFAULT ''
        )
    """)

    # ── Security: active sessions (single-session enforcement) ──────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            session_token   TEXT    NOT NULL UNIQUE,
            ip_address      TEXT    DEFAULT '',
            user_agent      TEXT    DEFAULT '',
            created_at      TEXT    DEFAULT '',
            last_seen       TEXT    DEFAULT ''
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_active_sessions_user ON active_sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_active_sessions_token ON active_sessions(session_token)")
    except Exception:
        pass

    # ── Migrate tenants table: add security columns ──────────────────────
    try:
        tenant_cols = _get_existing_columns(conn, "tenants")
        if "ip_restriction_enabled" not in tenant_cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN ip_restriction_enabled INTEGER DEFAULT 0")
        if "mfa_enforced" not in tenant_cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN mfa_enforced INTEGER DEFAULT 0")
        if "single_session_enforced" not in tenant_cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN single_session_enforced INTEGER DEFAULT 1")
    except Exception:
        pass

    conn.commit()
    conn.close()
