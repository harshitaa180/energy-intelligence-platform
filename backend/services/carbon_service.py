"""Carbon intelligence.

    carbon_kg = energy_kwh * grid_emission_factor

The emission factor is configuration, not measurement, so every figure produced here
is tagged ``estimated`` and carries its factor and source so a reader can check it.
"""

from __future__ import annotations

import pandas as pd

from backend.config import get_settings
from data.loaders import channel_display_names
from data.schema import Provenance, site_profile
from data.transformers import resample_energy, site_interval_energy

#: Rough equivalences, used only for narrative context and labelled as such.
KG_CO2_PER_TREE_YEAR = 21.0
KG_CO2_PER_KM_PETROL_CAR = 0.17


def emission_factor(site_id: str) -> float:
    """kg CO2e per kWh for a site's grid, honouring per-country overrides."""
    settings = get_settings()
    country = site_profile(site_id).location
    return settings.emission_overrides.get(country, settings.grid_emission_factor)


def factor_source(site_id: str) -> str:
    settings = get_settings()
    country = site_profile(site_id).location
    if country in settings.emission_overrides:
        return f"Configured override for {country}"
    return settings.grid_emission_factor_source


def carbon_for(site_id: str, energy_kwh: float) -> float:
    return energy_kwh * emission_factor(site_id)


def carbon_summary(site_id: str, date: str) -> dict:
    """Daily, month-to-date and lifetime carbon for a site."""
    factor = emission_factor(site_id)
    target = pd.Timestamp(date)

    day_frame = site_interval_energy(
        site_id, target, target + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    )
    day_kwh = float(day_frame["total_energy_kwh"].sum()) if not day_frame.empty else 0.0

    month_start = target.replace(day=1)
    month_frame = site_interval_energy(
        site_id, month_start, target + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    )
    month_kwh = float(month_frame["total_energy_kwh"].sum()) if not month_frame.empty else 0.0

    all_frame = site_interval_energy(site_id)
    total_kwh = float(all_frame["total_energy_kwh"].sum()) if not all_frame.empty else 0.0
    day_count = (
        int(all_frame["date_time"].dt.normalize().nunique()) if not all_frame.empty else 0
    )

    daily_series = []
    if not all_frame.empty:
        rolled = resample_energy(all_frame, "daily")
        for _, row in rolled.iterrows():
            energy = float(row["total_energy_kwh"])
            daily_series.append(
                {
                    "date": pd.Timestamp(row["date_time"]).strftime("%Y-%m-%d"),
                    "energy_kwh": round(energy, 4),
                    "carbon_kg": round(energy * factor, 3),
                }
            )

    per_channel = []
    if not day_frame.empty:
        labels = channel_display_names(site_id)
        for column in day_frame.columns:
            if not column.endswith("_energy_kwh") or column == "total_energy_kwh":
                continue
            key = column[: -len("_energy_kwh")]
            energy = float(day_frame[column].sum())
            if energy <= 0:
                continue
            per_channel.append(
                {
                    "key": key,
                    "label": labels.get(key, key),
                    "energy_kwh": round(energy, 4),
                    "carbon_kg": round(energy * factor, 3),
                }
            )
        per_channel.sort(key=lambda entry: entry["carbon_kg"], reverse=True)

    daily_average = total_kwh / day_count if day_count else 0.0
    projected_annual_kg = daily_average * 365 * factor

    return {
        "site_id": site_id,
        "date": date,
        "emission_factor": factor,
        "emission_factor_source": factor_source(site_id),
        "unit": "kg CO2e per kWh",
        "daily": {
            "energy_kwh": round(day_kwh, 4),
            "carbon_kg": round(day_kwh * factor, 3),
        },
        "month_to_date": {
            "energy_kwh": round(month_kwh, 4),
            "carbon_kg": round(month_kwh * factor, 3),
        },
        "lifetime": {
            "energy_kwh": round(total_kwh, 3),
            "carbon_kg": round(total_kwh * factor, 3),
            "days": day_count,
        },
        "projected_annual_kg": round(projected_annual_kg, 1),
        "equivalences": {
            "trees_year_equivalent": round(projected_annual_kg / KG_CO2_PER_TREE_YEAR, 1),
            "petrol_car_km_equivalent": round(projected_annual_kg / KG_CO2_PER_KM_PETROL_CAR),
            "note": "Rough public equivalence factors, for scale only.",
        },
        "by_channel": per_channel,
        "daily_series": daily_series,
        "renewable": _renewable_block(),
        "provenance": Provenance.ESTIMATED.value,
        "note": (
            "Carbon is energy multiplied by a configured grid emission factor. It is "
            "not measured, and it does not account for time-of-day variation in grid "
            "carbon intensity."
        ),
    }


def _renewable_block() -> dict:
    """Renewable contribution. Zero and clearly unavailable unless configured."""
    settings = get_settings()
    if not settings.solar_enabled:
        return {
            "available": False,
            "generation_kwh": None,
            "avoided_carbon_kg": None,
            "provenance": Provenance.UNAVAILABLE.value,
            "note": (
                "No renewable asset is configured for this site and the dataset "
                "contains no generation measurements, so avoided carbon cannot be "
                "calculated."
            ),
        }
    return {
        "available": True,
        "generation_kwh": None,
        "avoided_carbon_kg": None,
        "provenance": Provenance.UNAVAILABLE.value,
        "note": (
            "A solar asset is configured but no generation readings are connected. "
            "Connect an inverter feed to populate avoided carbon."
        ),
    }


def describe() -> dict:
    settings = get_settings()
    return {
        "default_factor": settings.grid_emission_factor,
        "source": settings.grid_emission_factor_source,
        "overrides": settings.emission_overrides,
        "provenance": Provenance.ESTIMATED.value,
    }
