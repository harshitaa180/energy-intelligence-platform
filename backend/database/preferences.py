"""Household preference storage.

Preferences are constraints, not decoration: the optimiser and the recommendation
engine read them so that advice respects sleep hours, comfort and budget.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

from .db import connection

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "preferred_temperature_c": None,
    "work_hours": None,
    "sleep_hours": None,
    "quiet_hours": None,
    "monthly_budget": None,
    "comfort_priority": "balanced",
    "sustainability_priority": "medium",
    "ev_departure_hour": None,
    "battery_reserve_pct": None,
}


def get_preferences(site_id: str) -> dict:
    """Stored preferences merged over the defaults. Never raises."""
    stored: dict = {}
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT payload FROM site_preferences WHERE site_id = ?", (site_id,)
            ).fetchone()
        if row:
            stored = json.loads(row["payload"])
    except (sqlite3.Error, json.JSONDecodeError):
        logger.exception("Could not read preferences for %s", site_id)

    merged = {**DEFAULTS, **stored}
    # Sleep hours imply quiet hours unless quiet hours were set explicitly.
    if merged.get("quiet_hours") is None and merged.get("sleep_hours"):
        merged["quiet_hours"] = merged["sleep_hours"]
    return merged


def save_preferences(site_id: str, payload: dict) -> None:
    existing = {}
    try:
        with connection() as conn:
            row = conn.execute(
                "SELECT payload FROM site_preferences WHERE site_id = ?", (site_id,)
            ).fetchone()
            if row:
                existing = json.loads(row["payload"])
            merged = {**existing, **payload}
            conn.execute(
                """
                INSERT INTO site_preferences (site_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(site_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (site_id, json.dumps(merged), datetime.now(timezone.utc).isoformat()),
            )
    except (sqlite3.Error, json.JSONDecodeError):
        logger.exception("Could not save preferences for %s", site_id)
