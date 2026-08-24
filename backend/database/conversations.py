"""Assistant conversation log.

Kept so a user can see what they asked and what the platform answered. Failure to
write is logged and swallowed -- an unavailable log must never break a reply.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from .db import connection

logger = logging.getLogger(__name__)


def record(site_id: str, question: str, answer: str, source: str) -> None:
    try:
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO ai_conversations (site_id, question, answer, source, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (site_id, question, answer, source, datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.Error:
        logger.exception("Could not record conversation for %s", site_id)


def recent(site_id: str, limit: int = 20) -> list[dict]:
    try:
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT question, answer, source, created_at
                FROM ai_conversations
                WHERE site_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (site_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        logger.exception("Could not read conversations for %s", site_id)
        return []
