"""Recommendation endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.common import PreferencesRequest
from backend.services import recommendation_service
from backend.database import preferences as preferences_store
from backend.utils.errors import ensure_date, ensure_site

router = APIRouter(tags=["recommendations"])


@router.get("/recommendations")
def recommendations(site_id: str, date: str | None = None) -> dict:
    """Ranked, rule-derived recommendations. No language model contributes here."""
    ensure_site(site_id)
    resolved = ensure_date(site_id, date)
    stored = preferences_store.get_preferences(site_id)
    return recommendation_service.build_recommendations(site_id, resolved, stored)


@router.get("/preferences/{site_id}")
def get_preferences(site_id: str) -> dict:
    ensure_site(site_id)
    return {"site_id": site_id, "preferences": preferences_store.get_preferences(site_id)}


@router.put("/preferences")
def set_preferences(request: PreferencesRequest) -> dict:
    """Store household preferences. Recommendations respect these constraints."""
    ensure_site(request.site_id)
    payload = request.model_dump(exclude_none=True)
    payload.pop("site_id", None)
    preferences_store.save_preferences(request.site_id, payload)
    return {
        "site_id": request.site_id,
        "preferences": preferences_store.get_preferences(request.site_id),
        "saved": True,
    }
