import sqlite3
import os
from config import DB_PATH


def get_db():
    """Open a database connection with row-factory set to sqlite3.Row."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the contacts table and migrate any missing columns."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
    existing = {row[1] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    migrations = [
        ("network",         "TEXT    DEFAULT ''"),
        ("contact_name",    "TEXT    DEFAULT ''"),
        ("city",            "TEXT    DEFAULT ''"),
        ("verified_status", "TEXT    DEFAULT 'unverified'"),
        ("verified_score",  "INTEGER DEFAULT 0"),
        ("verified_date",   "TEXT    DEFAULT ''"),
        ("website_url",     "TEXT    DEFAULT ''"),
        ("linkedin_url",    "TEXT    DEFAULT ''"),
        ("verify_notes",    "TEXT    DEFAULT ''"),
    ]
    for col, definition in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE contacts ADD COLUMN {col} {definition}")

    conn.commit()
    conn.close()


def init_carriers_db():
    """Create the carriers table."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS carriers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            dot_number    TEXT,
            mc_number     TEXT,
            legal_name    TEXT,
            dba_name      TEXT    DEFAULT '',
            city          TEXT    DEFAULT '',
            state         TEXT    DEFAULT '',
            phone         TEXT    DEFAULT '',
            fleet_trucks  INTEGER DEFAULT 0,
            fleet_drivers INTEGER DEFAULT 0,
            safety_rating TEXT    DEFAULT '',
            status        TEXT    DEFAULT '',
            years_active  INTEGER DEFAULT 0,
            insured       INTEGER DEFAULT 0,
            score         REAL    DEFAULT 0,
            lanes         TEXT    DEFAULT '',
            notes         TEXT    DEFAULT '',
            fetched_at    TEXT    DEFAULT ''
        )
    """)
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
    rate_cols = {r[1] for r in conn.execute("PRAGMA table_info(rates)").fetchall()}
    rate_migrations = [
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
    gap_cols = {r[1] for r in conn.execute("PRAGMA table_info(rate_gaps)").fetchall()}
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


def init_users_db():
    """Create user auth, learning, agent scoring, and rate intelligence tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()

    # ── User accounts ──────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            role          TEXT    DEFAULT 'user',
            created_at    TEXT    DEFAULT '',
            last_login    TEXT    DEFAULT ''
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
    rate_cols = {r[1] for r in conn.execute("PRAGMA table_info(rates)").fetchall()}
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
    lane_cols = {r[1] for r in conn.execute("PRAGMA table_info(lanes)").fetchall()}
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

    conn.commit()
    conn.close()
