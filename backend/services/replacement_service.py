"""Appliance replacement analysis.

Honest answer first: this dataset contains brands, star ratings and unit counts, but
**no appliance prices and no rated power draw**. So a payback period cannot be computed
from data alone. What *can* be computed from measured energy is the annual running cost
of what is installed, and the annual saving implied by moving to a higher star rating
under the BEE scheme's own step assumption.

Purchase price is therefore an input, not a fact. Without one the service returns the
saving and explicitly reports payback as unavailable; with one supplied by the caller it
computes payback and labels the whole result an estimate.
"""

from __future__ import annotations

from backend.services import carbon_service, energy_service, tariff_service
from data.loaders import units_for
from data.schema import CHANNELS_BY_KEY, Provenance

#: Each additional BEE star is worth roughly this much less energy for the same
#: service. A published rule of thumb, not a measurement from this dataset.
ENERGY_SAVING_PER_STAR = 0.10
MAX_STARS = 5.0


def analyse_replacement(
    site_id: str,
    appliance: str,
    target_star_rating: float | None = None,
    replacement_cost: float | None = None,
) -> dict:
    spec = CHANNELS_BY_KEY.get(appliance)
    if spec is None or spec.metadata_type is None:
        return _unavailable(
            site_id, appliance, "This channel has no appliance metadata entry."
        )

    rows = units_for(site_id, spec.metadata_type)
    if rows.empty:
        return _unavailable(
            site_id,
            appliance,
            (
                f"No appliance metadata exists for {site_id}, so brand and star rating "
                "are unknown and replacement cannot be assessed."
            ),
        )

    rated = rows.dropna(subset=["star_rating"])
    if rated.empty:
        return _unavailable(
            site_id,
            appliance,
            "Every unit at this site has an unknown star rating.",
        )

    current_stars = float(
        (rated["star_rating"] * rated["appliance_count"]).sum()
        / rated["appliance_count"].sum()
    )
    target_stars = target_star_rating if target_star_rating is not None else MAX_STARS

    history = energy_service.channel_history(site_id, appliance)
    if not history:
        return _unavailable(site_id, appliance, "No measured history for this appliance.")

    days = len(history)
    total_kwh = sum(entry["energy_kwh"] for entry in history)
    daily_kwh = total_kwh / days
    annual_kwh = daily_kwh * 365
    annual_cost = tariff_service.cost_of_kwh(annual_kwh)
    annual_carbon = carbon_service.carbon_for(site_id, annual_kwh)

    if target_stars <= current_stars:
        return {
            "site_id": site_id,
            "appliance": appliance,
            "available": True,
            "recommended": False,
            "reason": (
                f"The installed units already average {current_stars:.1f} stars, at or "
                f"above the {target_stars:.0f}-star target. Replacement is not "
                "indicated."
            ),
            "current": _current_block(
                current_stars, days, annual_kwh, annual_cost, annual_carbon, rows
            ),
            "provenance": Provenance.ESTIMATED.value,
        }

    reduction = min((target_stars - current_stars) * ENERGY_SAVING_PER_STAR, 0.6)
    projected_kwh = annual_kwh * (1 - reduction)
    annual_saving_kwh = annual_kwh - projected_kwh
    annual_saving_cost = tariff_service.cost_of_kwh(annual_saving_kwh)
    annual_saving_carbon = carbon_service.carbon_for(site_id, annual_saving_kwh)

    payback_years = None
    payback_note = (
        "Purchase price is not in the dataset. Supply `replacement_cost` to compute a "
        "payback period."
    )
    if replacement_cost is not None and replacement_cost > 0 and annual_saving_cost > 0:
        payback_years = replacement_cost / annual_saving_cost
        payback_note = "Payback = replacement cost / annual saving."

    return {
        "site_id": site_id,
        "appliance": appliance,
        "available": True,
        "recommended": annual_saving_cost > 0,
        "current": _current_block(
            current_stars, days, annual_kwh, annual_cost, annual_carbon, rows
        ),
        "replacement": {
            "target_star_rating": target_stars,
            "assumed_energy_reduction_pct": round(reduction * 100, 1),
            "projected_annual_kwh": round(projected_kwh, 1),
            "projected_annual_cost": round(tariff_service.cost_of_kwh(projected_kwh), 2),
            "replacement_cost": replacement_cost,
        },
        "savings": {
            "annual_kwh": round(annual_saving_kwh, 1),
            "annual_cost": round(annual_saving_cost, 2),
            "annual_carbon_kg": round(annual_saving_carbon, 1),
        },
        "payback_years": round(payback_years, 1) if payback_years is not None else None,
        "payback_note": payback_note,
        "provenance": Provenance.ESTIMATED.value,
        "assumptions": [
            (
                f"Each additional BEE star is assumed to cut energy by "
                f"{ENERGY_SAVING_PER_STAR * 100:.0f}% for the same service. This is a "
                "published rule of thumb, not measured from this dataset."
            ),
            (
                f"Annual energy is this appliance's measured {days}-day average scaled "
                "to 365 days, which assumes the observed season is representative. For "
                "a seasonal load such as an air conditioner it is likely an "
                "over-estimate."
            ),
            "Cost uses the configured tariff, not a real bill.",
        ],
    }


def _current_block(
    stars: float, days: int, annual_kwh: float, annual_cost: float, annual_carbon: float, rows
) -> dict:
    return {
        "weighted_star_rating": round(stars, 2),
        "measured_days": days,
        "annual_kwh": round(annual_kwh, 1),
        "annual_cost": round(annual_cost, 2),
        "annual_carbon_kg": round(annual_carbon, 1),
        "units": [
            {
                "appliance_id": row["appliance_id"],
                "brand": row["brand"],
                "star_rating": (
                    None if row["star_rating"] != row["star_rating"] else float(row["star_rating"])
                ),
                "count": int(row["appliance_count"]),
            }
            for _, row in rows.iterrows()
        ],
    }


def _unavailable(site_id: str, appliance: str, reason: str) -> dict:
    return {
        "site_id": site_id,
        "appliance": appliance,
        "available": False,
        "reason": reason,
        "provenance": Provenance.UNAVAILABLE.value,
    }
