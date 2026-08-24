"""Deterministic, data-grounded explanations.

These sentences are assembled from measured values and model output only. No language
model is involved, so an explanation exists even when the LLM is unconfigured, and the
numbers in it can never be hallucinated. The AI assistant later rephrases these; it does
not invent them.
"""

from __future__ import annotations

from .config import FEATURE_LABELS
from .reliability import Reliability

#: Above this temperature, heat is a plausible driver of cooling load.
HOT_DAY_C = 32.0

#: Above this relative humidity, dehumidification adds meaningfully to cooling work.
HUMID_PCT = 70.0

#: Deviation magnitude below which the gap is noise, not a finding.
MATERIAL_DEVIATION_PCT = 10.0


def explain_day(
    *,
    appliance_label: str,
    status: str,
    active_kwh: float,
    expected_kwh: float | None,
    deviation_pct: float | None,
    runtime_hours: float,
    temperature: float,
    humidity: float,
    drivers: list[dict],
    probability: float | None,
    reliability: Reliability,
    star_adjusted: bool,
) -> str:
    """Build a paragraph explaining one appliance-day."""
    if status == "idle":
        return f"{appliance_label} did not run on this day."

    if status == "not_assessable" or expected_kwh is None:
        return (
            f"{appliance_label} used {active_kwh:.2f} kWh while running for "
            f"{runtime_hours:.1f} h, but no expected-energy baseline could be "
            "established for this day, so the usage cannot be judged."
        )

    parts: list[str] = []
    direction = "above" if (deviation_pct or 0) >= 0 else "below"
    magnitude = abs(deviation_pct) if deviation_pct is not None else 0.0

    parts.append(
        f"{appliance_label} used {active_kwh:.2f} kWh over {runtime_hours:.1f} h of "
        f"runtime, against an expected {expected_kwh:.2f} kWh for that much runtime "
        f"in these weather conditions"
    )

    if deviation_pct is None:
        parts[-1] += "."
    elif magnitude < MATERIAL_DEVIATION_PCT:
        parts[-1] += f" -- a difference of {magnitude:.0f}%, which is within normal variation."
    else:
        parts[-1] += f" -- {magnitude:.0f}% {direction} expectation."

    weather_clause = _weather_clause(temperature, humidity)
    if weather_clause:
        parts.append(weather_clause)

    if status == "abnormal":
        driver_clause = _driver_clause(drivers)
        if driver_clause:
            parts.append(driver_clause)
        if star_adjusted:
            parts.append(
                "The threshold used here is tightened for this home's appliance star "
                "rating, so a better-rated unit is held to a higher standard."
            )

    if probability is not None:
        if reliability is Reliability.GOOD:
            parts.append(
                f"The classifier scores this day at {probability:.0%} likelihood of "
                "inefficiency."
            )
        else:
            parts.append(
                f"A classifier score of {probability:.0%} is available but is not "
                "reliable for this appliance, so the verdict above comes from the "
                "expected-energy comparison instead."
            )

    return " ".join(parts)


def _weather_clause(temperature: float, humidity: float) -> str:
    """State what the weather does and does not explain.

    The expected-energy baseline already contains the heat index, so a hot day raises
    the expectation. Saying so is the difference between "high because it was hot" and
    "high even after allowing for the heat".
    """
    hot = temperature >= HOT_DAY_C
    humid = humidity >= HUMID_PCT

    if hot and humid:
        condition = f"It was hot and humid ({temperature:.0f} C, {humidity:.0f}% RH)"
    elif hot:
        condition = f"It was hot ({temperature:.0f} C)"
    elif humid:
        condition = f"Humidity was high ({humidity:.0f}% RH)"
    else:
        return (
            f"Conditions were moderate ({temperature:.0f} C, {humidity:.0f}% RH), so "
            "weather does not account for much of the load."
        )

    return (
        f"{condition}, and the expected figure already allows for that -- the "
        "comparison above is weather-adjusted."
    )


def _driver_clause(drivers: list[dict]) -> str:
    """Name the behaviours the model weighs most, with this day's values."""
    if not drivers:
        return ""
    named = []
    for driver in drivers[:2]:
        label = FEATURE_LABELS.get(driver["feature"], driver["feature"])
        value = driver.get("value")
        if value is None:
            named.append(label)
        else:
            named.append(f"{label} ({_format_value(driver['feature'], value)})")
    if not named:
        return ""
    joined = " and ".join(named)
    return (
        f"The model weighs {joined} most heavily when separating efficient from "
        "inefficient days for this appliance."
    )


def _format_value(feature: str, value: float) -> str:
    if feature == "duty_cycle":
        return f"{value * 100:.0f}% of the day"
    if feature in ("short_cycles", "cycles"):
        return f"{value:.0f}"
    if feature in ("std_power", "power_range", "power_gradient"):
        return f"{value:.0f} W"
    if feature == "heat_index":
        return f"{value:.1f}"
    return f"{value:.2f}"


def explain_site_summary(
    *,
    site_label: str,
    total_kwh: float,
    top_appliance: str | None,
    top_share_pct: float | None,
    abnormal: list[str],
) -> str:
    """One-paragraph summary of a site's day, used for the daily insight card."""
    parts = [f"{site_label} used {total_kwh:.2f} kWh."]
    if top_appliance and top_share_pct is not None:
        parts.append(
            f"{top_appliance} accounted for {top_share_pct:.0f}% of that."
        )
    if abnormal:
        listed = ", ".join(abnormal)
        verb = "was" if len(abnormal) == 1 else "were"
        parts.append(f"{listed} {verb} above the weather-adjusted expectation.")
    else:
        parts.append("No appliance exceeded its weather-adjusted expectation.")
    return " ".join(parts)
