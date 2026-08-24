"""Weather endpoints. All provider calls happen here, server-side."""

from __future__ import annotations

from fastapi import APIRouter

from backend.services import weather_service
from backend.utils.errors import ensure_date, ensure_site

router = APIRouter(tags=["weather"])


@router.get("/weather")
def weather(site_id: str, refresh: bool = False) -> dict:
    """Live conditions and forecast for a site's location."""
    ensure_site(site_id)
    return weather_service.get_weather(site_id, force_refresh=refresh)


@router.get("/weather/recorded")
def recorded_weather(site_id: str, date: str | None = None) -> dict:
    """Weather as recorded with the meter readings -- what the model actually used."""
    ensure_site(site_id)
    return weather_service.observed_weather_context(site_id, ensure_date(site_id, date))
