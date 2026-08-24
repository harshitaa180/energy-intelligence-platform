"""Load-shifting, demand response and EV charge optimisation.

The optimiser answers one question per appliance: *given this appliance's own measured
usage shape, is there a cheaper window in the day to run it?* Savings are computed by
repricing the appliance's real measured energy at a different hour's tariff -- they are
arithmetic on measured energy, not a guess, though they remain estimates because the
tariff itself is configuration.

Two rules are absolute:

* **Critical loads are never proposed for shifting.** Environmental chambers,
  refrigeration and medical equipment are excluded by classification, not by heuristic.
* **Nothing is claimed as saved that was not calculated.** Where a shift is impossible
  or worthless, the appliance is returned with a reason instead of a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from backend.config import get_settings
from backend.services import renewable_service, tariff_service
from data.loaders import channel_display_names, site_capabilities
from data.schema import Flexibility, Provenance
from data.transformers import channel_hourly_profile

#: Never recommend running a shiftable load during sleeping hours.
DEFAULT_QUIET_HOURS = {0, 1, 2, 3, 4, 5}

#: A saving below this is noise; the appliance is reported as already well placed.
MIN_MATERIAL_SAVING = 0.5


@dataclass
class ShiftPlan:
    channel: str
    label: str
    flexibility: str
    shiftable: bool
    reason: str | None
    current_hours: list[int]
    recommended_hours: list[int]
    daily_energy_kwh: float
    current_cost: float
    optimized_cost: float
    saving: float
    saving_pct: float
    renewable_aligned: bool


def _weighted_hours(profile: pd.DataFrame, top_n: int = 3) -> list[int]:
    """The hours where this appliance actually does most of its work."""
    if profile.empty:
        return []
    ranked = profile.sort_values("mean_energy_kwh", ascending=False)
    ranked = ranked[ranked["mean_energy_kwh"] > 0]
    return [int(hour) for hour in ranked.head(top_n)["hour"].tolist()]


def _preferred_hours(
    duration_hours: int,
    renewable: dict,
    constraints: dict,
) -> list[int]:
    """Cheapest feasible run window, preferring renewable-rich hours when available."""
    quiet = set(constraints.get("quiet_hours", DEFAULT_QUIET_HOURS))
    schedule = tariff_service.schedule()

    availability = {entry["hour"]: entry["availability"] for entry in renewable.get("hourly", [])}
    use_renewable = renewable.get("available") and availability

    def score(hour: int) -> tuple:
        rate, _ = tariff_service.rate_for_hour(hour)
        if use_renewable:
            # Prefer sunny hours first, then cheap ones.
            return (-availability.get(hour, 0.0), rate, hour)
        return (rate, hour)

    candidates = [slot.hour for slot in schedule if slot.hour not in quiet]
    candidates.sort(key=score)
    return sorted(candidates[: max(1, duration_hours)])


def optimize_site(site_id: str, constraints: dict | None = None) -> dict:
    """Build a current-vs-optimised schedule for every shiftable load at a site.

    Results depend only on the site and the caller's quiet hours, so they are cached
    on that pair. The dashboard, the recommendation engine and the demand-response
    view all ask for the same plan.
    """
    quiet = constraints.get("quiet_hours") if constraints else None
    return _optimize_site_cached(site_id, tuple(sorted(quiet)) if quiet else None)


@lru_cache(maxsize=64)
def _optimize_site_cached(site_id: str, quiet_hours: tuple[int, ...] | None) -> dict:
    constraints = {"quiet_hours": set(quiet_hours)} if quiet_hours else {}
    settings = get_settings()
    labels = channel_display_names(site_id)
    renewable = renewable_service.generation_profile(site_id)

    plans: list[ShiftPlan] = []
    for capability in site_capabilities(site_id):
        profile = channel_hourly_profile(site_id, capability.key)
        daily_energy = float(profile["mean_energy_kwh"].sum()) if not profile.empty else 0.0
        current_hours = _weighted_hours(profile)

        if capability.flexibility is Flexibility.CRITICAL:
            plans.append(
                ShiftPlan(
                    channel=capability.key,
                    label=labels.get(capability.key, capability.label),
                    flexibility=capability.flexibility.value,
                    shiftable=False,
                    reason=(
                        "Critical load. This appliance is never proposed for shifting "
                        "or shedding, regardless of cost."
                    ),
                    current_hours=current_hours,
                    recommended_hours=[],
                    daily_energy_kwh=round(daily_energy, 4),
                    current_cost=round(_cost_at(profile), 2),
                    optimized_cost=round(_cost_at(profile), 2),
                    saving=0.0,
                    saving_pct=0.0,
                    renewable_aligned=False,
                )
            )
            continue

        if daily_energy <= 0 or not current_hours:
            plans.append(
                ShiftPlan(
                    channel=capability.key,
                    label=labels.get(capability.key, capability.label),
                    flexibility=capability.flexibility.value,
                    shiftable=False,
                    reason="No measurable usage to shift.",
                    current_hours=[],
                    recommended_hours=[],
                    daily_energy_kwh=0.0,
                    current_cost=0.0,
                    optimized_cost=0.0,
                    saving=0.0,
                    saving_pct=0.0,
                    renewable_aligned=False,
                )
            )
            continue

        current_cost = _cost_at(profile)
        target_hours = _preferred_hours(len(current_hours), renewable, constraints)
        target_rate = sum(
            tariff_service.rate_for_hour(hour)[0] for hour in target_hours
        ) / max(len(target_hours), 1)

        if capability.flexibility is Flexibility.LESS_FLEXIBLE:
            # A thermostatic load cannot be moved wholesale. Only the portion that
            # actually sits in peak hours is realistically shiftable, so the hours
            # reported as "current" are the peak hours it really occupies -- not its
            # busiest hours overall, which may be nowhere near the peak window.
            movable_hours = _occupied_hours(profile, settings.peak_hours)
            shiftable_energy = _energy_in_hours(profile, settings.peak_hours)
            source_hours = movable_hours
            note = (
                "Partially flexible: only the peak-hour portion of this load is "
                "treated as movable, and comfort is assumed to be preserved."
            )
            current_rate_on_movable = (
                _cost_in_hours(profile, settings.peak_hours) / shiftable_energy
                if shiftable_energy > 0
                else 0.0
            )
        else:
            shiftable_energy = daily_energy
            source_hours = current_hours
            note = None
            current_rate_on_movable = current_cost / daily_energy if daily_energy else 0.0

        if shiftable_energy <= 0:
            plans.append(
                ShiftPlan(
                    channel=capability.key,
                    label=labels.get(capability.key, capability.label),
                    flexibility=capability.flexibility.value,
                    shiftable=False,
                    reason=(
                        "None of this load falls in peak hours, so there is nothing to "
                        "move without affecting comfort."
                    ),
                    current_hours=current_hours,
                    recommended_hours=[],
                    daily_energy_kwh=round(daily_energy, 4),
                    current_cost=round(current_cost, 2),
                    optimized_cost=round(current_cost, 2),
                    saving=0.0,
                    saving_pct=0.0,
                    renewable_aligned=False,
                )
            )
            continue

        optimized_cost = current_cost - shiftable_energy * (
            current_rate_on_movable - target_rate
        )
        saving = current_cost - optimized_cost

        if saving < MIN_MATERIAL_SAVING:
            plans.append(
                ShiftPlan(
                    channel=capability.key,
                    label=labels.get(capability.key, capability.label),
                    flexibility=capability.flexibility.value,
                    shiftable=False,
                    reason=(
                        "Already running in low-cost hours; moving it would save less "
                        f"than {settings.currency_symbol}{MIN_MATERIAL_SAVING:g} a day."
                    ),
                    current_hours=current_hours,
                    recommended_hours=[],
                    daily_energy_kwh=round(daily_energy, 4),
                    current_cost=round(current_cost, 2),
                    optimized_cost=round(current_cost, 2),
                    saving=0.0,
                    saving_pct=0.0,
                    renewable_aligned=False,
                )
            )
            continue

        plans.append(
            ShiftPlan(
                channel=capability.key,
                label=labels.get(capability.key, capability.label),
                flexibility=capability.flexibility.value,
                shiftable=True,
                reason=note,
                current_hours=source_hours,
                recommended_hours=target_hours,
                daily_energy_kwh=round(daily_energy, 4),
                current_cost=round(current_cost, 2),
                optimized_cost=round(max(optimized_cost, 0.0), 2),
                saving=round(saving, 2),
                saving_pct=round(saving / current_cost * 100, 1) if current_cost else 0.0,
                renewable_aligned=bool(renewable.get("available")),
            )
        )

    total_current = sum(plan.current_cost for plan in plans)
    total_optimized = sum(plan.optimized_cost for plan in plans)
    total_saving = round(total_current - total_optimized, 2)

    return {
        "site_id": site_id,
        "tariff": tariff_service.describe(),
        "renewable": renewable,
        "plans": [plan.__dict__ for plan in plans],
        "totals": {
            "current_cost_per_day": round(total_current, 2),
            "optimized_cost_per_day": round(total_optimized, 2),
            "saving_per_day": total_saving,
            "saving_per_month": round(total_saving * 30, 2),
            "saving_pct": (
                round(total_saving / total_current * 100, 1) if total_current else 0.0
            ),
        },
        "constraints": {
            "quiet_hours": sorted(constraints.get("quiet_hours", DEFAULT_QUIET_HOURS)),
            "critical_loads_excluded": [
                plan.label for plan in plans if plan.flexibility == Flexibility.CRITICAL.value
            ],
        },
        "provenance": Provenance.ESTIMATED.value,
        "method": (
            "Each appliance's measured average hourly energy is repriced at the "
            "cheapest feasible hours under the configured tariff. Savings are "
            "arithmetic on measured energy, but the tariff is configuration, so they "
            "remain estimates."
        ),
    }


def clear_cache() -> None:
    _optimize_site_cached.cache_clear()


def _cost_at(profile: pd.DataFrame) -> float:
    if profile.empty:
        return 0.0
    return float(
        sum(
            row["mean_energy_kwh"] * tariff_service.rate_for_hour(int(row["hour"]))[0]
            for _, row in profile.iterrows()
        )
    )


def _occupied_hours(profile: pd.DataFrame, hours: set[int]) -> list[int]:
    """Hours from ``hours`` in which this appliance actually consumes energy."""
    if profile.empty:
        return []
    subset = profile[(profile["hour"].isin(hours)) & (profile["mean_energy_kwh"] > 0)]
    return [int(hour) for hour in sorted(subset["hour"].tolist())]


def _energy_in_hours(profile: pd.DataFrame, hours: set[int]) -> float:
    if profile.empty:
        return 0.0
    return float(profile[profile["hour"].isin(hours)]["mean_energy_kwh"].sum())


def _cost_in_hours(profile: pd.DataFrame, hours: set[int]) -> float:
    if profile.empty:
        return 0.0
    subset = profile[profile["hour"].isin(hours)]
    return float(
        sum(
            row["mean_energy_kwh"] * tariff_service.rate_for_hour(int(row["hour"]))[0]
            for _, row in subset.iterrows()
        )
    )


def demand_response(site_id: str) -> dict:
    """Where a site's load sits relative to the price curve, and what could move."""
    settings = get_settings()
    from backend.services.energy_service import hourly_profile

    profile = hourly_profile(site_id)
    peak_energy = sum(entry["mean_energy_kwh"] for entry in profile if entry["period"] == "peak")
    total_energy = sum(entry["mean_energy_kwh"] for entry in profile)
    peak_cost = sum(entry["cost"] for entry in profile if entry["period"] == "peak")
    total_cost = sum(entry["cost"] for entry in profile)

    optimization = optimize_site(site_id)
    shiftable = [plan for plan in optimization["plans"] if plan["shiftable"]]

    return {
        "site_id": site_id,
        "tariff_mode": tariff_service.tariff_mode(),
        "profile": profile,
        "peak_share_pct": round(peak_energy / total_energy * 100, 1) if total_energy else 0.0,
        "peak_cost_share_pct": round(peak_cost / total_cost * 100, 1) if total_cost else 0.0,
        "peak_energy_kwh": round(peak_energy, 3),
        "total_energy_kwh": round(total_energy, 3),
        "peak_hours": sorted(settings.peak_hours),
        "shiftable_loads": shiftable,
        "opportunity": optimization["totals"],
        "provenance": Provenance.ESTIMATED.value,
        "note": (
            "Peak and off-peak windows come from the configured tariff. The dataset "
            "carries no utility price signal."
        ),
    }


def optimize_ev_charging(
    site_id: str,
    current_soc_pct: float,
    target_soc_pct: float,
    departure_hour: int,
) -> dict:
    """Cheapest charging window that still meets the departure requirement."""
    asset = renewable_service.ev_asset()
    if not asset.enabled:
        return {
            "available": False,
            "reason": (
                "The EV module is disabled and the dataset contains no EV charging "
                "data. Enable EV_ENABLED and set EV_BATTERY_KWH / EV_CHARGER_KW to use it."
            ),
            "provenance": Provenance.UNAVAILABLE.value,
        }
    if asset.battery_kwh <= 0 or asset.charger_kw <= 0:
        return {
            "available": False,
            "reason": "EV_BATTERY_KWH and EV_CHARGER_KW must both be greater than zero.",
            "provenance": Provenance.UNAVAILABLE.value,
        }

    needed_kwh = max(0.0, (target_soc_pct - current_soc_pct) / 100.0 * asset.battery_kwh)
    if needed_kwh <= 0:
        return {
            "available": True,
            "needed_kwh": 0.0,
            "reason": "The vehicle already meets the target state of charge.",
            "hours": [],
            "provenance": Provenance.ESTIMATED.value,
        }

    hours_needed = max(1, int(needed_kwh / asset.charger_kw + 0.999))
    renewable = renewable_service.generation_profile(site_id)
    availability = {entry["hour"]: entry["availability"] for entry in renewable.get("hourly", [])}

    # Only hours strictly before departure are usable.
    window = [hour for hour in range(24) if hour < departure_hour] or list(range(24))
    ranked = sorted(
        window,
        key=lambda hour: (
            -availability.get(hour, 0.0) if renewable.get("available") else 0,
            tariff_service.rate_for_hour(hour)[0],
            hour,
        ),
    )
    chosen = sorted(ranked[:hours_needed])
    feasible = len(chosen) >= hours_needed

    energy_per_hour = needed_kwh / len(chosen) if chosen else 0.0
    optimized_cost = sum(
        energy_per_hour * tariff_service.rate_for_hour(hour)[0] for hour in chosen
    )
    naive_hours = sorted(window)[:hours_needed]
    naive_cost = sum(
        (needed_kwh / max(len(naive_hours), 1)) * tariff_service.rate_for_hour(hour)[0]
        for hour in naive_hours
    )

    return {
        "available": True,
        "feasible": feasible,
        "needed_kwh": round(needed_kwh, 2),
        "hours_needed": hours_needed,
        "departure_hour": departure_hour,
        "hours": chosen,
        "optimized_cost": round(optimized_cost, 2),
        "plug_in_now_cost": round(naive_cost, 2),
        "saving": round(naive_cost - optimized_cost, 2),
        "renewable_aligned": bool(renewable.get("available")),
        "renewable_note": renewable.get("reason") or renewable.get("warning"),
        "provenance": Provenance.ESTIMATED.value,
        "warning": (
            None
            if feasible
            else (
                f"Only {len(chosen)} usable hour(s) before departure but "
                f"{hours_needed} are needed. The target state of charge cannot be met."
            )
        ),
    }
