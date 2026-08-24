"""Carbon intelligence endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.services import carbon_service
from backend.utils.errors import ensure_date, ensure_site

router = APIRouter(tags=["carbon"])


@router.get("/carbon")
def carbon(site_id: str, date: str | None = None) -> dict:
    ensure_site(site_id)
    return carbon_service.carbon_summary(site_id, ensure_date(site_id, date))


@router.get("/carbon/config")
def carbon_config() -> dict:
    """The emission factor in use and where it came from."""
    return carbon_service.describe()
