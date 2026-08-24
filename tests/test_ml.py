"""The ported inefficiency pipeline: features, baseline, artefacts and serving."""

from __future__ import annotations

import pandas as pd
import pytest

from data.loaders import get_site_readings
from ml import model_loader
from ml.baseline import deviation_pct, fit_baseline
from ml.config import BASELINE_FEATURES, MODEL_FEATURES, XGB_PARAMS
from ml.feature_engineering import FEATURE_NAMES, build_daily_features, extract_daily_features
from ml.prediction import analyze_energy_usage
from ml.reliability import Reliability, grade
from tests.conftest import NO_STATE_SITE, PRIMARY_APPLIANCE, PRIMARY_SITE


# --- feature engineering ---------------------------------------------------


def test_feature_extraction_produces_every_documented_feature():
    readings = get_site_readings(PRIMARY_SITE)
    daily = build_daily_features(readings, PRIMARY_APPLIANCE)
    assert not daily.empty
    for name in FEATURE_NAMES:
        assert name in daily.columns


def test_idle_day_produces_all_zero_features():
    """The notebook returns a zero vector when the appliance never ran. So must this."""
    group = pd.DataFrame(
        {
            "ac_state": [0, 0, 0],
            "ac_power": [1.0, 2.0, 3.0],
            "Temperature": [30.0, 31.0, 32.0],
            "Humidity": [50.0, 51.0, 52.0],
        }
    )
    features = extract_daily_features(group, "ac")
    assert all(value == 0 for value in features.values())


def test_heat_index_formula_matches_the_notebook():
    group = pd.DataFrame(
        {
            "ac_state": [1, 1],
            "ac_power": [100.0, 200.0],
            "Temperature": [30.0, 30.0],
            "Humidity": [60.0, 60.0],
        }
    )
    features = extract_daily_features(group, "ac")
    assert features["heat_index"] == pytest.approx(30.0 + 0.1 * 60.0)


def test_total_energy_sums_on_state_power_only():
    group = pd.DataFrame(
        {
            "ac_state": [1, 0, 1],
            "ac_power": [100.0, 999.0, 200.0],
            "Temperature": [30.0] * 3,
            "Humidity": [50.0] * 3,
        }
    )
    features = extract_daily_features(group, "ac")
    assert features["total_energy"] == pytest.approx(300.0)
    assert features["on_duration"] == 2


def test_short_and_long_cycle_counting():
    state = [1] * 5 + [0] * 3 + [1] * 35
    group = pd.DataFrame(
        {
            "ac_state": state,
            "ac_power": [100.0] * len(state),
            "Temperature": [30.0] * len(state),
            "Humidity": [50.0] * len(state),
        }
    )
    features = extract_daily_features(group, "ac")
    assert features["short_cycles"] == 1
    assert features["cycles"] == 1
    assert features["long_run_ratio"] > 0


# --- baseline --------------------------------------------------------------


def test_baseline_fits_on_active_training_days_only():
    readings = get_site_readings(PRIMARY_SITE)
    daily = build_daily_features(readings, PRIMARY_APPLIANCE)
    train_mask = pd.Series([True] * len(daily))
    baseline = fit_baseline(daily, train_mask, star_rating=4.0, max_star_rating=5.0)
    assert baseline is not None
    assert list(baseline.features) == list(BASELINE_FEATURES)
    assert baseline.n_train_days == int((daily["on_duration"] > 0).sum())


def test_star_adjustment_holds_better_appliances_to_a_tighter_threshold():
    readings = get_site_readings(PRIMARY_SITE)
    daily = build_daily_features(readings, PRIMARY_APPLIANCE)
    train_mask = pd.Series([True] * len(daily))

    five_star = fit_baseline(daily, train_mask, 5.0, 5.0)
    three_star = fit_baseline(daily, train_mask, 3.0, 5.0)
    assert five_star is not None and three_star is not None
    assert five_star.adjusted_threshold < three_star.adjusted_threshold


def test_baseline_without_metadata_uses_the_unadjusted_threshold():
    readings = get_site_readings(PRIMARY_SITE)
    daily = build_daily_features(readings, PRIMARY_APPLIANCE)
    train_mask = pd.Series([True] * len(daily))
    baseline = fit_baseline(daily, train_mask, None, None)
    assert baseline is not None
    assert baseline.star_adjusted is False
    assert baseline.adjusted_threshold == baseline.base_threshold


def test_baseline_returns_none_on_too_little_data():
    daily = pd.DataFrame(
        {
            "on_duration": [0, 0, 1],
            "duty_cycle": [0.0, 0.0, 0.1],
            "cycles": [0, 0, 1],
            "heat_index": [30.0, 30.0, 30.0],
            "total_energy": [0.0, 0.0, 5.0],
        }
    )
    assert fit_baseline(daily, pd.Series([True] * 3), None, None) is None


def test_deviation_pct_guards_against_near_zero_expectation():
    assert deviation_pct(5.0, 0.0) is None
    assert deviation_pct(5.0, float("nan")) is None
    assert deviation_pct(6.0, 4.0) == pytest.approx(50.0)


# --- artefacts and serving -------------------------------------------------


def test_artefacts_exist_for_the_primary_pair():
    pair = model_loader.load_pair(PRIMARY_SITE, PRIMARY_APPLIANCE)
    assert pair is not None, "run 'python -m ml.train' first"
    assert pair.has_classifier
    assert list(pair.model_features) == list(MODEL_FEATURES)


def test_hyperparameters_match_the_notebook():
    pair = model_loader.load_pair(PRIMARY_SITE, PRIMARY_APPLIANCE)
    params = pair.classifier.get_params()
    for key in ("n_estimators", "max_depth", "learning_rate", "random_state"):
        assert params[key] == XGB_PARAMS[key]


def test_missing_artefact_returns_none_rather_than_raising():
    assert model_loader.load_pair("does_not_exist", "ac") is None


def test_analysis_never_raises_for_a_site_without_state_signal():
    analysis = analyze_energy_usage(NO_STATE_SITE, "ac")
    assert analysis.has_baseline is False
    assert analysis.reliability == Reliability.UNAVAILABLE.value
    assert analysis.reliability_note
    assert all(day.status == "not_assessable" for day in analysis.days)


def test_analysis_produces_expected_vs_actual_for_the_primary_pair():
    analysis = analyze_energy_usage(PRIMARY_SITE, PRIMARY_APPLIANCE)
    assessed = [d for d in analysis.days if d.status in ("normal", "abnormal")]
    assert assessed, "some days must be assessable"
    for day in assessed:
        assert day.expected_energy_kwh is not None and day.expected_energy_kwh > 0
        assert day.deviation_pct is not None
        assert day.explanation


def test_idle_days_are_never_flagged_as_abnormal():
    analysis = analyze_energy_usage(PRIMARY_SITE, PRIMARY_APPLIANCE)
    for day in analysis.days:
        if day.runtime_hours == 0:
            assert day.status == "idle"
            assert day.inefficient is None


def test_actual_and_expected_are_on_the_same_basis():
    """Deviation must be reconstructible from the two kWh figures the API returns."""
    analysis = analyze_energy_usage(PRIMARY_SITE, PRIMARY_APPLIANCE)
    checked = 0
    for day in analysis.days:
        if day.expected_energy_kwh is None or day.deviation_pct is None:
            continue
        recomputed = (
            (day.active_energy_kwh - day.expected_energy_kwh) / day.expected_energy_kwh * 100
        )
        assert day.deviation_pct == pytest.approx(recomputed, abs=0.15)
        checked += 1
    assert checked > 10


def test_unreliable_classifier_does_not_drive_the_verdict():
    """House_1's geyser classifier has too few positives to be trusted."""
    analysis = analyze_energy_usage("House_1", "geyser")
    assert analysis.reliability != Reliability.GOOD.value
    for day in analysis.days:
        if day.status in ("normal", "abnormal"):
            assert day.inefficient is not None
            assert "not reliable" in day.explanation or day.probability is None


def test_reliability_grading_rules():
    assert grade(None)[0] is Reliability.UNAVAILABLE
    assert (
        grade({"test_accuracy": 0.9, "test_positives": 1, "test_days": 10})[0]
        is Reliability.INSUFFICIENT
    )
    assert (
        grade({"test_accuracy": 0.9, "test_positives": 5, "test_days": 20, "roc_auc": 0.5})[0]
        is Reliability.LIMITED
    )
    assert (
        grade(
            {
                "test_accuracy": 0.9,
                "test_positives": 5,
                "test_days": 20,
                "roc_auc": 0.86,
                "pr_auc": 0.9,
            }
        )[0]
        is Reliability.GOOD
    )
