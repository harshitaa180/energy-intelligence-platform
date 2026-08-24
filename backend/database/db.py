"""SQLite persistence.

Scope is deliberately narrow. The meter readings live in CSV and are read through the
ingestion layer; duplicating 22,084 rows into SQLite would buy nothing at this size.
What the database holds is the state a *user* creates: household preferences and
assistant conversations.

The schema is written so a move to PostgreSQL is a connection change rather than a
rewrite: no SQLite-only types, explicit timestamps, and all access funnelled through
this module.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.config import get_settings
from data.loaders import paths

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_preferences (
    site_id           TEXT PRIMARY KEY,
    payload           TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id           TEXT NOT NULL,
    question          TEXT NOT NULL,
    answer            TEXT NOT NULL,
    source            TEXT NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversations_site
    ON ai_conversations (site_id, created_at DESC);

CREATE TABLE IF NOT EXISTS renewable_assets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id           TEXT NOT NULL,
    asset_type        TEXT NOT NULL,
    capacity          REAL,
    payload           TEXT,
    created_at        TEXT NOT NULL
);
"""


def _database_path() -> Path:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        path = Path(raw)
        if not path.is_absolute():
            path = paths.PROJECT_ROOT / raw
        return path
    # Anything else is out of scope for the prototype; fall back to a local file so the
    # app still starts rather than crashing on an unsupported URL.
    logger.warning("Unsupported DATABASE_URL %r; using a local SQLite file.", url)
    return paths.PROJECT_ROOT / "energy_platform.db"


@contextmanager
def connection():
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every startup."""
    try:
        with connection() as conn:
            conn.executescript(SCHEMA)
        logger.info("Database ready at %s", _database_path())
    except sqlite3.Error:
        logger.exception("Database initialisation failed; persistence is disabled")


def healthy() -> dict:
    try:
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"available": True, "path": str(_database_path())}
    except sqlite3.Error as exc:
        return {"available": False, "reason": str(exc)}
