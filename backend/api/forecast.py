"""Forecasting endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.services import forecast_service
from backend.utils.errors import ensure_site

router = APIRouter(tags=["forecast"])


@router.get("/forecast")
def forecast(site_id: str, days: int = Query(default=7, ge=1, le=14)) -> dict:
    """Daily energy forecast with a measured error band."""
    ensure_site(site_id)
    return forecast_service.forecast(site_id, days)
