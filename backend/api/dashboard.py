"""Dashboard, sites and consumption endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.config import get_settings
from backend.schemas.common import (
    ConsumptionResponse,
    DashboardResponse,
    Granularity,
    SiteResponse,
)
from backend.services import (
    ai_service,
    carbon_service,
    energy_service,
    forecast_service,
    ml_service,
    optimization_service,
    recommendation_service,
    renewable_service,
    score_service,
    weather_service,
)
from backend.utils.errors import degrade, ensure_date, ensure_site

router = APIRouter(tags=["dashboard"])


@router.get("/houses", response_model=list[SiteResponse])
def list_houses() -> list[dict]:
    """Every site in the dataset, with the size of its history."""
    return [
        {
            **summary.__dict__,
            "latest_date": energy_service.latest_date(summary.site_id),
            "showcase_date": energy_service.showcase_date(summary.site_id),
        }
        for summary in energy_service.list_site_summaries()
    ]


@router.get("/houses/{site_id}", response_model=SiteResponse)
def get_house(site_id: str) -> dict:
    ensure_site(site_id)
    summary = energy_service.get_site_summary(site_id)
    return {
        **summary.__dict__,
        "latest_date": energy_service.latest_date(site_id),
        "showcase_date": energy_service.showcase_date(site_id),
        "last_reading_date": energy_service.last_reading_date(site_id),
        "capabilities": energy_service.capabilities_payload(site_id),
        "available_dates": energy_service.available_dates(site_id),
    }


@router.get("/houses/{site_id}/appliances")
def get_house_appliances(site_id: str, date: str | None = None) -> dict:
    """Appliance-level intelligence for one day."""
    ensure_site(site_id)
    resolved = ensure_date(site_id, date)
    totals = energy_service.day_totals(site_id, resolved)
    return {
        "site_id": site_id,
        "date": resolved,
        "capabilities": energy_service.capabilities_payload(site_id),
        "channels": totals["channels"],
        "total_energy_kwh": totals["total_energy_kwh"],
        "analysed": ml_service.site_appliance_overview(site_id, resolved),
    }


@router.get("/houses/{site_id}/consumption", response_model=ConsumptionResponse)
def get_consumption(
    site_id: str,
    granularity: Granularity = "daily",
    start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    channel: str | None = None,
) -> dict:
    ensure_site(site_id)
    return energy_service.consumption_series(site_id, granularity, start, end, channel)


@router.get("/houses/{site_id}/profile")
def get_hourly_profile(site_id: str, channel: str | None = None) -> dict:
    """Average load shape by hour of day, with each hour's tariff."""
    ensure_site(site_id)
    return {
        "site_id": site_id,
        "channel": channel,
        "hours": energy_service.hourly_profile(site_id, channel),
        "tariff": {"mode": get_settings().tariff_mode},
    }


@router.get("/houses/{site_id}/dashboard", response_model=DashboardResponse)
def get_dashboard(site_id: str, date: str | None = None) -> dict:
    """Everything the main dashboard needs, in one call.

    Optional services are wrapped so that a failing weather provider, LLM or
    forecaster degrades to an unavailable block instead of blanking the page.
    """
    ensure_site(site_id)
    resolved = ensure_date(site_id, date)
    summary = energy_service.get_site_summary(site_id)
    totals = energy_service.day_totals(site_id, resolved)

    return {
        "site": {
            **summary.__dict__,
            "latest_date": energy_service.latest_date(site_id),
            "showcase_date": energy_service.showcase_date(site_id),
            "last_reading_date": energy_service.last_reading_date(site_id),
        },
        "date": resolved,
        "available_dates": energy_service.available_dates(site_id),
        "totals": totals,
        "comparison": degrade(
            "Week-on-week comparison",
            lambda: energy_service.compare_to_previous(site_id, resolved),
        ),
        "appliances": degrade(
            "Appliance analysis",
            lambda: ml_service.site_appliance_overview(site_id, resolved),
            fallback={},
        )
        or [],
        "anomalies": degrade("Anomaly detection", lambda: ml_service.anomalies(site_id, 8))
        or [],
        "weather": {
            "live": degrade("Weather", lambda: weather_service.get_weather(site_id)),
            "recorded": degrade(
                "Recorded weather",
                lambda: weather_service.observed_weather_context(site_id, resolved),
            ),
        },
        "forecast": degrade("Forecast", lambda: forecast_service.forecast(site_id, 7)),
        "optimization": degrade(
            "Optimisation", lambda: optimization_service.optimize_site(site_id)
        ),
        "carbon": degrade(
            "Carbon analysis", lambda: carbon_service.carbon_summary(site_id, resolved)
        ),
        "sustainability_score": degrade(
            "Sustainability score",
            lambda: score_service.sustainability_score(site_id, resolved),
        ),
        "recommendations": degrade(
            "Recommendations",
            lambda: recommendation_service.build_recommendations(site_id, resolved),
            fallback={"recommendations": []},
        ),
        "insight": degrade(
            "Daily insight", lambda: ai_service.daily_insight(site_id, resolved)
        ),
        "energy_flow": degrade(
            "Energy flow",
            lambda: renewable_service.energy_flow(site_id, totals["total_energy_kwh"]),
        ),
        "capabilities": energy_service.capabilities_payload(site_id),
    }
