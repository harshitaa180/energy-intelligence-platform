"""Daily feature extraction -- a faithful port of the notebook's ``extract_daily_features``.

The maths is unchanged. What changed is packaging: features are returned with bare
names (``duty_cycle`` rather than ``ac_duty_cycle``) so that one code path serves every
appliance, and the appliance key travels alongside the frame instead of inside every
column name.

``total_energy`` is deliberately kept as the notebook defined it -- a sum of watt
samples over on-state rows. It is a model feature, not a billing quantity. Billing
energy in kWh is computed in :mod:`data.transformers.aggregate`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import LONG_RUN_INTERVALS, SHORT_CYCLE_INTERVALS

#: Every column produced by :func:`extract_daily_features`.
FEATURE_NAMES: tuple[str, ...] = (
    "total_energy",
    "on_duration",
    "energy_per_hour",
    "duty_cycle",
    "cycles",
    "std_power",
    "power_range",
    "cv_power",
    "short_cycles",
    "long_run_ratio",
    "power_gradient",
    "temperature_mean",
    "temperature_std",
    "temp_runtime",
    "humidity_mean",
    "humidity_std",
    "humidity_runtime",
    "runtime_per_degree",
    "heat_index",
    "peak_average_ratio",
)


def _zeroed() -> dict[str, float]:
    return {name: 0.0 for name in FEATURE_NAMES}


def extract_daily_features(group: pd.DataFrame, appliance: str) -> dict[str, float]:
    """Features for one appliance on one day.

    ``group`` is all readings for a single (site, date). Returns an all-zero vector
    when the appliance never ran that day, matching the notebook's behaviour.
    """
    power_col = f"{appliance}_power"
    state_col = f"{appliance}_state"
    on_data = group[group[state_col] == 1]

    base = _zeroed()
    if len(on_data) == 0:
        return base

    energy = float(on_data[power_col].sum())
    on_duration = int(len(on_data))
    avg_power = float(on_data[power_col].mean())
    peak_power = float(on_data[power_col].max())
    min_power = float(on_data[power_col].min())
    std_power = float(on_data[power_col].std()) if on_duration > 1 else 0.0

    temperature_mean = float(group["Temperature"].mean())
    humidity_mean = float(group["Humidity"].mean())
    temperature_std = float(group["Temperature"].std()) if len(group) > 1 else 0.0
    humidity_std = float(group["Humidity"].std()) if len(group) > 1 else 0.0
    if np.isnan(temperature_std):
        temperature_std = 0.0
    if np.isnan(humidity_std):
        humidity_std = 0.0

    peak_average_ratio = peak_power / avg_power if avg_power > 0 else 0.0

    power_gradient = float(on_data[power_col].diff().abs().mean())
    if np.isnan(power_gradient):
        power_gradient = 0.0

    runtime_per_degree = on_duration / temperature_mean if temperature_mean > 0 else 0.0
    # Simple heat index used by the notebook -- not the NWS formula.
    heat_index = temperature_mean + 0.1 * humidity_mean
    temp_runtime = temperature_mean * on_duration
    humidity_runtime = humidity_mean * on_duration

    state_shift = group[state_col].diff().fillna(0)
    cycles = int((state_shift == 1).sum())

    run_lengths: list[int] = []
    current_run = 0
    for value in group[state_col]:
        if value == 1:
            current_run += 1
        elif current_run > 0:
            run_lengths.append(current_run)
            current_run = 0
    if current_run > 0:
        run_lengths.append(current_run)

    short_cycles = sum(1 for r in run_lengths if r < SHORT_CYCLE_INTERVALS)
    long_run_ratio = (
        sum(r for r in run_lengths if r > LONG_RUN_INTERVALS) / on_duration
        if on_duration > 0
        else 0.0
    )

    base.update(
        {
            "total_energy": energy,
            "on_duration": float(on_duration),
            "energy_per_hour": energy / on_duration,
            "duty_cycle": float(group[state_col].mean()),
            "cycles": float(cycles),
            "std_power": std_power,
            "power_range": peak_power - min_power,
            "cv_power": std_power / avg_power if avg_power > 0 else 0.0,
            "short_cycles": float(short_cycles),
            "long_run_ratio": float(long_run_ratio),
            "power_gradient": power_gradient,
            "temperature_mean": temperature_mean,
            "temperature_std": temperature_std,
            "temp_runtime": temp_runtime,
            "humidity_mean": humidity_mean,
            "humidity_std": humidity_std,
            "humidity_runtime": humidity_runtime,
            "runtime_per_degree": runtime_per_degree,
            "heat_index": heat_index,
            "peak_average_ratio": peak_average_ratio,
        }
    )
    return base


def build_daily_features(readings: pd.DataFrame, appliance: str) -> pd.DataFrame:
    """One row per day of daily features for a single site's readings.

    ``readings`` must be a single site's rows with ``date_time``, ``Temperature``,
    ``Humidity`` and the appliance's ``_state`` / ``_power`` columns.
    """
    power_col = f"{appliance}_power"
    state_col = f"{appliance}_state"
    if power_col not in readings.columns or state_col not in readings.columns:
        return pd.DataFrame()
    if readings.empty:
        return pd.DataFrame()

    frame = readings.copy()
    frame["date"] = frame["date_time"].dt.normalize()

    records = []
    for date, day_group in frame.groupby("date", sort=True):
        features = extract_daily_features(day_group, appliance)
        features["date"] = date
        records.append(features)

    daily = pd.DataFrame(records)
    return daily.sort_values("date").reset_index(drop=True)
