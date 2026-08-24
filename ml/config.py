"""Frozen configuration of the ported inefficiency pipeline.

These values are transcribed from
``notebooks/energy_inefficiency_model_with_weather_integration_code.ipynb``.
Changing anything here changes the model, so they live in one place and are
recorded into every artefact for traceability.
"""

from __future__ import annotations

PIPELINE_VERSION = "1.0.0"

#: Regressors for the expected-energy baseline. ``heat_index`` is what makes the
#: baseline weather-aware: expected energy rises with heat, so a hot-day increase is
#: explained rather than flagged.
BASELINE_FEATURES: tuple[str, ...] = (
    "on_duration",
    "duty_cycle",
    "cycles",
    "heat_index",
)

#: Classifier inputs. Purely behavioural -- energy, average power and any usage flag
#: are excluded so the model cannot read the label off its own input.
MODEL_FEATURES: tuple[str, ...] = (
    "duty_cycle",
    "std_power",
    "power_range",
    "cv_power",
    "short_cycles",
    "temp_runtime",
    "heat_index",
    "peak_average_ratio",
    "power_gradient",
)

XGB_PARAMS: dict = {
    "n_estimators": 300,
    "learning_rate": 0.1,
    "max_depth": 4,
    "min_child_weight": 4,
    "subsample": 1.0,
    "colsample_bytree": 1.0,
    "gamma": 1,
    "reg_alpha": 0.5,
    "reg_lambda": 2,
    "scale_pos_weight": 2.8,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "random_state": 42,
}

#: Residual percentile above which a day is a candidate for "inefficient".
RESIDUAL_PERCENTILE: float = 75.0

#: Chronological train fraction over active days.
TRAIN_RATIO: float = 0.7

#: Guards copied from the notebook's ``run_temporal_split``.
MIN_TRAIN_ACTIVE_DAYS: int = 5
MIN_TEST_ACTIVE_DAYS: int = 3

#: A run shorter than this many intervals counts as a short cycle.
SHORT_CYCLE_INTERVALS: int = 10

#: A run longer than this many intervals counts toward ``long_run_ratio``.
LONG_RUN_INTERVALS: int = 30

#: Probability at or above which a day is reported as inefficient.
DECISION_THRESHOLD: float = 0.5

#: Plain-language names for the model features, used in explanations.
FEATURE_LABELS: dict[str, str] = {
    "duty_cycle": "share of the day the appliance was running",
    "std_power": "variability of power draw",
    "power_range": "spread between peak and minimum power",
    "cv_power": "relative power variability",
    "short_cycles": "number of short on/off cycles",
    "temp_runtime": "runtime weighted by outdoor temperature",
    "heat_index": "combined heat and humidity load",
    "peak_average_ratio": "peak power relative to average power",
    "power_gradient": "abruptness of power changes",
    "on_duration": "total runtime",
    "cycles": "number of start-ups",
}
