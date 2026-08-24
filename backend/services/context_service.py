"""Structured context builder for the AI assistant.

The user's question is never sent to a model on its own. This module first assembles a
compact, fully-grounded snapshot of the site -- consumption, appliances, anomalies,
weather, forecast, tariff, renewables, optimisation, carbon, score -- and the assistant
answers *only* from that snapshot.

Two design consequences:

* Every number the assistant can see is one this platform computed, so it has nothing
  to hallucinate *from*.
* Anything unavailable is present in the context as an explicit "unavailable" entry
  with a reason, so the assistant can say why instead of guessing.
"""

from __future__ import annotations

import json

from backend.config import get_settings
from backend.services import (
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


def build_context(site_id: str, date: str | None = None) -> dict:
    """Assemble the grounded snapshot the assistant reasons over."""
    settings = get_settings()
    date = date or energy_service.latest_date(site_id)

    summary = energy_service.get_site_summary(site_id)
    totals = energy_service.day_totals(site_id, date)
    comparison = energy_service.compare_to_previous(site_id, date)
    appliances = ml_service.site_appliance_overview(site_id, date)
    anomalies = ml_service.anomalies(site_id, limit=8)
    observed_weather = weather_service.observed_weather_context(site_id, date)
    live_weather = weather_service.get_weather(site_id)
    prediction = forecast_service.forecast(site_id, horizon_days=7)
    optimisation = optimization_service.optimize_site(site_id)
    carbon = carbon_service.carbon_summary(site_id, date)
    score = score_service.sustainability_score(site_id, date)
    advice = recommendation_service.build_recommendations(site_id, date)
    renewable = renewable_service.energy_flow(site_id, totals["total_energy_kwh"])

    return {
        "site": {
            "site_id": summary.site_id,
            "display_name": summary.display_name,
            "location": summary.location,
            "kind": summary.kind,
            "history": {
                "first_reading": summary.first_reading,
                "last_reading": summary.last_reading,
                "days": summary.day_count,
                "readings": summary.reading_count,
            },
            "analysis_date": date,
            "is_latest_day": date == energy_service.latest_date(site_id),
        },
        "today": {
            "date": date,
            "total_energy_kwh": totals["total_energy_kwh"],
            "cost": totals["cost"],
            "cost_currency": settings.currency,
            "carbon_kg": totals["carbon_kg"],
            "peak_power_w": totals["peak_power_w"],
            "temperature_mean_c": totals.get("temperature_mean"),
            "humidity_mean_pct": totals.get("humidity_mean"),
            "channels": totals["channels"],
            "vs_trailing_week": comparison,
            "provenance": "measured (energy); estimated (cost, carbon)",
        },
        "appliances": [
            {
                "appliance": entry["appliance"],
                "label": entry["appliance_label"],
                "energy_kwh": entry["energy_kwh"],
                "expected_energy_kwh": entry["expected_energy_kwh"],
                "deviation_pct": entry["deviation_pct"],
                "runtime_hours": entry["runtime_hours"],
                "status": entry["status"],
                "probability": entry["probability"],
                "model_reliability": entry["reliability"],
                "model_reliability_note": entry["reliability_note"],
                "explanation": entry["explanation"],
                "metadata": entry["metadata"],
            }
            for entry in appliances
        ],
        "anomalies": [
            {
                "appliance": entry["appliance_label"],
                "date": entry["date"],
                "severity": entry["severity"],
                "types": [t["type"] for t in entry["types"]],
                "deviation_pct": entry["deviation_pct"],
                "explanation": entry["explanation"],
            }
            for entry in anomalies
        ],
        "weather": {
            "recorded_with_readings": observed_weather,
            "live": (
                {
                    "available": True,
                    "temperature_c": live_weather.get("temperature_c"),
                    "feels_like_c": live_weather.get("feels_like_c"),
                    "humidity_pct": live_weather.get("humidity_pct"),
                    "condition": live_weather.get("condition"),
                    "location": live_weather.get("location"),
                }
                if live_weather.get("available")
                else {"available": False, "reason": live_weather.get("reason")}
            ),
        },
        "forecast": (
            {
                "available": True,
                "model": prediction["model_label"],
                "mae_kwh": prediction["accuracy"]["mae_kwh"],
                "mape_pct": prediction["accuracy"]["mape_pct"],
                "tomorrow": prediction["tomorrow"],
                "next_7_days": prediction["points"],
                "assumptions": prediction["assumptions"],
                "warning": prediction.get("warning"),
            }
            if prediction["available"]
            else {"available": False, "reason": prediction["reason"]}
        ),
        "tariff": {
            "mode": optimisation["tariff"]["mode"],
            "currency": settings.currency,
            "peak_rate": optimisation["tariff"]["peak_rate"],
            "offpeak_rate": optimisation["tariff"]["offpeak_rate"],
            "peak_hours": optimisation["tariff"]["peak_hours"],
            "provenance": "estimated (configured, not a real bill)",
        },
        "optimisation": {
            "totals": optimisation["totals"],
            "plans": [
                {
                    "appliance": plan["label"],
                    "shiftable": plan["shiftable"],
                    "reason": plan["reason"],
                    "current_hours": plan["current_hours"],
                    "recommended_hours": plan["recommended_hours"],
                    "saving_per_day": plan["saving"],
                    "flexibility": plan["flexibility"],
                }
                for plan in optimisation["plans"]
            ],
            "critical_loads_never_shifted": optimisation["constraints"][
                "critical_loads_excluded"
            ],
        },
        "renewable": {
            "status": renewable["status"],
            "message": renewable["message"],
            "solar_available": renewable["solar"]["available"],
            "battery_available": renewable["battery"]["available"],
            "ev_available": renewable["ev"]["available"],
        },
        "carbon": {
            "daily_kg": carbon["daily"]["carbon_kg"],
            "month_to_date_kg": carbon["month_to_date"]["carbon_kg"],
            "emission_factor": carbon["emission_factor"],
            "emission_factor_source": carbon["emission_factor_source"],
            "provenance": "estimated",
        },
        "sustainability_score": {
            "overall": score["overall"],
            "grade": score["grade"],
            "components": [
                {
                    "label": component["label"],
                    "score": component["score"],
                    "available": component["available"],
                    "detail": component["detail"],
                }
                for component in score["components"]
            ],
        },
        "recommendations": [
            {
                "priority": entry["priority"],
                "title": entry["title"],
                "recommendation": entry["recommendation"],
                "reason": entry["reason"],
                "estimated_saving": entry["estimated_saving"],
                "saving_period": entry["saving_period"],
                "confidence": entry["confidence"],
            }
            for entry in advice["recommendations"]
        ],
        "model_registry": ml_service.registry_summary(),
        "data_limitations": [
            "This dataset has no solar generation, battery, EV, occupancy or real-time "
            "telemetry. Anything about those is a configuration statement, not a "
            "measurement.",
            "Tariff rates and the grid emission factor are configured, so all costs and "
            "carbon figures are estimates.",
            "The inefficiency model classifies whole days and was trained on labels "
            "derived from a residual percentile, not externally verified ground truth.",
        ],
    }


def context_as_json(site_id: str, date: str | None = None, indent: int | None = None) -> str:
    return json.dumps(build_context(site_id, date), indent=indent, default=str)


def compact_context(site_id: str, date: str | None = None) -> dict:
    """A smaller snapshot for the daily-insight call, which needs less breadth."""
    full = build_context(site_id, date)
    return {
        "site": full["site"],
        "today": full["today"],
        "appliances": full["appliances"],
        "anomalies": full["anomalies"][:3],
        "weather": full["weather"],
        "forecast": full["forecast"],
        "optimisation": {
            "totals": full["optimisation"]["totals"],
            "plans": [p for p in full["optimisation"]["plans"] if p["shiftable"]][:3],
        },
        "recommendations": full["recommendations"][:3],
        "data_limitations": full["data_limitations"],
    }
