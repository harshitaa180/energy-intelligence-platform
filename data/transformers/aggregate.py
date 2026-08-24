"""Turn instantaneous watt readings into energy, and roll them up over time.

The one conversion everything else depends on::

    kWh(interval) = power_W * interval_hours / 1000

Note this sums over *all* rows, not only on-state rows: standby draw is real
consumption and appears on the bill. The ML pipeline's ``total_energy`` feature is a
different quantity (a sum of watt samples over on-state rows only) and is computed
separately in :mod:`ml.feature_engineering`.
"""

from __future__ import annotations

import pandas as pd

from ..loaders.readings import get_site_readings, interval_hours, site_channel_keys

FREQ_ALIASES = {
    "hourly": "h",
    "daily": "D",
    "weekly": "W-MON",
    "monthly": "MS",
}


def add_energy_columns(df: pd.DataFrame, channel_keys: list[str]) -> pd.DataFrame:
    """Append ``<key>_energy_kwh`` for each channel plus a ``total_energy_kwh`` column."""
    hours = interval_hours()
    out = df.copy()
    energy_cols = []
    for key in channel_keys:
        power_col = f"{key}_power"
        if power_col not in out.columns:
            continue
        col = f"{key}_energy_kwh"
        out[col] = out[power_col] * hours / 1000.0
        energy_cols.append(col)
    out["total_energy_kwh"] = out[energy_cols].sum(axis=1) if energy_cols else 0.0
    out["total_power_w"] = (
        out[[f"{k}_power" for k in channel_keys if f"{k}_power" in out.columns]].sum(axis=1)
        if channel_keys
        else 0.0
    )
    return out


def site_interval_energy(
    site_id: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Half-hourly readings for a site with energy columns attached."""
    df = get_site_readings(site_id)
    if start is not None:
        df = df[df["date_time"] >= start]
    if end is not None:
        df = df[df["date_time"] <= end]
    return add_energy_columns(df, site_channel_keys(site_id))


def resample_energy(df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    """Roll interval energy up to hourly / daily / weekly / monthly buckets.

    Returns one row per bucket with total and per-channel energy, peak power, and
    mean weather.
    """
    if granularity not in FREQ_ALIASES:
        raise ValueError(f"Unsupported granularity {granularity!r}")
    if df.empty:
        return pd.DataFrame()

    freq = FREQ_ALIASES[granularity]
    indexed = df.set_index("date_time")

    energy_cols = [c for c in indexed.columns if c.endswith("_energy_kwh")]
    agg: dict[str, str] = {col: "sum" for col in energy_cols}
    agg["total_power_w"] = "max"
    if "Temperature" in indexed.columns:
        agg["Temperature"] = "mean"
    if "Humidity" in indexed.columns:
        agg["Humidity"] = "mean"

    grouped = indexed.resample(freq).agg(agg)
    grouped = grouped.rename(columns={"total_power_w": "peak_power_w"})
    grouped["reading_count"] = indexed["total_energy_kwh"].resample(freq).count()
    grouped = grouped[grouped["reading_count"] > 0]
    grouped["coverage"] = (
        grouped["reading_count"] / expected_readings(granularity)
    ).clip(upper=1.0)
    return grouped.reset_index()


def expected_readings(granularity: str) -> float:
    """How many readings a complete bucket should contain at this sampling rate."""
    per_day = 24.0 / interval_hours()
    return {
        "hourly": 1.0 / interval_hours(),
        "daily": per_day,
        "weekly": per_day * 7,
        "monthly": per_day * 30,
    }[granularity]


#: A day below this coverage is partial. Gaps and truncated first/last days are
#: common in this dataset, and including them would drag averages and forecasts down.
COMPLETE_DAY_COVERAGE = 0.9


def complete_days_only(daily: pd.DataFrame) -> pd.DataFrame:
    """Drop partial days from a daily rollup."""
    if daily.empty or "coverage" not in daily.columns:
        return daily
    return daily[daily["coverage"] >= COMPLETE_DAY_COVERAGE].reset_index(drop=True)


def site_daily(site_id: str) -> pd.DataFrame:
    """Daily energy rollup for a site."""
    return resample_energy(site_interval_energy(site_id), "daily")


def channel_daily(site_id: str, channel_key: str) -> pd.DataFrame:
    """Per-day energy, runtime and peak power for one channel.

    ``runtime_hours`` counts on-state intervals; it is ``NaN`` when the site has no
    usable state signal, rather than a misleading zero.
    """
    df = site_interval_energy(site_id)
    if df.empty:
        return pd.DataFrame()

    power_col = f"{channel_key}_power"
    state_col = f"{channel_key}_state"
    energy_col = f"{channel_key}_energy_kwh"
    if energy_col not in df.columns:
        return pd.DataFrame()

    hours = interval_hours()
    has_state = state_col in df.columns and bool(df[state_col].sum() > 0)

    frame = pd.DataFrame(
        {
            "date": df["date_time"].dt.normalize(),
            "energy_kwh": df[energy_col],
            "power_w": df[power_col],
            "on": df[state_col] if state_col in df.columns else 0,
            "temperature": df["Temperature"],
            "humidity": df["Humidity"],
        }
    )
    grouped = frame.groupby("date", as_index=False).agg(
        energy_kwh=("energy_kwh", "sum"),
        peak_power_w=("power_w", "max"),
        mean_power_w=("power_w", "mean"),
        on_intervals=("on", "sum"),
        temperature_mean=("temperature", "mean"),
        humidity_mean=("humidity", "mean"),
    )
    grouped["runtime_hours"] = (
        grouped["on_intervals"] * hours if has_state else float("nan")
    )
    return grouped


def channel_hourly_profile(site_id: str, channel_key: str) -> pd.DataFrame:
    """Average energy by hour of day -- the shape used for load-shifting advice."""
    df = site_interval_energy(site_id)
    energy_col = f"{channel_key}_energy_kwh"
    if df.empty or energy_col not in df.columns:
        return pd.DataFrame()

    frame = pd.DataFrame(
        {
            "hour": df["date_time"].dt.hour,
            "date": df["date_time"].dt.normalize(),
            "energy_kwh": df[energy_col],
        }
    )
    per_day_hour = frame.groupby(["date", "hour"], as_index=False)["energy_kwh"].sum()
    profile = per_day_hour.groupby("hour", as_index=False)["energy_kwh"].mean()
    profile = profile.rename(columns={"energy_kwh": "mean_energy_kwh"})
    # Guarantee all 24 hours are present so charts do not gap.
    full = pd.DataFrame({"hour": range(24)})
    return full.merge(profile, on="hour", how="left").fillna({"mean_energy_kwh": 0.0})
