"""Household sustainability score.

A score is only worth showing if the reader can reconstruct it. Every component below
states its inputs, its formula and its weight, and the API returns all of that
alongside the number. Components whose inputs are unavailable are **dropped and the
remaining weights renormalised** -- they are never silently scored as zero, which would
punish a site for missing instrumentation.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.config import get_settings
from backend.services import carbon_service, energy_service, ml_service
from data.schema import Provenance

#: Component weights before renormalisation. They sum to 100.
WEIGHTS: dict[str, float] = {
    "energy_efficiency": 30.0,
    "appliance_efficiency": 25.0,
    "peak_behaviour": 20.0,
    "carbon_intensity": 15.0,
    "renewable_utilisation": 10.0,
}


@dataclass
class Component:
    key: str
    label: str
    score: float | None
    weight: float
    formula: str
    detail: str
    available: bool


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def sustainability_score(site_id: str, date: str | None = None) -> dict:
    """Compute the 0-100 score with a full, checkable breakdown."""
    settings = get_settings()
    date = date or energy_service.latest_date(site_id)
    components: list[Component] = []

    components.append(_energy_efficiency(site_id))
    components.append(_appliance_efficiency(site_id))
    components.append(_peak_behaviour(site_id))
    components.append(_carbon_intensity(site_id))
    components.append(_renewable_utilisation())

    available = [c for c in components if c.available and c.score is not None]
    total_weight = sum(c.weight for c in available)

    if total_weight <= 0:
        overall = None
    else:
        overall = round(
            sum(c.score * (c.weight / total_weight) for c in available), 1  # type: ignore[operator]
        )

    return {
        "site_id": site_id,
        "date": date,
        "overall": overall,
        "grade": _grade(overall),
        "components": [
            {
                "key": c.key,
                "label": c.label,
                "score": None if c.score is None else round(c.score, 1),
                "nominal_weight_pct": c.weight,
                "effective_weight_pct": (
                    round(c.weight / total_weight * 100, 1)
                    if c.available and c.score is not None and total_weight
                    else 0.0
                ),
                "formula": c.formula,
                "detail": c.detail,
                "available": c.available,
            }
            for c in components
        ],
        "excluded_components": [c.key for c in components if not c.available],
        "provenance": Provenance.ESTIMATED.value,
        "methodology": (
            "Each component is scored 0-100 from measured data using the formula "
            "shown. Components whose inputs are unavailable are excluded and the "
            "remaining weights renormalised, so a site is never penalised for missing "
            "instrumentation. The overall score is the weighted mean of the "
            "components that could be computed."
        ),
        "currency_symbol": settings.currency_symbol,
    }


def _energy_efficiency(site_id: str) -> Component:
    """How the recent week compares with the site's own long-run daily average."""
    summary = energy_service.get_site_summary(site_id)
    if summary.day_count < 8:
        return Component(
            "energy_efficiency",
            "Energy efficiency",
            None,
            WEIGHTS["energy_efficiency"],
            "100 - (recent 7-day mean / long-run daily mean - 1) x 100",
            "Needs at least 8 days of history.",
            False,
        )

    series = energy_service.consumption_series(site_id, "daily")["points"]
    if len(series) < 8:
        return Component(
            "energy_efficiency",
            "Energy efficiency",
            None,
            WEIGHTS["energy_efficiency"],
            "100 - (recent 7-day mean / long-run daily mean - 1) x 100",
            "Not enough daily points.",
            False,
        )

    values = [point["energy_kwh"] for point in series]
    long_run = sum(values) / len(values)
    recent = sum(values[-7:]) / 7
    if long_run <= 0:
        return Component(
            "energy_efficiency",
            "Energy efficiency",
            None,
            WEIGHTS["energy_efficiency"],
            "100 - (recent 7-day mean / long-run daily mean - 1) x 100",
            "Long-run mean is zero.",
            False,
        )

    ratio = recent / long_run
    score = _clamp(100 - (ratio - 1) * 100)
    return Component(
        "energy_efficiency",
        "Energy efficiency",
        score,
        WEIGHTS["energy_efficiency"],
        "100 - (recent 7-day mean / long-run daily mean - 1) x 100, clamped to 0-100",
        (
            f"Recent 7-day mean {recent:.2f} kWh/day against a long-run "
            f"{long_run:.2f} kWh/day over {len(values)} days."
        ),
        True,
    )


def _appliance_efficiency(site_id: str) -> Component:
    """Share of assessed appliance-days that stayed within expectation."""
    assessed = 0
    normal = 0
    for appliance in ml_service.ml_appliances(site_id):
        analysis = ml_service.analyse(site_id, appliance)
        if not analysis.has_baseline:
            continue
        for day in analysis.days:
            if day.status in ("normal", "abnormal"):
                assessed += 1
                if day.status == "normal":
                    normal += 1

    if assessed < 5:
        return Component(
            "appliance_efficiency",
            "Appliance efficiency",
            None,
            WEIGHTS["appliance_efficiency"],
            "normal appliance-days / assessed appliance-days x 100",
            (
                "Fewer than 5 assessable appliance-days. This site lacks the on/off "
                "state signal or the history the inefficiency model needs."
            ),
            False,
        )

    score = normal / assessed * 100
    return Component(
        "appliance_efficiency",
        "Appliance efficiency",
        score,
        WEIGHTS["appliance_efficiency"],
        "normal appliance-days / assessed appliance-days x 100",
        f"{normal} of {assessed} assessed appliance-days stayed within expectation.",
        True,
    )


def _peak_behaviour(site_id: str) -> Component:
    """How much load sits in the expensive, high-demand hours."""
    settings = get_settings()
    profile = energy_service.hourly_profile(site_id)
    total = sum(entry["mean_energy_kwh"] for entry in profile)
    if total <= 0:
        return Component(
            "peak_behaviour",
            "Peak-load behaviour",
            None,
            WEIGHTS["peak_behaviour"],
            "100 - peak-hour share of energy x 100 / fair share",
            "No measurable consumption.",
            False,
        )

    peak_energy = sum(
        entry["mean_energy_kwh"] for entry in profile if entry["period"] == "peak"
    )
    peak_share = peak_energy / total
    peak_hour_count = max(len(settings.peak_hours), 1)
    fair_share = peak_hour_count / 24.0

    # A site with exactly its proportional share of load in peak hours scores 50.
    score = _clamp(100 - (peak_share / fair_share) * 50)
    return Component(
        "peak_behaviour",
        "Peak-load behaviour",
        score,
        WEIGHTS["peak_behaviour"],
        "100 - (peak-hour energy share / proportional share) x 50, clamped to 0-100",
        (
            f"{peak_share * 100:.1f}% of energy falls in the {peak_hour_count} peak "
            f"hours, whose proportional share would be {fair_share * 100:.1f}%."
        ),
        True,
    )


def _carbon_intensity(site_id: str) -> Component:
    """Daily carbon against a reference household budget."""
    #: Reference budget for a household day. A policy choice, stated openly.
    reference_kg_per_day = 6.0

    summary = energy_service.get_site_summary(site_id)
    if summary.day_count < 3:
        return Component(
            "carbon_intensity",
            "Carbon intensity",
            None,
            WEIGHTS["carbon_intensity"],
            "100 - (daily carbon / reference budget) x 50",
            "Needs at least 3 days of history.",
            False,
        )

    factor = carbon_service.emission_factor(site_id)
    daily_kwh = summary.total_energy_kwh / summary.day_count
    daily_carbon = daily_kwh * factor
    score = _clamp(100 - (daily_carbon / reference_kg_per_day) * 50)
    return Component(
        "carbon_intensity",
        "Carbon intensity",
        score,
        WEIGHTS["carbon_intensity"],
        f"100 - (daily carbon / {reference_kg_per_day:g} kg reference) x 50, clamped",
        (
            f"{daily_carbon:.2f} kg CO2e per day at {factor} kg/kWh, against a "
            f"{reference_kg_per_day:g} kg reference household budget."
        ),
        True,
    )


def _renewable_utilisation() -> Component:
    settings = get_settings()
    if not settings.solar_enabled:
        return Component(
            "renewable_utilisation",
            "Renewable utilisation",
            None,
            WEIGHTS["renewable_utilisation"],
            "renewable energy consumed / total energy consumed x 100",
            (
                "No renewable asset is configured and the dataset contains no "
                "generation measurements, so this component is excluded rather than "
                "scored as zero."
            ),
            False,
        )
    return Component(
        "renewable_utilisation",
        "Renewable utilisation",
        None,
        WEIGHTS["renewable_utilisation"],
        "renewable energy consumed / total energy consumed x 100",
        "A renewable asset is configured but no generation feed is connected.",
        False,
    )


def _grade(score: float | None) -> str:
    if score is None:
        return "unavailable"
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "good"
    if score >= 50:
        return "fair"
    return "needs attention"
