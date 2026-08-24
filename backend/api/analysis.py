"""Anomaly detection, model registry and sustainability scoring."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.services import ml_service, score_service
from backend.utils.errors import ensure_date, ensure_site

router = APIRouter(tags=["analysis"])


@router.get("/anomalies/{site_id}")
def anomalies(site_id: str, limit: int = Query(default=20, ge=1, le=200)) -> dict:
    """Days flagged as abnormal, with the kind of abnormality separated out."""
    ensure_site(site_id)
    found = ml_service.anomalies(site_id, limit)
    return {
        "site_id": site_id,
        "count": len(found),
        "anomalies": found,
        "types_detected": sorted(
            {entry["type"] for anomaly in found for entry in anomaly["types"]}
        ),
        "note": (
            "High consumption on a hot day is not flagged by itself: the expected-energy "
            "baseline already accounts for heat and humidity, so what is reported here "
            "is consumption beyond the weather-adjusted expectation."
        ),
    }


@router.get("/score/{site_id}")
def sustainability_score(site_id: str, date: str | None = None) -> dict:
    """The 0-100 score with its full formula breakdown."""
    ensure_site(site_id)
    return score_service.sustainability_score(site_id, ensure_date(site_id, date))


@router.get("/models")
def models() -> dict:
    """Every trained (site, appliance) pair and how well it validated."""
    return ml_service.registry_summary()
