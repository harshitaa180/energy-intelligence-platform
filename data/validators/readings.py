"""Schema and sanity checks applied once, at ingestion time.

The checks are non-fatal by design: a malformed row is dropped and counted, so a
single bad record can never take the platform down.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..schema import ALL_CHANNELS

REQUIRED_COLUMNS = ("date_time", "house_id", "Temperature", "Humidity")

#: Physically implausible readings. Above this a watt value is treated as a sensor fault.
MAX_PLAUSIBLE_WATTS = 50_000.0


@dataclass
class ValidationReport:
    """Outcome of validating one readings file."""

    rows_in: int = 0
    rows_out: int = 0
    dropped_unparseable_time: int = 0
    dropped_duplicates: int = 0
    negative_power_clipped: int = 0
    implausible_power_nulled: int = 0
    missing_weather: int = 0
    irregular_interval_sites: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "dropped_unparseable_time": self.dropped_unparseable_time,
            "dropped_duplicates": self.dropped_duplicates,
            "negative_power_clipped": self.negative_power_clipped,
            "implausible_power_nulled": self.implausible_power_nulled,
            "missing_weather": self.missing_weather,
            "irregular_interval_sites": self.irregular_interval_sites,
            "warnings": self.warnings,
        }


def validate_readings(df: pd.DataFrame) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate and clean a normalised readings frame.

    Expects the frame to already have ``date_time`` parsed and ``house_id`` normalised.
    """
    report = ValidationReport(rows_in=len(df))

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Readings file is missing required columns: {missing}")

    unparseable = int(df["date_time"].isna().sum())
    if unparseable:
        report.dropped_unparseable_time = unparseable
        df = df[df["date_time"].notna()]

    before = len(df)
    df = df.drop_duplicates(subset=["house_id", "date_time"], keep="first")
    report.dropped_duplicates = before - len(df)

    for channel in ALL_CHANNELS:
        power_col = f"{channel.key}_power"
        state_col = f"{channel.key}_state"
        if power_col in df.columns:
            values = pd.to_numeric(df[power_col], errors="coerce")
            report.negative_power_clipped += int((values < 0).sum())
            values = values.clip(lower=0)
            implausible = values > MAX_PLAUSIBLE_WATTS
            report.implausible_power_nulled += int(implausible.sum())
            values = values.mask(implausible)
            df[power_col] = values.fillna(0.0)
        if state_col in df.columns:
            df[state_col] = (
                pd.to_numeric(df[state_col], errors="coerce").fillna(0).clip(0, 1).astype("int8")
            )

    for col in ("Temperature", "Humidity"):
        values = pd.to_numeric(df[col], errors="coerce")
        report.missing_weather += int(values.isna().sum())
        # Forward/backward fill within a site: weather is slowly varying and the gaps
        # in this dataset are isolated points.
        df[col] = values.groupby(df["house_id"]).transform(lambda s: s.ffill().bfill())

    df = df.sort_values(["house_id", "date_time"]).reset_index(drop=True)
    report.rows_out = len(df)

    for site, group in df.groupby("house_id", sort=True):
        if len(group) < 3:
            continue
        deltas = group["date_time"].diff().dropna().dt.total_seconds() / 3600.0
        median = float(np.median(deltas))
        if not np.isclose(median, 0.5, atol=1e-6):
            report.irregular_interval_sites.append(f"{site}: median interval {median:.3f} h")

    return df, report
