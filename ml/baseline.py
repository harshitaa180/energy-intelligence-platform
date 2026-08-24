"""Expected-energy baseline and star-adjusted labelling.

This is the piece that answers "is this consumption actually justified?". A linear
model predicts how much energy the appliance *should* have used given how long it ran,
how hard it worked, and how hot and humid the day was. The gap between actual and
expected is the residual; a day is labelled inefficient when its residual exceeds a
threshold derived from the training distribution and tightened for better-rated
appliances.

Ported from the notebook's ``assign_residual_labels``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from .config import BASELINE_FEATURES, RESIDUAL_PERCENTILE


@dataclass
class BaselineModel:
    """A fitted expected-energy baseline plus its labelling threshold."""

    regressor: LinearRegression
    features: tuple[str, ...]
    base_threshold: float
    r2: float
    star_rating: float | None
    max_star_rating: float | None
    n_train_days: int
    star_adjusted: bool = field(init=False)

    def __post_init__(self) -> None:
        self.star_adjusted = self.star_rating is not None and self.max_star_rating is not None

    @property
    def adjusted_threshold(self) -> float:
        """Threshold after the star-rating adjustment.

        ``threshold * (2 - stars / max_stars)``: a 5-star appliance is held to a
        tighter standard than a 3-star one. Without metadata the base threshold is
        used unchanged and :attr:`star_adjusted` is ``False``.
        """
        if not self.star_adjusted:
            return self.base_threshold
        assert self.star_rating is not None and self.max_star_rating is not None
        if self.max_star_rating <= 0:
            return self.base_threshold
        return self.base_threshold * (2 - self.star_rating / self.max_star_rating)

    def expected_energy(self, daily: pd.DataFrame) -> np.ndarray:
        return self.regressor.predict(daily[list(self.features)])

    def residuals(self, daily: pd.DataFrame) -> np.ndarray:
        return daily["total_energy"].to_numpy() - self.expected_energy(daily)

    def labels(self, daily: pd.DataFrame) -> np.ndarray:
        return (self.residuals(daily) > self.adjusted_threshold).astype(int)

    def as_dict(self) -> dict:
        return {
            "features": list(self.features),
            "base_threshold": self.base_threshold,
            "adjusted_threshold": self.adjusted_threshold,
            "r2": self.r2,
            "star_rating": self.star_rating,
            "max_star_rating": self.max_star_rating,
            "star_adjusted": self.star_adjusted,
            "n_train_days": self.n_train_days,
            "coefficients": dict(
                zip(self.features, [float(c) for c in self.regressor.coef_])
            ),
            "intercept": float(self.regressor.intercept_),
        }


def fit_baseline(
    daily: pd.DataFrame,
    train_mask: pd.Series,
    star_rating: float | None,
    max_star_rating: float | None,
) -> BaselineModel | None:
    """Fit the expected-energy baseline on training *active* days only.

    Restricting to active days is what removes the trivial "it ran, therefore it used
    energy" correlation. Returns ``None`` when there is too little signal to fit.
    """
    active_mask = daily["on_duration"] > 0
    train_active = daily[train_mask & active_mask]

    if len(train_active) < 5:
        return None

    regressor = LinearRegression()
    features = list(BASELINE_FEATURES)
    regressor.fit(train_active[features], train_active["total_energy"])
    r2 = float(regressor.score(train_active[features], train_active["total_energy"]))

    all_expected = regressor.predict(daily[features])
    all_residuals = daily["total_energy"].to_numpy() - all_expected
    train_residuals = all_residuals[(train_mask & active_mask).to_numpy()]
    base_threshold = float(np.percentile(train_residuals, RESIDUAL_PERCENTILE))

    return BaselineModel(
        regressor=regressor,
        features=BASELINE_FEATURES,
        base_threshold=base_threshold,
        r2=r2,
        star_rating=star_rating,
        max_star_rating=max_star_rating,
        n_train_days=int(len(train_active)),
    )


def annotate(daily: pd.DataFrame, baseline: BaselineModel) -> pd.DataFrame:
    """Attach expected energy, residual, deviation % and label to a daily frame."""
    out = daily.copy()
    out["expected_energy"] = baseline.expected_energy(out)
    out["energy_residual"] = out["total_energy"] - out["expected_energy"]
    out["deviation_pct"] = _safe_deviation_pct(
        out["total_energy"].to_numpy(), out["expected_energy"].to_numpy()
    )
    out["efficiency_class"] = (out["energy_residual"] > baseline.adjusted_threshold).astype(int)
    return out


def _safe_deviation_pct(actual: np.ndarray, expected: np.ndarray) -> np.ndarray:
    """``(actual - expected) / expected * 100`` with a guard for tiny expectations.

    When expected energy is at or below the guard, a percentage is meaningless and
    ``NaN`` is returned so the UI can show "not comparable" rather than a number like
    +40000%.
    """
    guard = 1e-6
    expected = np.asarray(expected, dtype=float)
    actual = np.asarray(actual, dtype=float)
    out = np.full(actual.shape, np.nan, dtype=float)
    usable = np.abs(expected) > max(guard, 0.01 * np.nanmax(np.abs(expected), initial=guard))
    np.divide(
        actual - expected,
        expected,
        out=out,
        where=usable,
    )
    return out * 100.0


def deviation_pct(actual: float, expected: float) -> float | None:
    """Scalar form of :func:`_safe_deviation_pct`. ``None`` when not comparable."""
    if expected is None or not np.isfinite(expected) or abs(expected) < 1e-6:
        return None
    return float((actual - expected) / expected * 100.0)
