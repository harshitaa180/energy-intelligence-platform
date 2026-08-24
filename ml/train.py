"""Train and persist the inefficiency pipeline.

Run once (or after the dataset changes)::

    python -m ml.train

This reproduces the notebook end to end -- same features, same baseline, same
star-adjusted threshold, same XGBoost hyperparameters, same chronological 70/30 split
-- and writes the fitted objects to ``ml/artifacts/`` so the API never retrains.

Coverage is wider than the notebook's hard-coded ``appliance_map``: every
(site, appliance) pair with a usable on-state signal is attempted. Pairs without
appliance metadata are trained with the *unadjusted* residual threshold and recorded
with ``star_adjusted: false``, so the difference is visible rather than papered over.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from data.loaders import get_site_readings, get_star_ratings, list_sites, site_capabilities
from data.schema import CHANNELS_BY_KEY

from . import model_loader
from .baseline import annotate, fit_baseline
from .config import (
    MIN_TEST_ACTIVE_DAYS,
    MIN_TRAIN_ACTIVE_DAYS,
    MODEL_FEATURES,
    PIPELINE_VERSION,
    TRAIN_RATIO,
    XGB_PARAMS,
)
from .feature_engineering import build_daily_features

logger = logging.getLogger(__name__)


def _star_context(site_id: str, appliance: str) -> tuple[float | None, float | None]:
    """House star rating and the corpus maximum, or ``(None, None)`` without metadata."""
    spec = CHANNELS_BY_KEY.get(appliance)
    if spec is None or spec.metadata_type is None:
        return None, None
    ratings = get_star_ratings(spec.metadata_type)
    if ratings.empty:
        return None, None
    row = ratings[ratings["house_id"] == site_id]
    if row.empty:
        return None, None
    return float(row.iloc[0]["star_rating"]), float(ratings["star_rating"].max())


def _candidate_pairs() -> list[tuple[str, str]]:
    """Every (site, appliance) with an on-state signal the pipeline can work with."""
    pairs: list[tuple[str, str]] = []
    for site_id in list_sites():
        for capability in site_capabilities(site_id):
            spec = CHANNELS_BY_KEY.get(capability.key)
            if spec is None or not spec.ml_appliance:
                continue
            if not capability.has_state_signal:
                continue
            pairs.append((site_id, capability.key))
    return pairs


def train_pair(site_id: str, appliance: str) -> dict:
    """Train one pair. Always returns a status dict; never raises for data reasons."""
    result: dict = {
        "site_id": site_id,
        "appliance": appliance,
        "has_baseline": False,
        "has_classifier": False,
        "status": "unknown",
    }

    readings = get_site_readings(site_id)
    daily = build_daily_features(readings, appliance)
    if daily.empty:
        result["status"] = "no_daily_features"
        return result

    active = daily[daily["on_duration"] > 0]
    result["total_days"] = int(len(daily))
    result["active_days"] = int(len(active))

    if active.empty:
        result["status"] = "no_active_days"
        return result

    split_index = int(len(active) * TRAIN_RATIO)
    train_dates = set(active.iloc[:split_index]["date"])
    test_dates = set(active.iloc[split_index:]["date"])
    train_mask = daily["date"].isin(train_dates)
    test_mask = daily["date"].isin(test_dates)

    star_rating, max_star = _star_context(site_id, appliance)
    baseline = fit_baseline(daily, train_mask, star_rating, max_star)
    if baseline is None:
        result["status"] = "insufficient_days_for_baseline"
        return result

    labelled = annotate(daily, baseline)
    result["has_baseline"] = True
    result["baseline"] = baseline.as_dict()
    result["star_adjusted"] = baseline.star_adjusted
    result["positive_rate"] = float(labelled["efficiency_class"].mean())

    metrics: dict = {"baseline_r2": baseline.r2}
    classifier = None

    train_data = labelled[train_mask]
    test_data = labelled[test_mask]
    y_train = train_data["efficiency_class"]
    y_test = test_data["efficiency_class"]

    if len(train_data) < MIN_TRAIN_ACTIVE_DAYS or len(test_data) < MIN_TEST_ACTIVE_DAYS:
        result["status"] = "baseline_only_insufficient_split"
        metrics["classifier_skip_reason"] = (
            f"needs >={MIN_TRAIN_ACTIVE_DAYS} train and >={MIN_TEST_ACTIVE_DAYS} test "
            f"active days, has {len(train_data)}/{len(test_data)}"
        )
    elif y_train.nunique() < 2:
        result["status"] = "baseline_only_single_class_in_train"
        metrics["classifier_skip_reason"] = "training window contains a single class"
    else:
        features = list(MODEL_FEATURES)
        classifier = XGBClassifier(**XGB_PARAMS)
        classifier.fit(train_data[features], y_train)

        y_train_pred = classifier.predict(train_data[features])
        y_pred = classifier.predict(test_data[features])
        y_prob = classifier.predict_proba(test_data[features])[:, 1]

        metrics.update(
            {
                "train_accuracy": float(accuracy_score(y_train, y_train_pred)),
                "train_f1": float(f1_score(y_train, y_train_pred, zero_division=0)),
                "test_accuracy": float(accuracy_score(y_test, y_pred)),
                "test_f1": float(f1_score(y_test, y_pred, zero_division=0)),
                "test_precision": float(precision_score(y_test, y_pred, zero_division=0)),
                "test_recall": float(recall_score(y_test, y_pred, zero_division=0)),
                "train_days": int(len(train_data)),
                "test_days": int(len(test_data)),
                "test_positives": int(y_test.sum()),
                "train_positive_rate": float(y_train.mean()),
                "test_positive_rate": float(y_test.mean()),
            }
        )
        metrics["roc_auc"] = _safe_metric(roc_auc_score, y_test, y_prob)
        metrics["pr_auc"] = _safe_metric(average_precision_score, y_test, y_prob)
        metrics["feature_importance"] = {
            name: float(value)
            for name, value in zip(features, classifier.feature_importances_)
        }
        if int(y_test.sum()) < 3:
            metrics["reliability_warning"] = (
                "Fewer than 3 positive days in the test window: F1 and ROC-AUC are "
                "not reliable here. Treat PR-AUC as indicative only."
            )
        result["has_classifier"] = True
        result["status"] = "trained"

    if not result["has_classifier"] and result["status"] == "unknown":
        result["status"] = "baseline_only"

    trained_at = datetime.now(timezone.utc).isoformat()
    model_loader.save_pair(
        site_id=site_id,
        appliance=appliance,
        baseline=baseline,
        classifier=classifier,
        model_features=MODEL_FEATURES,
        metrics=metrics,
        trained_at=trained_at,
        pipeline_version=PIPELINE_VERSION,
    )
    result["metrics"] = metrics
    result["trained_at"] = trained_at
    return result


def _safe_metric(fn, y_true, y_score) -> float | None:
    """Metrics that need both classes present return ``None`` instead of raising."""
    try:
        return float(fn(y_true, y_score))
    except ValueError:
        return None


def train_all(verbose: bool = True) -> dict:
    """Train every candidate pair and write the registry."""
    entries = []
    for site_id, appliance in _candidate_pairs():
        outcome = train_pair(site_id, appliance)
        entries.append(outcome)
        if verbose:
            metrics = outcome.get("metrics", {})
            summary = outcome["status"]
            if outcome["has_classifier"]:
                summary = (
                    f"trained  acc={metrics.get('test_accuracy'):.3f} "
                    f"f1={metrics.get('test_f1'):.3f} "
                    f"pr_auc={_fmt(metrics.get('pr_auc'))} "
                    f"roc_auc={_fmt(metrics.get('roc_auc'))}"
                )
            print(
                f"  {site_id:18s} {appliance:8s} "
                f"days={outcome.get('active_days', 0):4d}  {summary}"
            )

    registry = {
        "pipeline_version": PIPELINE_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "pairs": entries,
    }
    model_loader.save_registry(registry)
    return registry


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the inefficiency pipeline.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("Training inefficiency pipeline (ported from the notebook)\n")
    registry = train_all(verbose=not args.quiet)

    trained = sum(1 for entry in registry["pairs"] if entry["has_classifier"])
    baseline_only = sum(
        1 for entry in registry["pairs"] if entry["has_baseline"] and not entry["has_classifier"]
    )
    print(
        f"\n{trained} pair(s) with a classifier, {baseline_only} with an "
        f"expected-energy baseline only, out of {len(registry['pairs'])} attempted."
    )
    print(f"Artefacts written to {model_loader.REGISTRY_PATH.parent}")


if __name__ == "__main__":
    main()
