"""SQLite storage for Yant Guard governance data (Step 2: request log)."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.paths import REPO_ROOT, data_dir  # noqa: F401  (REPO_ROOT kept for older imports)


def db_path() -> Path:
    """Database file (data/yantguard.db). Override with YANTGUARD_DB (tests use this)."""
    return Path(os.getenv("YANTGUARD_DB", data_dir() / "yantguard.db"))


@contextmanager
def get_conn():
    """Open the database, commit on success, roll back on error, always close."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    user_name         TEXT,            -- filled in Step 3
    provider          TEXT,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    total_tokens      INTEGER,
    cost_usd          REAL,            -- filled in Step 5
    status_code       INTEGER NOT NULL,
    success           INTEGER NOT NULL,
    latency_ms        INTEGER,
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests (created_at);

CREATE TABLE IF NOT EXISTS departments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Which providers a department may use. No row = not allowed.
CREATE TABLE IF NOT EXISTS department_providers (
    department_id INTEGER NOT NULL REFERENCES departments (id),
    provider      TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (department_id, provider)
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    department_id INTEGER NOT NULL REFERENCES departments (id),
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Step 6: optional monthly spending limit per department (USD). No row = no limit.
CREATE TABLE IF NOT EXISTS department_budgets (
    department_id     INTEGER PRIMARY KEY REFERENCES departments (id),
    monthly_limit_usd REAL NOT NULL CHECK (monthly_limit_usd > 0)
);

-- Step 7: security filter. Rule actions override the defaults in security.py.
CREATE TABLE IF NOT EXISTS security_rules (
    name   TEXT PRIMARY KEY,
    action TEXT NOT NULL CHECK (action IN ('mask', 'block', 'off'))
);

-- Step 7: what the filter found. Never stores the sensitive value or the prompt.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    user_name   TEXT,
    department  TEXT,
    provider    TEXT,
    rule        TEXT NOT NULL,
    action      TEXT NOT NULL,      -- masked | blocked
    match_count INTEGER NOT NULL
);

-- Dashboard admin accounts (password stored as a salted PBKDF2 hash) and login sessions.
CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash TEXT PRIMARY KEY,
    admin_id   INTEGER NOT NULL REFERENCES admins (id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at TEXT NOT NULL
);
-- What admins did in the dashboard (never passwords or keys).
CREATE TABLE IF NOT EXISTS admin_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    admin_name TEXT,
    action     TEXT NOT NULL,
    detail     TEXT
);

-- Only a SHA-256 hash of each key is stored; the key itself is shown once at creation.
CREATE TABLE IF NOT EXISTS api_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users (id),
    key_hash   TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    revoked_at TEXT
);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def log_request(
    *,
    provider=None,
    model=None,
    prompt_tokens=None,
    completion_tokens=None,
    total_tokens=None,
    status_code: int,
    success: bool,
    latency_ms=None,
    error=None,
    user_name=None,
    cost_usd=None,
) -> None:
    """Insert one row. Prompt text is never stored."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO requests
               (user_name, provider, model, prompt_tokens, completion_tokens,
                total_tokens, cost_usd, status_code, success, latency_ms, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_name, provider, model, prompt_tokens, completion_tokens,
             total_tokens, cost_usd, status_code, int(success), latency_ms, error),
        )
