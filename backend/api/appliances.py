"""Appliance intelligence and detail endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.common import AnalyzeRequest, ReplacementRequest
from backend.services import (
    energy_service,
    ml_service,
    recommendation_service,
    replacement_service,
    weather_service,
)
from backend.utils.errors import degrade, ensure_appliance, ensure_date, ensure_site

router = APIRouter(tags=["appliances"])


@router.post("/analyze")
def analyze(request: AnalyzeRequest) -> dict:
    """Run the inefficiency analysis for one appliance-day."""
    ensure_site(request.site_id)
    ensure_appliance(request.site_id, request.appliance)
    date = ensure_date(request.site_id, request.date)
    return ml_service.day_payload(request.site_id, request.appliance, date)


@router.get("/appliances/{site_id}/{appliance}/analysis")
def appliance_analysis(site_id: str, appliance: str, date: str | None = None) -> dict:
    """Full detail for one appliance: the day, its history, the model, and advice."""
    ensure_site(site_id)
    ensure_appliance(site_id, appliance)
    resolved = ensure_date(site_id, date)

    analysis = ml_service.analyse(site_id, appliance)
    day = ml_service.day_payload(site_id, appliance, resolved)
    recommendations = degrade(
        "Recommendations",
        lambda: recommendation_service.build_recommendations(site_id, resolved),
        fallback={"recommendations": []},
    )
    relevant = [
        entry
        for entry in recommendations.get("recommendations", [])
        if entry.get("appliance") == appliance
    ]

    return {
        "site_id": site_id,
        "appliance": appliance,
        "appliance_label": analysis.appliance_label,
        "date": resolved,
        "day": day,
        "model_card": ml_service.model_card(site_id, appliance),
        "weather": weather_service.observed_weather_context(site_id, resolved),
        "history": degrade(
            "Appliance history",
            lambda: energy_service.channel_history(site_id, appliance),
        ),
        "series": [
            {
                "date": entry.date,
                "energy_kwh": entry.energy_kwh,
                "active_energy_kwh": entry.active_energy_kwh,
                "expected_energy_kwh": entry.expected_energy_kwh,
                "deviation_pct": entry.deviation_pct,
                "runtime_hours": entry.runtime_hours,
                "status": entry.status,
                "probability": entry.probability,
                "temperature_mean": entry.temperature_mean,
            }
            for entry in analysis.days
        ],
        "notes": analysis.notes,
        "recommendations": relevant,
        "replacement": degrade(
            "Replacement analysis",
            lambda: replacement_service.analyse_replacement(site_id, appliance),
        ),
    }


@router.get("/appliances/{site_id}/{appliance}/history")
def appliance_history(site_id: str, appliance: str) -> dict:
    """Measured per-day history for one channel."""
    ensure_site(site_id)
    ensure_appliance(site_id, appliance)
    return {
        "site_id": site_id,
        "appliance": appliance,
        "history": energy_service.channel_history(site_id, appliance),
    }


@router.get("/appliances/{site_id}/{appliance}/model")
def appliance_model(site_id: str, appliance: str) -> dict:
    """The model card: metrics, features, reliability and limitations."""
    ensure_site(site_id)
    ensure_appliance(site_id, appliance)
    return ml_service.model_card(site_id, appliance)


@router.post("/appliances/replacement")
def replacement(request: ReplacementRequest) -> dict:
    """Replacement analysis. Payback needs a purchase price, which is not in the data."""
    ensure_site(request.site_id)
    ensure_appliance(request.site_id, request.appliance)
    return replacement_service.analyse_replacement(
        request.site_id,
        request.appliance,
        request.target_star_rating,
        request.replacement_cost,
    )
