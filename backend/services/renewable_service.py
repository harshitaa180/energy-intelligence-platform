"""Renewable, battery and EV integration points.

The dataset contains **no** solar generation, battery state or EV charging data. So
this module deliberately ships the *interfaces and optimisation logic* without any
measurements behind them. Three rules hold throughout:

1. Nothing here is ever tagged ``measured``.
2. With the modules disabled, every reading is ``None`` and ``available`` is ``False``.
3. With ``ALLOW_SIMULATION=true`` a clear-sky solar shape can be modelled for
   demonstration -- and it is tagged ``simulated`` in every payload that carries it.

Replacing this module with a real inverter or BMS feed means implementing
:func:`generation_profile` and :func:`battery_state`; nothing else has to change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.config import get_settings
from backend.services.weather_service import coordinates_for
from data.schema import Provenance


@dataclass(frozen=True)
class SolarAsset:
    enabled: bool
    capacity_kw: float


@dataclass(frozen=True)
class BatteryAsset:
    enabled: bool
    capacity_kwh: float
    reserve_pct: float
    max_charge_kw: float
    max_discharge_kw: float


@dataclass(frozen=True)
class EVAsset:
    enabled: bool
    battery_kwh: float
    charger_kw: float


def solar_asset() -> SolarAsset:
    settings = get_settings()
    return SolarAsset(settings.solar_enabled, settings.solar_capacity_kw)


def battery_asset() -> BatteryAsset:
    settings = get_settings()
    return BatteryAsset(
        settings.battery_enabled,
        settings.battery_capacity_kwh,
        settings.battery_reserve_pct,
        settings.battery_max_charge_kw,
        settings.battery_max_discharge_kw,
    )


def ev_asset() -> EVAsset:
    settings = get_settings()
    return EVAsset(settings.ev_enabled, settings.ev_battery_kwh, settings.ev_charger_kw)


def generation_profile(site_id: str) -> dict:
    """Hourly renewable availability, 0..1, for the optimiser.

    Without a configured asset this returns ``available: False`` and the optimiser
    falls back to pricing alone. It never fabricates generation.
    """
    settings = get_settings()
    asset = solar_asset()

    if not asset.enabled:
        return {
            "available": False,
            "provenance": Provenance.UNAVAILABLE.value,
            "hourly": [],
            "reason": (
                "No renewable asset is configured, and the dataset contains no solar "
                "generation measurements."
            ),
            "integration_ready": True,
        }

    if not settings.allow_simulation:
        return {
            "available": False,
            "provenance": Provenance.UNAVAILABLE.value,
            "hourly": [],
            "reason": (
                "A solar asset is configured but no generation feed is connected. "
                "Connect an inverter, or set ALLOW_SIMULATION=true to model a "
                "clear-sky profile for demonstration."
            ),
            "integration_ready": True,
        }

    return {
        "available": True,
        "provenance": Provenance.SIMULATED.value,
        "capacity_kw": asset.capacity_kw,
        "hourly": _clear_sky_profile(site_id, asset.capacity_kw),
        "reason": None,
        "integration_ready": True,
        "warning": (
            "SIMULATED clear-sky output for a "
            f"{asset.capacity_kw:g} kW array. These are modelled values, not "
            "measurements, and must not be read as real generation."
        ),
    }


def _clear_sky_profile(site_id: str, capacity_kw: float) -> list[dict]:
    """A smooth sunrise-to-sunset curve. Explicitly a demo shape, not a solar model."""
    coordinates = coordinates_for(site_id)
    # Day length shifts slightly with latitude; this is a presentation shape only.
    sunrise, sunset = (6.5, 18.5) if abs(coordinates.latitude) > 10 else (7.0, 19.0)
    profile = []
    for hour in range(24):
        if hour < sunrise or hour > sunset:
            fraction = 0.0
        else:
            position = (hour - sunrise) / (sunset - sunrise)
            fraction = max(0.0, math.sin(math.pi * position))
        profile.append(
            {
                "hour": hour,
                "availability": round(fraction, 4),
                "generation_kw": round(fraction * capacity_kw, 3),
            }
        )
    return profile


def battery_state() -> dict:
    """Battery telemetry. Always unavailable until a BMS feed is connected."""
    asset = battery_asset()
    if not asset.enabled:
        return {
            "available": False,
            "provenance": Provenance.UNAVAILABLE.value,
            "reason": "No battery is configured for this site.",
            "integration_ready": True,
        }
    return {
        "available": False,
        "provenance": Provenance.UNAVAILABLE.value,
        "capacity_kwh": asset.capacity_kwh,
        "reserve_pct": asset.reserve_pct,
        "max_charge_kw": asset.max_charge_kw,
        "max_discharge_kw": asset.max_discharge_kw,
        "state_of_charge_pct": None,
        "reason": (
            "A battery is configured but no state-of-charge feed is connected, so "
            "live charge level, charge and discharge power are unknown."
        ),
        "integration_ready": True,
    }


def energy_flow(site_id: str, home_load_kwh: float) -> dict:
    """The Solar -> Battery -> Home -> Grid flow diagram's data.

    With no renewable asset the only real edge is Grid -> Home, and the payload says
    so rather than drawing an invented solar arrow.
    """
    generation = generation_profile(site_id)
    battery = battery_state()

    nodes = [
        {"id": "grid", "label": "Grid", "available": True},
        {"id": "solar", "label": "Solar", "available": bool(generation["available"])},
        {"id": "battery", "label": "Battery", "available": bool(battery["available"])},
        {"id": "home", "label": "Home", "available": True},
    ]

    edges = [
        {
            "from": "grid",
            "to": "home",
            "energy_kwh": round(home_load_kwh, 3),
            "provenance": Provenance.MEASURED.value,
        }
    ]

    if generation["available"]:
        simulated_kwh = sum(entry["generation_kw"] for entry in generation["hourly"])
        edges.append(
            {
                "from": "solar",
                "to": "home",
                "energy_kwh": round(min(simulated_kwh, home_load_kwh), 3),
                "provenance": Provenance.SIMULATED.value,
            }
        )

    return {
        "site_id": site_id,
        "nodes": nodes,
        "edges": edges,
        "solar": generation,
        "battery": battery,
        "ev": describe_ev(),
        "status": (
            "renewable_integration_ready"
            if not generation["available"]
            else "renewable_simulated"
        ),
        "message": (
            "Renewable integration ready. No solar, battery or EV measurements exist "
            "in this dataset, so only grid supply is shown."
            if not generation["available"]
            else "Solar values shown are SIMULATED for demonstration."
        ),
    }


def describe_ev() -> dict:
    asset = ev_asset()
    if not asset.enabled:
        return {
            "available": False,
            "provenance": Provenance.UNAVAILABLE.value,
            "reason": "EV module is disabled. No EV charging data exists in this dataset.",
            "integration_ready": True,
        }
    return {
        "available": True,
        "provenance": Provenance.ESTIMATED.value,
        "battery_kwh": asset.battery_kwh,
        "charger_kw": asset.charger_kw,
        "state_of_charge_pct": None,
        "reason": (
            "EV module is enabled from configuration. State of charge must be supplied "
            "per request; it is not measured."
        ),
        "integration_ready": True,
    }
