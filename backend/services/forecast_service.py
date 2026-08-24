"""Daily energy forecasting.

The existing model is a *classifier* -- it cannot forecast energy, so this is new
work rather than a reuse. It is deliberately simple, because the histories here are
25 to 116 days long and a deep model would only overfit them.

Two candidates compete for every site:

* **Seasonal naive** -- predict the mean of the same weekday in recent history.
* **Ridge regression** on lag-1, lag-2, lag-7, rolling 3- and 7-day means, weekday,
  and the trailing weather.

Both are scored by walk-forward validation over the tail of the history, and the one
with the lower mean absolute error wins. The reported uncertainty band is that measured
error, not a guess. If neither beats a trivial constant, the service says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from backend.services import carbon_service, tariff_service
from data.schema import Provenance
from data.transformers import complete_days_only, resample_energy, site_interval_energy

logger = logging.getLogger(__name__)

#: Below this many days there is nothing to learn from.
MIN_DAYS = 14

#: Days held out for walk-forward validation.
MIN_BACKTEST_DAYS = 5
BACKTEST_FRACTION = 0.25

LAGS = (1, 2, 7)


@dataclass
class ForecastModel:
    name: str
    mae: float
    mape: float | None
    backtest_days: int
    beats_constant: bool


def _daily_frame(site_id: str) -> pd.DataFrame:
    frame = site_interval_energy(site_id)
    if frame.empty:
        return pd.DataFrame()
    daily = resample_energy(frame, "daily")
    if daily.empty:
        return pd.DataFrame()
    # Partial days -- truncated first/last days and mid-series gaps -- would drag the
    # model toward zero, so only complete days train and score it.
    daily = complete_days_only(daily)
    if daily.empty:
        return pd.DataFrame()
    daily = daily.rename(columns={"date_time": "date"})
    return daily[["date", "total_energy_kwh", "Temperature", "Humidity"]].reset_index(drop=True)


def _build_supervised(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily.copy()
    frame["dow"] = frame["date"].dt.dayofweek
    for lag in LAGS:
        frame[f"lag{lag}"] = frame["total_energy_kwh"].shift(lag)
    frame["roll3"] = frame["total_energy_kwh"].shift(1).rolling(3).mean()
    frame["roll7"] = frame["total_energy_kwh"].shift(1).rolling(7).mean()
    frame["temp_lag1"] = frame["Temperature"].shift(1)
    frame["humidity_lag1"] = frame["Humidity"].shift(1)
    frame["is_weekend"] = (frame["dow"] >= 5).astype(int)
    return frame.dropna().reset_index(drop=True)


FEATURE_COLUMNS = [
    "lag1",
    "lag2",
    "lag7",
    "roll3",
    "roll7",
    "temp_lag1",
    "humidity_lag1",
    "dow",
    "is_weekend",
]


def _seasonal_naive_predict(history: pd.DataFrame, target_dow: int) -> float:
    """Mean of the same weekday; falls back to the trailing 7-day mean."""
    same_day = history[history["date"].dt.dayofweek == target_dow]["total_energy_kwh"]
    if len(same_day) >= 2:
        return float(same_day.tail(4).mean())
    return float(history["total_energy_kwh"].tail(7).mean())


def _fit_ridge(train: pd.DataFrame) -> tuple[Ridge, StandardScaler]:
    scaler = StandardScaler()
    features = scaler.fit_transform(train[FEATURE_COLUMNS])
    model = Ridge(alpha=1.0)
    model.fit(features, train["total_energy_kwh"])
    return model, scaler


def _backtest(daily: pd.DataFrame) -> tuple[ForecastModel, ForecastModel, float]:
    """Walk-forward comparison of ridge vs seasonal naive vs a constant."""
    supervised = _build_supervised(daily)
    horizon = max(MIN_BACKTEST_DAYS, int(len(supervised) * BACKTEST_FRACTION))
    horizon = min(horizon, len(supervised) - MIN_BACKTEST_DAYS)
    horizon = max(horizon, 1)
    split = len(supervised) - horizon

    ridge_errors: list[float] = []
    naive_errors: list[float] = []
    constant_errors: list[float] = []
    actuals: list[float] = []

    for position in range(split, len(supervised)):
        train = supervised.iloc[:position]
        row = supervised.iloc[position]
        actual = float(row["total_energy_kwh"])
        actuals.append(actual)

        history = daily[daily["date"] < row["date"]]
        naive_errors.append(abs(_seasonal_naive_predict(history, int(row["dow"])) - actual))
        constant_errors.append(abs(float(train["total_energy_kwh"].mean()) - actual))

        if len(train) >= 8:
            try:
                model, scaler = _fit_ridge(train)
                prediction = float(
                    model.predict(scaler.transform(row[FEATURE_COLUMNS].to_frame().T))[0]
                )
                ridge_errors.append(abs(max(prediction, 0.0) - actual))
            except Exception:  # pragma: no cover - degenerate training window
                ridge_errors.append(naive_errors[-1])
        else:
            ridge_errors.append(naive_errors[-1])

    constant_mae = float(np.mean(constant_errors))
    mean_actual = float(np.mean(actuals)) if actuals else 0.0

    def build(name: str, errors: list[float]) -> ForecastModel:
        mae = float(np.mean(errors))
        return ForecastModel(
            name=name,
            mae=mae,
            mape=(mae / mean_actual * 100) if mean_actual > 0 else None,
            backtest_days=len(errors),
            beats_constant=mae < constant_mae,
        )

    return build("ridge", ridge_errors), build("seasonal_naive", naive_errors), constant_mae


@lru_cache(maxsize=32)
def _prepare(site_id: str) -> dict | None:
    daily = _daily_frame(site_id)
    if daily.empty or len(daily) < MIN_DAYS:
        return None
    supervised = _build_supervised(daily)
    if len(supervised) < MIN_DAYS:
        return None

    ridge_score, naive_score, constant_mae = _backtest(daily)
    chosen = ridge_score if ridge_score.mae <= naive_score.mae else naive_score

    model = scaler = None
    if chosen.name == "ridge":
        model, scaler = _fit_ridge(supervised)

    return {
        "daily": daily,
        "supervised": supervised,
        "chosen": chosen,
        "alternatives": [ridge_score, naive_score],
        "constant_mae": constant_mae,
        "model": model,
        "scaler": scaler,
    }


def forecast(site_id: str, horizon_days: int = 7) -> dict:
    """Forecast the next ``horizon_days`` after the last observed day."""
    prepared = _prepare(site_id)
    if prepared is None:
        return {
            "site_id": site_id,
            "available": False,
            "reason": (
                f"Forecasting needs at least {MIN_DAYS} days of history; this site has "
                "fewer usable days."
            ),
            "provenance": Provenance.UNAVAILABLE.value,
            "points": [],
        }

    daily: pd.DataFrame = prepared["daily"].copy()
    chosen: ForecastModel = prepared["chosen"]
    horizon_days = max(1, min(horizon_days, 14))

    working = daily.copy()
    points = []
    # Trailing weather is carried forward: the dataset ends in the past, so no live
    # forecast applies to these dates. This assumption is stated in the payload.
    temp_assumption = float(working["Temperature"].tail(7).mean())
    humidity_assumption = float(working["Humidity"].tail(7).mean())

    for step in range(1, horizon_days + 1):
        next_date = working["date"].iloc[-1] + pd.Timedelta(days=1)
        prediction = _predict_next(prepared, working, next_date, temp_assumption, humidity_assumption)
        prediction = max(prediction, 0.0)

        # Uncertainty widens with horizon: one MAE at day 1, growing as sqrt(step).
        band = chosen.mae * float(np.sqrt(step))
        hour_costs = tariff_service.cost_of_kwh(prediction)
        points.append(
            {
                "date": next_date.strftime("%Y-%m-%d"),
                "day_label": next_date.strftime("%a %d %b"),
                "energy_kwh": round(prediction, 3),
                "lower_kwh": round(max(prediction - band, 0.0), 3),
                "upper_kwh": round(prediction + band, 3),
                "cost": round(hour_costs, 2),
                "carbon_kg": round(carbon_service.carbon_for(site_id, prediction), 3),
                "horizon_day": step,
            }
        )

        working = pd.concat(
            [
                working,
                pd.DataFrame(
                    [
                        {
                            "date": next_date,
                            "total_energy_kwh": prediction,
                            "Temperature": temp_assumption,
                            "Humidity": humidity_assumption,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    recent_mean = float(daily["total_energy_kwh"].tail(7).mean())
    tomorrow = points[0]
    change_pct = (
        round((tomorrow["energy_kwh"] - recent_mean) / recent_mean * 100, 1)
        if recent_mean > 0
        else None
    )

    return {
        "site_id": site_id,
        "available": True,
        "model": chosen.name,
        "model_label": (
            "Ridge regression on lagged consumption and weather"
            if chosen.name == "ridge"
            else "Seasonal naive (same weekday average)"
        ),
        "accuracy": {
            "mae_kwh": round(chosen.mae, 3),
            "mape_pct": round(chosen.mape, 1) if chosen.mape is not None else None,
            "backtest_days": chosen.backtest_days,
            "beats_constant_baseline": chosen.beats_constant,
            "constant_baseline_mae_kwh": round(prepared["constant_mae"], 3),
            "candidates": [
                {"name": alt.name, "mae_kwh": round(alt.mae, 3)}
                for alt in prepared["alternatives"]
            ],
        },
        "history_days": int(len(daily)),
        "last_observed_date": daily["date"].iloc[-1].strftime("%Y-%m-%d"),
        "recent_7day_mean_kwh": round(recent_mean, 3),
        "tomorrow": {**tomorrow, "change_vs_recent_pct": change_pct},
        "points": points,
        "recent_history": [
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "day_label": row["date"].strftime("%a %d %b"),
                "energy_kwh": round(float(row["total_energy_kwh"]), 3),
            }
            for _, row in daily.tail(14).iterrows()
        ],
        "provenance": Provenance.PREDICTED.value,
        "assumptions": [
            (
                f"Weather for the forecast window is assumed to match the trailing "
                f"7-day average ({temp_assumption:.1f} C, {humidity_assumption:.0f}% RH), "
                "because the dataset ends in the past and no live forecast covers "
                "these dates."
            ),
            (
                "Cost uses the configured average tariff, since the hour-by-hour shape "
                "of a future day is not forecast."
            ),
            (
                f"The band is the model's measured mean absolute error "
                f"({chosen.mae:.2f} kWh), widened with the square root of the horizon."
            ),
        ],
        "warning": (
            None
            if chosen.beats_constant
            else (
                "This model does not beat a simple long-run average on back-testing. "
                "Treat the forecast as indicative only."
            )
        ),
    }


def _predict_next(
    prepared: dict,
    working: pd.DataFrame,
    next_date: pd.Timestamp,
    temperature: float,
    humidity: float,
) -> float:
    chosen: ForecastModel = prepared["chosen"]
    if chosen.name == "seasonal_naive" or prepared["model"] is None:
        return _seasonal_naive_predict(working, int(next_date.dayofweek))

    series = working["total_energy_kwh"]
    row = {
        "lag1": float(series.iloc[-1]),
        "lag2": float(series.iloc[-2]) if len(series) >= 2 else float(series.iloc[-1]),
        "lag7": float(series.iloc[-7]) if len(series) >= 7 else float(series.mean()),
        "roll3": float(series.tail(3).mean()),
        "roll7": float(series.tail(7).mean()),
        "temp_lag1": temperature,
        "humidity_lag1": humidity,
        "dow": int(next_date.dayofweek),
        "is_weekend": int(next_date.dayofweek >= 5),
    }
    features = pd.DataFrame([row])[FEATURE_COLUMNS]
    scaled = prepared["scaler"].transform(features)
    return float(prepared["model"].predict(scaled)[0])


def clear_cache() -> None:
    _prepare.cache_clear()
