"""Serving layer for the inefficiency pipeline.

One function does the work -- :func:`analyze_energy_usage` -- and everything in the
backend goes through it. It loads the persisted baseline and classifier, rebuilds the
daily features for a site/appliance, and returns a per-day analysis in units a person
can read.

Units, carefully
----------------
The notebook's ``total_energy`` is a sum of watt samples over on-state rows. Multiplying
by the sampling interval and dividing by 1000 converts it -- and the baseline's
expectation, which is in the same units -- into kWh. So:

* ``energy_kwh``          every row, including standby. This is what the bill reflects.
* ``active_energy_kwh``   on-state rows only. This is what the baseline predicts.
* ``expected_energy_kwh`` the baseline's expectation, same basis as ``active_energy_kwh``.

Comparing ``active`` against ``expected`` is apples to apples; comparing the bill
against the baseline would not be.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from functools import lru_cache

import numpy as np
import pandas as pd

from data.loaders import get_site_readings, interval_hours, site_capabilities
from data.schema import CHANNELS_BY_KEY, Provenance

from .baseline import annotate, deviation_pct
from .config import DECISION_THRESHOLD, MODEL_FEATURES
from .explanation import explain_day
from .feature_engineering import build_daily_features
from .model_loader import load_pair
from .reliability import Reliability, grade, trust_classifier

logger = logging.getLogger(__name__)


@dataclass
class DayAnalysis:
    """One appliance, one day."""

    site_id: str
    appliance: str
    appliance_label: str
    date: str

    energy_kwh: float
    active_energy_kwh: float
    expected_energy_kwh: float | None
    deviation_kwh: float | None
    deviation_pct: float | None

    runtime_hours: float | None
    peak_power_w: float
    mean_power_w: float
    cycles: int
    short_cycles: int
    duty_cycle: float

    temperature_mean: float
    humidity_mean: float
    heat_index: float

    status: str  # "normal" | "abnormal" | "idle" | "not_assessable"
    inefficient: bool | None
    probability: float | None
    reliability: str
    reliability_note: str
    star_adjusted: bool
    provenance: str

    drivers: list[dict] = field(default_factory=list)
    explanation: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApplianceAnalysis:
    """A full daily series for one appliance, plus what the model can say about it."""

    site_id: str
    appliance: str
    appliance_label: str
    days: list[DayAnalysis]
    has_baseline: bool
    has_classifier: bool
    reliability: str
    reliability_note: str
    metrics: dict
    feature_importance: dict
    notes: list[str] = field(default_factory=list)

    def latest(self) -> DayAnalysis | None:
        return self.days[-1] if self.days else None

    def by_date(self, date: str) -> DayAnalysis | None:
        for day in self.days:
            if day.date == date:
                return day
        return None


def _label_for(site_id: str, appliance: str) -> str:
    for capability in site_capabilities(site_id):
        if capability.key == appliance:
            return capability.label
    spec = CHANNELS_BY_KEY.get(appliance)
    return spec.label if spec else appliance


def _capability(site_id: str, appliance: str):
    for capability in site_capabilities(site_id):
        if capability.key == appliance:
            return capability
    return None


@lru_cache(maxsize=128)
def analyze_energy_usage(site_id: str, appliance: str) -> ApplianceAnalysis:
    """Analyse every day of one appliance at one site.

    Never raises for data reasons. When the classifier is missing the baseline still
    produces expected-vs-actual; when the on-state signal is missing the days are
    returned as ``not_assessable`` with the reason attached.
    """
    label = _label_for(site_id, appliance)
    capability = _capability(site_id, appliance)
    notes: list[str] = list(capability.notes) if capability else []

    readings = get_site_readings(site_id)
    daily = build_daily_features(readings, appliance)
    hours = interval_hours()

    energy_by_day = _billing_energy_by_day(readings, appliance, hours)

    if daily.empty:
        return ApplianceAnalysis(
            site_id=site_id,
            appliance=appliance,
            appliance_label=label,
            days=[],
            has_baseline=False,
            has_classifier=False,
            reliability=Reliability.UNAVAILABLE.value,
            reliability_note="No readings for this appliance at this site.",
            metrics={},
            feature_importance={},
            notes=notes,
        )

    pair = load_pair(site_id, appliance)
    has_state = bool(capability.has_state_signal) if capability else False

    if pair is None:
        reliability, reliability_note = Reliability.UNAVAILABLE, (
            "No trained model for this appliance at this site."
            if has_state
            else "On/off state is absent, so the appliance cannot be assessed against "
            "an expected-energy baseline."
        )
        days = [
            _unassessable_day(site_id, appliance, label, row, energy_by_day, reliability_note)
            for _, row in daily.iterrows()
        ]
        return ApplianceAnalysis(
            site_id=site_id,
            appliance=appliance,
            appliance_label=label,
            days=days,
            has_baseline=False,
            has_classifier=False,
            reliability=reliability.value,
            reliability_note=reliability_note,
            metrics={},
            feature_importance={},
            notes=notes,
        )

    labelled = annotate(daily, pair.baseline)
    reliability, reliability_note = grade(pair.metrics)
    importance = pair.feature_importance()

    probabilities: np.ndarray | None = None
    if pair.has_classifier:
        features = list(MODEL_FEATURES)
        probabilities = pair.classifier.predict_proba(labelled[features])[:, 1]

    days: list[DayAnalysis] = []
    for position, (_, row) in enumerate(labelled.iterrows()):
        probability = (
            float(probabilities[position]) if probabilities is not None else None
        )
        days.append(
            _build_day(
                site_id=site_id,
                appliance=appliance,
                label=label,
                row=row,
                energy_by_day=energy_by_day,
                hours=hours,
                probability=probability,
                reliability=reliability,
                reliability_note=reliability_note,
                star_adjusted=pair.baseline.star_adjusted,
                importance=importance,
            )
        )

    return ApplianceAnalysis(
        site_id=site_id,
        appliance=appliance,
        appliance_label=label,
        days=days,
        has_baseline=True,
        has_classifier=pair.has_classifier,
        reliability=reliability.value,
        reliability_note=reliability_note,
        metrics=pair.metrics,
        feature_importance=importance,
        notes=notes,
    )


def _billing_energy_by_day(
    readings: pd.DataFrame, appliance: str, hours: float
) -> dict[str, float]:
    """Total kWh per day including standby draw."""
    power_col = f"{appliance}_power"
    if power_col not in readings.columns:
        return {}
    frame = pd.DataFrame(
        {
            "date": readings["date_time"].dt.normalize(),
            "kwh": readings[power_col] * hours / 1000.0,
        }
    )
    totals = frame.groupby("date")["kwh"].sum()
    return {ts.strftime("%Y-%m-%d"): float(value) for ts, value in totals.items()}


def _unassessable_day(
    site_id: str,
    appliance: str,
    label: str,
    row: pd.Series,
    energy_by_day: dict[str, float],
    reason: str,
) -> DayAnalysis:
    date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
    return DayAnalysis(
        site_id=site_id,
        appliance=appliance,
        appliance_label=label,
        date=date,
        energy_kwh=round(energy_by_day.get(date, 0.0), 4),
        active_energy_kwh=0.0,
        expected_energy_kwh=None,
        deviation_kwh=None,
        deviation_pct=None,
        runtime_hours=None,
        peak_power_w=0.0,
        mean_power_w=0.0,
        cycles=0,
        short_cycles=0,
        duty_cycle=0.0,
        temperature_mean=round(float(row.get("temperature_mean", 0.0)), 2),
        humidity_mean=round(float(row.get("humidity_mean", 0.0)), 2),
        heat_index=round(float(row.get("heat_index", 0.0)), 2),
        status="not_assessable",
        inefficient=None,
        probability=None,
        reliability=Reliability.UNAVAILABLE.value,
        reliability_note=reason,
        star_adjusted=False,
        provenance=Provenance.MEASURED.value,
        explanation=reason,
        notes=[reason],
    )


def _build_day(
    *,
    site_id: str,
    appliance: str,
    label: str,
    row: pd.Series,
    energy_by_day: dict[str, float],
    hours: float,
    probability: float | None,
    reliability: Reliability,
    reliability_note: str,
    star_adjusted: bool,
    importance: dict[str, float],
) -> DayAnalysis:
    date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
    to_kwh = hours / 1000.0

    active_kwh = float(row["total_energy"]) * to_kwh
    expected_kwh = float(row["expected_energy"]) * to_kwh
    idle = float(row["on_duration"]) == 0

    # A negative expectation is meaningless; the linear baseline can produce one when
    # extrapolating far outside its training range.
    expected_kwh_out: float | None = None if idle or expected_kwh <= 0 else expected_kwh

    # Round *before* deriving the deviation, so the percentage the UI shows is exactly
    # reconstructible from the two kWh figures beside it. Deriving it from full
    # precision and rounding afterwards leaves the three numbers subtly inconsistent
    # whenever expected energy is small.
    active_kwh = round(active_kwh, 4)
    if expected_kwh_out is not None:
        expected_kwh_out = round(expected_kwh_out, 4)

    deviation = None if expected_kwh_out is None else active_kwh - expected_kwh_out
    dev_pct = (
        None
        if expected_kwh_out is None
        else deviation_pct(active_kwh, expected_kwh_out)
    )

    if idle:
        status = "idle"
        inefficient: bool | None = None
    elif expected_kwh_out is None:
        status = "not_assessable"
        inefficient = None
    else:
        # The classifier decides only when it has earned the right to. Otherwise the
        # baseline residual, which is well defined on short histories, decides.
        if probability is not None and trust_classifier(reliability):
            inefficient = probability >= DECISION_THRESHOLD
        else:
            inefficient = bool(row["efficiency_class"] == 1)
        status = "abnormal" if inefficient else "normal"

    mean_power = (
        float(row["total_energy"]) / float(row["on_duration"])
        if float(row["on_duration"]) > 0
        else 0.0
    )
    peak_power = mean_power * float(row["peak_average_ratio"])

    drivers = _drivers(row, importance)
    explanation = explain_day(
        appliance_label=label,
        status=status,
        active_kwh=active_kwh,
        expected_kwh=expected_kwh_out,
        deviation_pct=dev_pct,
        runtime_hours=float(row["on_duration"]) * hours,
        temperature=float(row["temperature_mean"]),
        humidity=float(row["humidity_mean"]),
        drivers=drivers,
        probability=probability,
        reliability=reliability,
        star_adjusted=star_adjusted,
    )

    return DayAnalysis(
        site_id=site_id,
        appliance=appliance,
        appliance_label=label,
        date=date,
        energy_kwh=round(energy_by_day.get(date, active_kwh), 4),
        active_energy_kwh=active_kwh,
        expected_energy_kwh=expected_kwh_out,
        deviation_kwh=None if deviation is None else round(deviation, 4),
        deviation_pct=None if dev_pct is None else round(dev_pct, 1),
        runtime_hours=round(float(row["on_duration"]) * hours, 2),
        peak_power_w=round(peak_power, 1),
        mean_power_w=round(mean_power, 1),
        cycles=int(row["cycles"]),
        short_cycles=int(row["short_cycles"]),
        duty_cycle=round(float(row["duty_cycle"]), 4),
        temperature_mean=round(float(row["temperature_mean"]), 2),
        humidity_mean=round(float(row["humidity_mean"]), 2),
        heat_index=round(float(row["heat_index"]), 2),
        status=status,
        inefficient=inefficient,
        probability=None if probability is None else round(probability, 4),
        reliability=reliability.value,
        reliability_note=reliability_note,
        star_adjusted=star_adjusted,
        provenance=Provenance.MEASURED.value,
        drivers=drivers,
        explanation=explanation,
    )


def _drivers(row: pd.Series, importance: dict[str, float], top_n: int = 3) -> list[dict]:
    """The features that most influenced this appliance's model, with the day's values.

    Importance is global to the model, not per-day (XGBoost gain does not decompose per
    sample without SHAP). The API labels it as such so it is not mistaken for a
    per-day attribution.
    """
    if not importance:
        return []
    ranked = sorted(importance.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [
        {
            "feature": name,
            "importance": round(float(value), 4),
            "value": round(float(row[name]), 4) if name in row.index else None,
        }
        for name, value in ranked
    ]


def clear_cache() -> None:
    analyze_energy_usage.cache_clear()
