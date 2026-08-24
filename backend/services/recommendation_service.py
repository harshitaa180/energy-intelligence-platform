"""Deterministic recommendation engine.

Recommendations are produced by rules over measured data, model output and the
optimiser -- never by the LLM. The assistant may *rephrase* what this module produces;
it may not invent an item, a saving, or a priority.

Every recommendation carries: priority, the reason it fired, its estimated impact, the
saving (or an explicit statement that none could be calculated), and a confidence that
reflects how much evidence stands behind it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from backend.config import get_settings
from backend.services import (
    energy_service,
    ml_service,
    optimization_service,
    renewable_service,
    replacement_service,
)
from data.schema import Flexibility, Provenance
from ml.reliability import Reliability

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


@dataclass
class Recommendation:
    id: str
    priority: str
    title: str
    recommendation: str
    reason: str
    estimated_impact: str
    estimated_saving: float | None
    saving_period: str | None
    confidence: str
    confidence_reason: str
    appliance: str | None = None
    category: str = "general"
    provenance: str = Provenance.ESTIMATED.value
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_recommendations(
    site_id: str,
    date: str | None = None,
    preferences: dict | None = None,
) -> dict:
    """Assemble the ranked recommendation list for a site."""
    settings = get_settings()
    preferences = preferences or {}
    date = date or energy_service.latest_date(site_id)

    recommendations: list[Recommendation] = []
    recommendations += _from_anomalies(site_id)
    recommendations += _from_optimization(site_id, preferences)
    recommendations += _from_peak_behaviour(site_id)
    recommendations += _from_replacement(site_id)
    recommendations += _from_renewable(site_id)
    recommendations += _from_capabilities(site_id)

    recommendations.sort(
        key=lambda r: (
            PRIORITY_ORDER.get(r.priority, 9),
            -(r.estimated_saving or 0.0),
        )
    )

    total_saving = sum(
        r.estimated_saving
        for r in recommendations
        if r.estimated_saving and r.saving_period == "month"
    )

    return {
        "site_id": site_id,
        "date": date,
        "currency_symbol": settings.currency_symbol,
        "recommendations": [r.to_dict() for r in recommendations],
        "total_monthly_saving": round(total_saving, 2),
        "count_by_priority": {
            priority: sum(1 for r in recommendations if r.priority == priority)
            for priority in ("high", "medium", "low", "info")
        },
        "method": (
            "Rules over measured consumption, the inefficiency model's output and the "
            "tariff optimiser. No language model contributes to this list."
        ),
    }


def _from_anomalies(site_id: str) -> list[Recommendation]:
    out: list[Recommendation] = []
    anomalies = ml_service.anomalies(site_id, limit=6)
    if not anomalies:
        return out

    by_appliance: dict[str, list[dict]] = {}
    for anomaly in anomalies:
        by_appliance.setdefault(anomaly["appliance"], []).append(anomaly)

    for appliance, entries in by_appliance.items():
        latest = entries[0]
        count = len(entries)
        excess_cost = sum(entry.get("excess_cost") or 0 for entry in entries)
        reliable = latest["reliability"] == Reliability.GOOD.value

        types = ", ".join(t["label"].lower() for t in latest["types"])
        priority = "high" if latest["severity"] == "high" else "medium"

        out.append(
            Recommendation(
                id=f"anomaly:{appliance}",
                priority=priority,
                title=f"Investigate {latest['appliance_label']}",
                recommendation=(
                    f"Review {latest['appliance_label']} usage on {latest['date']}: "
                    f"{types}."
                ),
                reason=latest["explanation"],
                estimated_impact=(
                    f"{count} flagged day(s) in the available history, most recently "
                    f"{latest['date']}."
                ),
                estimated_saving=round(excess_cost, 2) if excess_cost > 0 else None,
                saving_period="observed_period" if excess_cost > 0 else None,
                confidence="high" if reliable and count >= 3 else "medium",
                confidence_reason=(
                    "The classifier validates well for this appliance and several days "
                    "are flagged."
                    if reliable and count >= 3
                    else (
                        "Based on the expected-energy comparison. The classifier for "
                        "this appliance is not reliable enough to lead the verdict."
                    )
                ),
                appliance=appliance,
                category="anomaly",
                actions=[
                    "Check the thermostat or timer settings for this appliance.",
                    "Confirm nothing is obstructing airflow or the heating element.",
                    "Compare the flagged day's runtime against a typical day.",
                ],
            )
        )
    return out


def _from_optimization(site_id: str, preferences: dict) -> list[Recommendation]:
    constraints = {}
    # Preference keys are always present but may be null, so test the value.
    if preferences.get("quiet_hours"):
        constraints["quiet_hours"] = set(preferences["quiet_hours"])
    plan = optimization_service.optimize_site(site_id, constraints)

    out: list[Recommendation] = []
    for entry in plan["plans"]:
        if not entry["shiftable"] or entry["saving"] <= 0:
            continue
        hours = entry["recommended_hours"]
        window = _format_window(hours)
        monthly = round(entry["saving"] * 30, 2)
        out.append(
            Recommendation(
                id=f"shift:{entry['channel']}",
                priority="medium" if monthly >= 50 else "low",
                title=f"Shift {entry['label']} to {window}",
                recommendation=(
                    f"Run {entry['label']} during {window} instead of "
                    f"{_format_window(entry['current_hours'])}."
                ),
                reason=(
                    f"This appliance currently uses "
                    f"{entry['daily_energy_kwh']:.2f} kWh a day at an average cost of "
                    f"{entry['current_cost']:.2f}. The proposed window is cheaper under "
                    "the configured tariff."
                    + (f" {entry['reason']}" if entry.get("reason") else "")
                ),
                estimated_impact=f"{entry['saving_pct']:.0f}% lower cost for this load",
                estimated_saving=monthly,
                saving_period="month",
                confidence="medium",
                confidence_reason=(
                    "Energy is measured, but the tariff is configuration and the shift "
                    "assumes the appliance can actually run in the proposed window."
                ),
                appliance=entry["channel"],
                category="load_shifting",
                actions=[
                    f"Set a timer for {window}.",
                    "Confirm the new window suits the household's routine.",
                ],
            )
        )
    return out


def _from_peak_behaviour(site_id: str) -> list[Recommendation]:
    response = optimization_service.demand_response(site_id)
    settings = get_settings()
    peak_share = response["peak_share_pct"]
    fair_share = len(settings.peak_hours) / 24 * 100

    if peak_share <= fair_share * 1.2:
        return []

    return [
        Recommendation(
            id="peak:reduce",
            priority="medium",
            title="Reduce peak-hour consumption",
            recommendation=(
                f"Move discretionary load out of the {_format_window(response['peak_hours'])} "
                "peak window."
            ),
            reason=(
                f"{peak_share:.0f}% of this site's energy falls in peak hours, whose "
                f"proportional share would be {fair_share:.0f}%. Peak energy costs "
                f"{settings.tou_peak_rate:g} against {settings.tou_offpeak_rate:g} "
                "off-peak."
            ),
            estimated_impact=(
                f"{response['peak_cost_share_pct']:.0f}% of daily cost currently sits "
                "in peak hours"
            ),
            estimated_saving=response["opportunity"]["saving_per_month"] or None,
            saving_period="month",
            confidence="medium",
            confidence_reason="Load shape is measured; the tariff is configured.",
            category="demand_response",
            actions=[
                "Delay high-power appliances until after the peak window.",
                "Pre-cool or pre-heat before peak hours where comfort allows.",
            ],
        )
    ]


def _from_replacement(site_id: str) -> list[Recommendation]:
    out: list[Recommendation] = []
    for appliance in ml_service.ml_appliances(site_id):
        analysis = replacement_service.analyse_replacement(site_id, appliance)
        if not analysis.get("available") or not analysis.get("recommended"):
            continue
        savings = analysis["savings"]
        if savings["annual_cost"] <= 0:
            continue
        current = analysis["current"]
        out.append(
            Recommendation(
                id=f"replace:{appliance}",
                priority="low",
                title=f"Consider upgrading {appliance.upper()} units",
                recommendation=(
                    f"Replacing the {current['weighted_star_rating']:.1f}-star units "
                    f"with {analysis['replacement']['target_star_rating']:.0f}-star "
                    "models would cut this appliance's running cost."
                ),
                reason=(
                    f"Measured over {current['measured_days']} days, these units "
                    f"project to {current['annual_kwh']:.0f} kWh a year. "
                    + analysis["payback_note"]
                ),
                estimated_impact=(
                    f"{savings['annual_kwh']:.0f} kWh and "
                    f"{savings['annual_carbon_kg']:.0f} kg CO2e a year"
                ),
                estimated_saving=savings["annual_cost"],
                saving_period="year",
                confidence="low",
                confidence_reason=(
                    "The per-star energy saving is a published rule of thumb, and "
                    "annualising a short seasonal measurement is uncertain. No purchase "
                    "price exists in the dataset."
                ),
                appliance=appliance,
                category="replacement",
                actions=[
                    "Get a quote before committing; payback depends on purchase price.",
                    "Prioritise the unit with the most running hours.",
                ],
            )
        )
    return out


def _from_renewable(site_id: str) -> list[Recommendation]:
    profile = renewable_service.generation_profile(site_id)
    if profile["available"]:
        return []
    return [
        Recommendation(
            id="renewable:integrate",
            priority="info",
            title="Renewable integration ready",
            recommendation=(
                "Connect a solar inverter feed to unlock renewable-aligned scheduling "
                "and avoided-carbon reporting."
            ),
            reason=profile["reason"] or "No renewable measurements are available.",
            estimated_impact="Not calculable without generation data",
            estimated_saving=None,
            saving_period=None,
            confidence="high",
            confidence_reason="This is a statement about configuration, not a prediction.",
            category="renewable",
            provenance=Provenance.UNAVAILABLE.value,
            actions=["Configure SOLAR_ENABLED and connect an inverter data feed."],
        )
    ]


def _from_capabilities(site_id: str) -> list[Recommendation]:
    """Surface instrumentation gaps as actionable items rather than hiding them."""
    out: list[Recommendation] = []
    for capability in energy_service.capabilities_payload(site_id):
        if capability["has_power_signal"] and not capability["has_state_signal"]:
            out.append(
                Recommendation(
                    id=f"data:{capability['key']}:state",
                    priority="info",
                    title=f"No on/off signal for {capability['label']}",
                    recommendation=(
                        "Enable state reporting on this channel to unlock runtime "
                        "analysis and inefficiency detection."
                    ),
                    reason=(
                        "Power is being recorded but the on/off state column is zero "
                        "for every reading, and every behavioural feature in the model "
                        "is computed over on-state readings."
                    ),
                    estimated_impact="Unlocks anomaly detection for this appliance",
                    estimated_saving=None,
                    saving_period=None,
                    confidence="high",
                    confidence_reason="Determined directly from the data.",
                    appliance=capability["key"],
                    category="data_quality",
                    provenance=Provenance.UNAVAILABLE.value,
                    actions=["Check the sub-meter's state-detection threshold."],
                )
            )
    return out


def _format_window(hours: list[int]) -> str:
    if not hours:
        return "no specific window"
    ordered = sorted(hours)
    runs: list[list[int]] = [[ordered[0]]]
    for hour in ordered[1:]:
        if hour == runs[-1][-1] + 1:
            runs[-1].append(hour)
        else:
            runs.append([hour])
    parts = [f"{run[0]:02d}:00-{run[-1] + 1:02d}:00" for run in runs]
    return " and ".join(parts)


def critical_loads(site_id: str) -> list[str]:
    """Loads that must never appear in a shed or shift recommendation."""
    return [
        capability["label"]
        for capability in energy_service.capabilities_payload(site_id)
        if capability["flexibility"] == Flexibility.CRITICAL.value
    ]
