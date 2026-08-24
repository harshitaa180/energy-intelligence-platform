"""Error helpers.

Two rules the whole API follows:

* An unknown site or appliance is a 404 with a message naming what *is* available,
  not a bare "not found".
* A failure inside one optional service (weather, LLM, forecast) never becomes a 500.
  It degrades to an ``available: false`` block with a reason, so a dashboard with a
  dead weather provider still renders everything else.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def ensure_site(site_id: str) -> str:
    from data.loaders import list_sites

    sites = list_sites()
    if site_id not in sites:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_site",
                "message": f"No site named {site_id!r}.",
                "available_sites": list(sites),
            },
        )
    return site_id


def ensure_appliance(site_id: str, appliance: str) -> str:
    from data.loaders import site_channel_keys

    keys = site_channel_keys(site_id)
    if appliance not in keys:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_appliance",
                "message": f"{site_id} has no channel named {appliance!r}.",
                "available_appliances": keys,
            },
        )
    return appliance


def ensure_date(site_id: str, date: str | None) -> str:
    from backend.services import energy_service

    if date is None:
        return energy_service.latest_date(site_id)
    available = energy_service.available_dates(site_id)
    if date not in available:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_date",
                "message": f"{site_id} has no readings on {date}.",
                "first_date": available[0] if available else None,
                "last_date": available[-1] if available else None,
            },
        )
    return date


def degrade(label: str, fn: Callable[[], Any], fallback: dict | None = None) -> Any:
    """Run an optional service; on failure return a labelled unavailable block.

    Used for every service the dashboard can live without.
    """
    try:
        return fn()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - deliberate: one service must not kill the page
        logger.exception("%s failed", label)
        block = {
            "available": False,
            "provenance": "unavailable",
            "reason": f"{label} is temporarily unavailable ({type(exc).__name__}).",
            "message": (
                f"{label} could not be computed. The rest of the analysis is unaffected."
            ),
        }
        if fallback:
            block.update(fallback)
        return block
