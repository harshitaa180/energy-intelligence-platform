"""Electricity tariff engine.

Supports a flat rate and a time-of-use schedule. Rates come from configuration --
the dataset contains no tariff information -- so every monetary figure the platform
produces is an *estimate* and is labelled as one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from backend.config import get_settings


class TariffPeriod(str, Enum):
    PEAK = "peak"
    SHOULDER = "shoulder"
    OFF_PEAK = "off_peak"
    FLAT = "flat"


@dataclass(frozen=True)
class TariffSlot:
    hour: int
    period: TariffPeriod
    rate: float


def tariff_mode() -> str:
    return get_settings().tariff_mode.lower()


def rate_for_hour(hour: int) -> tuple[float, TariffPeriod]:
    """Rate and period for one hour of the day."""
    settings = get_settings()
    if tariff_mode() != "tou":
        return settings.default_tariff_per_kwh, TariffPeriod.FLAT
    if hour in settings.peak_hours:
        return settings.tou_peak_rate, TariffPeriod.PEAK
    if hour in settings.offpeak_hours:
        return settings.tou_offpeak_rate, TariffPeriod.OFF_PEAK
    return settings.tou_shoulder_rate, TariffPeriod.SHOULDER


def schedule() -> list[TariffSlot]:
    """The full 24-hour rate schedule, for charting and optimisation."""
    slots = []
    for hour in range(24):
        rate, period = rate_for_hour(hour)
        slots.append(TariffSlot(hour=hour, period=period, rate=rate))
    return slots


def cheapest_hours(count: int = 3, exclude: set[int] | None = None) -> list[int]:
    """The ``count`` cheapest hours of the day, cheapest first."""
    exclude = exclude or set()
    candidates = [slot for slot in schedule() if slot.hour not in exclude]
    candidates.sort(key=lambda slot: (slot.rate, slot.hour))
    return [slot.hour for slot in candidates[:count]]


def cost_of_series(timestamps: pd.Series, energy_kwh: pd.Series) -> float:
    """Cost of an energy series, priced at each interval's own hourly rate."""
    if len(timestamps) == 0:
        return 0.0
    rates = timestamps.dt.hour.map(lambda hour: rate_for_hour(hour)[0])
    return float((energy_kwh.to_numpy() * rates.to_numpy()).sum())


def cost_of_kwh(energy_kwh: float, hour: int | None = None) -> float:
    """Cost of a lump of energy. Without an hour, the flat/average rate is used."""
    if hour is None:
        return energy_kwh * average_rate()
    return energy_kwh * rate_for_hour(hour)[0]


def average_rate() -> float:
    """Unweighted mean rate across the day. Used when timing is unknown."""
    settings = get_settings()
    if tariff_mode() != "tou":
        return settings.default_tariff_per_kwh
    return sum(slot.rate for slot in schedule()) / 24.0


def describe() -> dict:
    """Tariff configuration as returned by the API, for display and transparency."""
    settings = get_settings()
    return {
        "mode": tariff_mode(),
        "currency": settings.currency,
        "currency_symbol": settings.currency_symbol,
        "flat_rate": settings.default_tariff_per_kwh,
        "average_rate": round(average_rate(), 4),
        "peak_rate": settings.tou_peak_rate,
        "shoulder_rate": settings.tou_shoulder_rate,
        "offpeak_rate": settings.tou_offpeak_rate,
        "peak_hours": sorted(settings.peak_hours),
        "offpeak_hours": sorted(settings.offpeak_hours),
        "schedule": [
            {"hour": slot.hour, "period": slot.period.value, "rate": slot.rate}
            for slot in schedule()
        ],
        "provenance": "estimated",
        "note": (
            "Tariff rates are configured in .env, not measured. Costs are estimates "
            "based on these rates."
        ),
    }
