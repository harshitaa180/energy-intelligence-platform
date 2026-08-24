"""Backend-facing wrapper over the ML package.

Keeps FastAPI ignorant of pandas and of artefact loading, and translates the ML
layer's per-day analysis into the appliance-shaped payloads the UI consumes.
"""

from __future__ import annotations

from functools import lru_cache

from backend.services import carbon_service, tariff_service
from data.loaders import channel_display_names, site_capabilities, unit_count, units_for
from data.schema import CHANNELS_BY_KEY, Provenance
from ml.model_loader import load_pair, load_registry, registry_pairs
from ml.prediction import ApplianceAnalysis, DayAnalysis, analyze_energy_usage


def registry_summary() -> dict:
    registry = load_registry()
    pairs = registry.get("pairs", [])
    return {
        "pipeline_version": registry.get("pipeline_version"),
        "trained_at": registry.get("trained_at"),
        "pairs_attempted": len(pairs),
        "pairs_with_classifier": sum(1 for p in pairs if p.get("has_classifier")),
        "pairs_with_baseline": sum(1 for p in pairs if p.get("has_baseline")),
        "pairs": [
            {
                "site_id": entry["site_id"],
                "appliance": entry["appliance"],
                "status": entry.get("status"),
                "active_days": entry.get("active_days"),
                "star_adjusted": entry.get("star_adjusted"),
                "has_classifier": entry.get("has_classifier"),
                "metrics": _public_metrics(entry.get("metrics", {})),
            }
            for entry in pairs
        ],
    }


def _public_metrics(metrics: dict) -> dict:
    keys = (
        "baseline_r2",
        "test_accuracy",
        "test_f1",
        "test_precision",
        "test_recall",
        "roc_auc",
        "pr_auc",
        "train_days",
        "test_days",
        "test_positives",
        "reliability_warning",
        "classifier_skip_reason",
    )
    return {key: metrics[key] for key in keys if key in metrics}


def ml_appliances(site_id: str) -> list[str]:
    """Channels at this site the inefficiency pipeline covers."""
    return [
        capability.key
        for capability in site_capabilities(site_id)
        if (spec := CHANNELS_BY_KEY.get(capability.key)) is not None and spec.ml_appliance
    ]


def analyse(site_id: str, appliance: str) -> ApplianceAnalysis:
    return analyze_energy_usage(site_id, appliance)


def day_payload(site_id: str, appliance: str, date: str | None = None) -> dict:
    """One appliance on one day, enriched with cost, carbon and metadata."""
    analysis = analyse(site_id, appliance)
    day = analysis.by_date(date) if date else analysis.latest()
    if day is None:
        return {
            "site_id": site_id,
            "appliance": appliance,
            "appliance_label": analysis.appliance_label,
            "available": False,
            "reason": (
                f"No readings for {appliance} at {site_id} on {date}."
                if date
                else f"No readings for {appliance} at {site_id}."
            ),
        }
    return _enrich(day, analysis)


def _enrich(day: DayAnalysis, analysis: ApplianceAnalysis) -> dict:
    payload = day.to_dict()
    payload["available"] = True
    payload["cost"] = round(tariff_service.cost_of_kwh(day.energy_kwh), 2)
    payload["carbon_kg"] = round(
        carbon_service.carbon_for(day.site_id, day.energy_kwh), 3
    )
    if day.expected_energy_kwh is not None:
        excess = max(day.active_energy_kwh - day.expected_energy_kwh, 0.0)
        payload["excess_cost"] = round(tariff_service.cost_of_kwh(excess), 2)
        payload["excess_carbon_kg"] = round(
            carbon_service.carbon_for(day.site_id, excess), 3
        )
    else:
        payload["excess_cost"] = None
        payload["excess_carbon_kg"] = None

    payload["has_classifier"] = analysis.has_classifier
    payload["model_metrics"] = _public_metrics(analysis.metrics)
    payload["feature_importance"] = analysis.feature_importance
    payload["metadata"] = appliance_metadata(day.site_id, day.appliance)
    payload["cost_provenance"] = Provenance.ESTIMATED.value
    return payload


def appliance_metadata(site_id: str, appliance: str) -> dict:
    """Brand, star rating and unit count, or an explicit statement that it is absent."""
    spec = CHANNELS_BY_KEY.get(appliance)
    if spec is None or spec.metadata_type is None:
        return {
            "available": False,
            "reason": "This channel has no entry in the appliance metadata file.",
        }
    rows = units_for(site_id, spec.metadata_type)
    if rows.empty:
        return {
            "available": False,
            "reason": (
                f"No appliance metadata exists for {site_id}. Brand, star rating and "
                "replacement analysis are unavailable for this site."
            ),
        }
    units = []
    for _, row in rows.iterrows():
        rating = row["star_rating"]
        units.append(
            {
                "appliance_id": row["appliance_id"],
                "brand": row["brand"],
                "star_rating": None if rating != rating else float(rating),  # NaN check
                "count": int(row["appliance_count"]),
            }
        )
    rated = [u for u in units if u["star_rating"] is not None]
    weighted = (
        sum(u["star_rating"] * u["count"] for u in rated) / sum(u["count"] for u in rated)
        if rated
        else None
    )
    return {
        "available": True,
        "appliance_type": spec.metadata_type,
        "unit_count": unit_count(site_id, spec.metadata_type),
        "units": units,
        "weighted_star_rating": round(weighted, 2) if weighted is not None else None,
        "unrated_units": len(units) - len(rated),
        "note": (
            "Star ratings are missing for some units; the weighted rating uses only "
            "the rated ones."
            if len(units) != len(rated)
            else None
        ),
    }


def site_appliance_overview(site_id: str, date: str | None = None) -> list[dict]:
    """Every ML-covered appliance at a site for one day, ranked by consumption."""
    payloads = []
    for appliance in ml_appliances(site_id):
        payload = day_payload(site_id, appliance, date)
        if payload.get("available"):
            payloads.append(payload)
    payloads.sort(key=lambda p: p.get("energy_kwh", 0), reverse=True)
    return payloads


def anomalies(site_id: str, limit: int = 20) -> list[dict]:
    """Wrapper so the expensive scan is computed once per site and then sliced."""
    return _anomalies_cached(site_id)[:limit]


@lru_cache(maxsize=32)
def _anomalies_cached(site_id: str) -> list[dict]:
    """Days flagged as above their weather-adjusted expectation, most recent first.

    Anomaly types are separated so the UI can say *what kind* of abnormality it is
    rather than lumping everything under "high usage".
    """
    found: list[dict] = []
    for appliance in ml_appliances(site_id):
        analysis = analyse(site_id, appliance)
        if not analysis.has_baseline:
            continue
        history = analysis.days
        runtimes = [d.runtime_hours for d in history if d.runtime_hours]
        median_runtime = _median(runtimes)
        peaks = [d.peak_power_w for d in history if d.peak_power_w > 0]
        median_peak = _median(peaks)

        for day in history:
            types = _classify_anomaly(day, median_runtime, median_peak)
            if not types:
                continue
            found.append(
                {
                    "site_id": site_id,
                    "appliance": day.appliance,
                    "appliance_label": day.appliance_label,
                    "date": day.date,
                    "types": types,
                    "severity": _severity(day),
                    "deviation_pct": day.deviation_pct,
                    "energy_kwh": day.energy_kwh,
                    "expected_energy_kwh": day.expected_energy_kwh,
                    "runtime_hours": day.runtime_hours,
                    "peak_power_w": day.peak_power_w,
                    "temperature_mean": day.temperature_mean,
                    "probability": day.probability,
                    "reliability": day.reliability,
                    "explanation": day.explanation,
                    "excess_cost": round(
                        tariff_service.cost_of_kwh(
                            max(
                                (day.active_energy_kwh or 0)
                                - (day.expected_energy_kwh or 0),
                                0.0,
                            )
                        ),
                        2,
                    ),
                }
            )

    found.sort(key=lambda entry: (entry["date"], entry["severity"]), reverse=True)
    return found


def clear_cache() -> None:
    _anomalies_cached.cache_clear()


def _classify_anomaly(
    day: DayAnalysis, median_runtime: float | None, median_peak: float | None
) -> list[dict]:
    """Separate the kinds of abnormality rather than reporting one generic flag."""
    types: list[dict] = []

    if day.status == "abnormal" and day.deviation_pct is not None:
        types.append(
            {
                "type": "high_consumption",
                "label": "Above weather-adjusted expectation",
                "detail": (
                    f"Used {day.deviation_pct:+.0f}% against the expected energy for "
                    "this much runtime in these conditions."
                ),
            }
        )

    if (
        median_runtime
        and day.runtime_hours
        and day.runtime_hours > median_runtime * 1.5
        and day.runtime_hours - median_runtime >= 1.0
    ):
        types.append(
            {
                "type": "runtime",
                "label": "Ran longer than usual",
                "detail": (
                    f"Ran {day.runtime_hours:.1f} h against a typical "
                    f"{median_runtime:.1f} h for this appliance."
                ),
            }
        )

    if median_peak and day.peak_power_w > median_peak * 1.6:
        types.append(
            {
                "type": "power",
                "label": "Unusual power draw",
                "detail": (
                    f"Peaked at {day.peak_power_w:.0f} W against a typical "
                    f"{median_peak:.0f} W."
                ),
            }
        )

    if day.short_cycles >= 4 and day.status == "abnormal":
        types.append(
            {
                "type": "cycling",
                "label": "Short cycling",
                "detail": (
                    f"{day.short_cycles} short on/off cycles, which wastes energy on "
                    "repeated start-up."
                ),
            }
        )

    return types


def _severity(day: DayAnalysis) -> str:
    if day.deviation_pct is None:
        return "info"
    if day.deviation_pct >= 50:
        return "high"
    if day.deviation_pct >= 20:
        return "medium"
    return "low"


def _median(values: list[float]) -> float | None:
    cleaned = sorted(v for v in values if v is not None)
    if not cleaned:
        return None
    middle = len(cleaned) // 2
    if len(cleaned) % 2:
        return cleaned[middle]
    return (cleaned[middle - 1] + cleaned[middle]) / 2


def model_card(site_id: str, appliance: str) -> dict:
    """Everything a reader needs to judge how much to trust this model."""
    pair = load_pair(site_id, appliance)
    analysis = analyse(site_id, appliance)
    if pair is None:
        return {
            "available": False,
            "site_id": site_id,
            "appliance": appliance,
            "reason": analysis.reliability_note,
        }
    return {
        "available": True,
        "site_id": site_id,
        "appliance": appliance,
        "appliance_label": analysis.appliance_label,
        "pipeline_version": pair.pipeline_version,
        "trained_at": pair.trained_at,
        "has_classifier": pair.has_classifier,
        "reliability": analysis.reliability,
        "reliability_note": analysis.reliability_note,
        "baseline": pair.baseline.as_dict(),
        "metrics": _public_metrics(pair.metrics),
        "feature_importance": pair.feature_importance(),
        "model_features": list(pair.model_features),
        "limitations": [
            "Labels are self-generated from a residual percentile, not externally "
            "verified ground truth.",
            "The model classifies whole days; it cannot localise a fault within a day "
            "or attribute it to one physical unit.",
            "Roughly a quarter of training days are inefficient by construction, so "
            "the positive rate reflects the definition, not the building.",
        ],
    }


def all_registry_pairs() -> list[dict]:
    return registry_pairs()
