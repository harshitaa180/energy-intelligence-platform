"""Energy monitoring: sites, consumption series, appliance breakdowns, dashboards.

All figures here are measured -- they come from the meter readings -- except cost and
carbon, which depend on configured rates and are tagged accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from backend.config import get_settings
from backend.services import carbon_service, tariff_service
from data.loaders import (
    channel_display_names,
    get_site_readings,
    interval_hours,
    list_sites,
    site_capabilities,
    site_channel_keys,
)
from data.schema import Provenance, site_profile
from data.transformers import (
    COMPLETE_DAY_COVERAGE,
    channel_daily,
    channel_hourly_profile,
    complete_days_only,
    resample_energy,
    site_interval_energy,
)
from ml.model_loader import registry_pairs

GRANULARITIES = ("hourly", "daily", "weekly", "monthly")


@dataclass
class SiteSummary:
    site_id: str
    display_name: str
    location: str
    kind: str
    first_reading: str
    last_reading: str
    reading_count: int
    day_count: int
    total_energy_kwh: float
    channel_count: int
    ml_appliances: list[str]


def _ml_supported(site_id: str) -> list[str]:
    return [
        entry["appliance"]
        for entry in registry_pairs()
        if entry["site_id"] == site_id and entry.get("has_baseline")
    ]


@lru_cache(maxsize=32)
def get_site_summary(site_id: str) -> SiteSummary:
    readings = get_site_readings(site_id)
    energy = site_interval_energy(site_id)
    profile = site_profile(site_id)
    return SiteSummary(
        site_id=site_id,
        display_name=profile.display_name,
        location=profile.location,
        kind=profile.kind,
        first_reading=readings["date_time"].min().strftime("%Y-%m-%d %H:%M"),
        last_reading=readings["date_time"].max().strftime("%Y-%m-%d %H:%M"),
        reading_count=int(len(readings)),
        day_count=int(readings["date_time"].dt.normalize().nunique()),
        total_energy_kwh=round(float(energy["total_energy_kwh"].sum()), 3),
        channel_count=len(site_channel_keys(site_id)),
        ml_appliances=_ml_supported(site_id),
    )


def list_site_summaries() -> list[SiteSummary]:
    return [get_site_summary(site_id) for site_id in list_sites()]


@lru_cache(maxsize=32)
def latest_date(site_id: str) -> str:
    """Most recent day the platform will present as "today".

    This dataset has truncated first and last days and mid-series gaps, so the final
    calendar day is often only a few hours long. Presenting it as a full day would
    understate consumption and produce nonsense day-on-day comparisons, so the most
    recent *complete* day is preferred. If no day is complete, the last day is used
    and :func:`day_completeness` reports it as partial.
    """
    daily = resample_energy(site_interval_energy(site_id), "daily")
    if daily.empty:
        return get_site_readings(site_id)["date_time"].max().strftime("%Y-%m-%d")
    complete = complete_days_only(daily)
    frame = complete if not complete.empty else daily
    return pd.Timestamp(frame["date_time"].iloc[-1]).strftime("%Y-%m-%d")


def last_reading_date(site_id: str) -> str:
    """The final calendar day with any reading, complete or not."""
    return get_site_readings(site_id)["date_time"].max().strftime("%Y-%m-%d")


def day_completeness(site_id: str, date: str) -> dict:
    """How much of a day was actually recorded."""
    start = pd.Timestamp(date)
    frame = site_interval_energy(site_id, start, start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    expected = 24.0 / interval_hours()
    count = int(len(frame))
    coverage = min(count / expected, 1.0) if expected else 0.0
    return {
        "reading_count": count,
        "expected_readings": int(expected),
        "coverage_pct": round(coverage * 100, 1),
        "complete": coverage >= COMPLETE_DAY_COVERAGE,
        "note": (
            None
            if coverage >= COMPLETE_DAY_COVERAGE
            else (
                f"Only {count} of {int(expected)} expected readings exist for this day, "
                "so totals cover part of the day only."
            )
        ),
    }


@lru_cache(maxsize=32)
def showcase_date(site_id: str) -> str:
    """The most recent complete day on which an appliance could actually be assessed.

    :func:`latest_date` is the honest default for the date picker, but at some sites the
    last complete day falls outside the season the appliance runs in -- House_4's air
    conditioning stops in October -- so the dashboard would open on a day with nothing
    to show. This picks the most recent real day where the analysis has something to
    say. It is still a measured day, not a curated one; only the choice of *which* day
    to open on differs.
    """
    from backend.services import ml_service  # local import avoids a cycle

    assessable: set[str] = set()
    for appliance in ml_service.ml_appliances(site_id):
        analysis = ml_service.analyse(site_id, appliance)
        for day in analysis.days:
            if day.status in ("normal", "abnormal"):
                assessable.add(day.date)

    if not assessable:
        return latest_date(site_id)

    complete = {
        date for date in assessable if day_completeness(site_id, date)["complete"]
    }
    candidates = complete or assessable
    return max(candidates)


def available_dates(site_id: str) -> list[str]:
    readings = get_site_readings(site_id)
    dates = readings["date_time"].dt.normalize().unique()
    return sorted(pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates)


def consumption_series(
    site_id: str,
    granularity: str = "daily",
    start: str | None = None,
    end: str | None = None,
    channel: str | None = None,
) -> dict:
    """Consumption over time, optionally filtered to a date range and one channel."""
    if granularity not in GRANULARITIES:
        raise ValueError(f"granularity must be one of {GRANULARITIES}")

    frame = site_interval_energy(
        site_id,
        pd.Timestamp(start) if start else None,
        pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1) if end else None,
    )
    if frame.empty:
        return {"site_id": site_id, "granularity": granularity, "points": []}

    rolled = resample_energy(frame, granularity)
    if rolled.empty:
        return {"site_id": site_id, "granularity": granularity, "points": []}

    value_col = f"{channel}_energy_kwh" if channel else "total_energy_kwh"
    if value_col not in rolled.columns:
        value_col = "total_energy_kwh"

    points = []
    for _, row in rolled.iterrows():
        timestamp = pd.Timestamp(row["date_time"])
        energy = float(row[value_col])
        rate_hour = timestamp.hour if granularity == "hourly" else None
        points.append(
            {
                "timestamp": timestamp.isoformat(),
                "label": _label_for(timestamp, granularity),
                "energy_kwh": round(energy, 4),
                "cost": round(tariff_service.cost_of_kwh(energy, rate_hour), 2),
                "carbon_kg": round(carbon_service.carbon_for(site_id, energy), 3),
                "peak_power_w": round(float(row.get("peak_power_w", 0.0)), 1),
                "temperature": _round_or_none(row.get("Temperature")),
                "humidity": _round_or_none(row.get("Humidity")),
            }
        )

    return {
        "site_id": site_id,
        "granularity": granularity,
        "channel": channel,
        "points": points,
        "provenance": {
            "energy_kwh": Provenance.MEASURED.value,
            "cost": Provenance.ESTIMATED.value,
            "carbon_kg": Provenance.ESTIMATED.value,
        },
    }


def _label_for(timestamp: pd.Timestamp, granularity: str) -> str:
    if granularity == "hourly":
        return timestamp.strftime("%d %b %H:%M")
    if granularity == "daily":
        return timestamp.strftime("%d %b")
    if granularity == "weekly":
        return f"Week of {timestamp.strftime('%d %b')}"
    return timestamp.strftime("%b %Y")


def _round_or_none(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 1)


def day_totals(site_id: str, date: str) -> dict:
    """Everything measured about one day at one site."""
    start = pd.Timestamp(date)
    end = start + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    frame = site_interval_energy(site_id, start, end)

    if frame.empty:
        return {
            "site_id": site_id,
            "date": date,
            "available": False,
            "total_energy_kwh": 0.0,
            "cost": 0.0,
            "carbon_kg": 0.0,
            "peak_power_w": 0.0,
            "channels": [],
        }

    total = float(frame["total_energy_kwh"].sum())
    cost = tariff_service.cost_of_series(frame["date_time"], frame["total_energy_kwh"])
    labels = channel_display_names(site_id)

    channels = []
    for key in site_channel_keys(site_id):
        energy_col = f"{key}_energy_kwh"
        if energy_col not in frame.columns:
            continue
        energy = float(frame[energy_col].sum())
        channels.append(
            {
                "key": key,
                "label": labels.get(key, key),
                "energy_kwh": round(energy, 4),
                "share_pct": round(energy / total * 100, 1) if total > 0 else 0.0,
                "cost": round(
                    tariff_service.cost_of_series(frame["date_time"], frame[energy_col]), 2
                ),
                "carbon_kg": round(carbon_service.carbon_for(site_id, energy), 3),
                "peak_power_w": round(float(frame[f"{key}_power"].max()), 1),
                "mean_power_w": round(float(frame[f"{key}_power"].mean()), 1),
            }
        )
    channels.sort(key=lambda c: c["energy_kwh"], reverse=True)

    return {
        "site_id": site_id,
        "date": date,
        "available": True,
        "total_energy_kwh": round(total, 4),
        "cost": round(cost, 2),
        "carbon_kg": round(carbon_service.carbon_for(site_id, total), 3),
        "peak_power_w": round(float(frame["total_power_w"].max()), 1),
        "mean_power_w": round(float(frame["total_power_w"].mean()), 1),
        "reading_count": int(len(frame)),
        "completeness": day_completeness(site_id, date),
        "temperature_mean": round(float(frame["Temperature"].mean()), 1),
        "temperature_max": round(float(frame["Temperature"].max()), 1),
        "humidity_mean": round(float(frame["Humidity"].mean()), 1),
        "channels": channels,
    }


def compare_to_previous(site_id: str, date: str) -> dict:
    """This day against the trailing 7-day mean, for the dashboard delta chips."""
    target = pd.Timestamp(date)
    window_start = target - pd.Timedelta(days=7)
    frame = site_interval_energy(site_id, window_start, target - pd.Timedelta(seconds=1))
    today = day_totals(site_id, date)

    if frame.empty:
        return {"available": False, "change_pct": None, "baseline_kwh": None}

    # Partial days would drag the baseline down and inflate the day-on-day change.
    daily = complete_days_only(resample_energy(frame, "daily"))
    if daily.empty:
        return {"available": False, "change_pct": None, "baseline_kwh": None}

    baseline = float(daily["total_energy_kwh"].mean())
    if baseline <= 0:
        return {"available": False, "change_pct": None, "baseline_kwh": None}

    change = (today["total_energy_kwh"] - baseline) / baseline * 100
    return {
        "available": True,
        "baseline_kwh": round(baseline, 3),
        "baseline_days": int(len(daily)),
        "change_pct": round(change, 1),
    }


def hourly_profile(site_id: str, channel: str | None = None) -> list[dict]:
    """Average consumption by hour of day, with each hour's tariff attached."""
    keys = [channel] if channel else site_channel_keys(site_id)
    combined: dict[int, float] = {hour: 0.0 for hour in range(24)}
    for key in keys:
        profile = channel_hourly_profile(site_id, key)
        if profile.empty:
            continue
        for _, row in profile.iterrows():
            combined[int(row["hour"])] += float(row["mean_energy_kwh"])

    out = []
    for hour in range(24):
        rate, period = tariff_service.rate_for_hour(hour)
        energy = combined[hour]
        out.append(
            {
                "hour": hour,
                "mean_energy_kwh": round(energy, 4),
                "rate": rate,
                "period": period.value,
                "cost": round(energy * rate, 2),
            }
        )
    return out


def channel_history(site_id: str, channel: str) -> list[dict]:
    """Per-day measured history for one channel."""
    daily = channel_daily(site_id, channel)
    if daily.empty:
        return []
    out = []
    for _, row in daily.iterrows():
        energy = float(row["energy_kwh"])
        runtime = row["runtime_hours"]
        out.append(
            {
                "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
                "energy_kwh": round(energy, 4),
                "peak_power_w": round(float(row["peak_power_w"]), 1),
                "mean_power_w": round(float(row["mean_power_w"]), 1),
                "runtime_hours": None if pd.isna(runtime) else round(float(runtime), 2),
                "temperature_mean": round(float(row["temperature_mean"]), 1),
                "humidity_mean": round(float(row["humidity_mean"]), 1),
                "cost": round(tariff_service.cost_of_kwh(energy), 2),
            }
        )
    return out


def capabilities_payload(site_id: str) -> list[dict]:
    """What the platform can and cannot do for each channel at a site."""
    trained = {
        entry["appliance"]: entry
        for entry in registry_pairs()
        if entry["site_id"] == site_id
    }
    payload = []
    for capability in site_capabilities(site_id):
        entry = trained.get(capability.key)
        payload.append(
            {
                "key": capability.key,
                "label": capability.label,
                "category": capability.category,
                "flexibility": capability.flexibility.value,
                "has_power_signal": capability.has_power_signal,
                "has_state_signal": capability.has_state_signal,
                "has_metadata": capability.has_metadata,
                "has_baseline": bool(entry and entry.get("has_baseline")),
                "has_classifier": bool(entry and entry.get("has_classifier")),
                "notes": capability.notes,
            }
        )
    return payload


def platform_stats() -> dict:
    """Corpus-level numbers for the health endpoint and the About panel."""
    settings = get_settings()
    summaries = list_site_summaries()
    return {
        "sites": len(summaries),
        "readings": sum(s.reading_count for s in summaries),
        "interval_hours": interval_hours(),
        "total_energy_kwh": round(sum(s.total_energy_kwh for s in summaries), 2),
        "demo_site_id": settings.demo_site_id,
    }


def clear_cache() -> None:
    get_site_summary.cache_clear()
    latest_date.cache_clear()
    showcase_date.cache_clear()
