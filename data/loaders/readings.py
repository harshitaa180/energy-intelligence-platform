"""Single entry point for half-hourly meter readings.

The frame is parsed, validated and cached once per process. API routes must never
read a CSV directly -- they call :func:`get_readings` or one of the site helpers.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import pandas as pd

from ..schema import (
    ALL_CHANNELS,
    CHANNELS_BY_KEY,
    NOMINAL_INTERVAL_HOURS,
    SITE_ALIASES,
    ChannelCapability,
    Flexibility,
)
from ..validators import ValidationReport, validate_readings
from . import paths
from .metadata import get_metadata

logger = logging.getLogger(__name__)

#: Filled by :func:`get_readings` so ``/api/health`` can report ingestion quality.
_last_report: ValidationReport | None = None


def _read_primary() -> pd.DataFrame:
    path = paths.resolve(paths.READINGS_CSV)
    usecols = ["date_time", "house_id", "Temperature", "Humidity"]
    for channel in ALL_CHANNELS:
        usecols += [f"{channel.key}_state", f"{channel.key}_power"]
        if channel.named:
            usecols.append(f"{channel.key}_name")

    header = pd.read_csv(path, nrows=0).columns.tolist()
    usecols = [c for c in usecols if c in header]

    # ``*_name`` columns mix strings and the literal "NA"; read them as text.
    name_cols = {c: "string" for c in usecols if c.endswith("_name")}
    df = pd.read_csv(path, usecols=usecols, dtype=name_cols)
    # Timestamps are DD-MM-YYYY HH:MM. Month-first parsing corrupts the series silently.
    df["date_time"] = pd.to_datetime(df["date_time"], dayfirst=True, errors="coerce")
    df["house_id"] = df["house_id"].astype(str).str.strip().replace(SITE_ALIASES)
    return df


@lru_cache(maxsize=1)
def get_readings() -> pd.DataFrame:
    """Return the validated readings frame. Cached for the lifetime of the process."""
    global _last_report
    df = _read_primary()
    df, report = validate_readings(df)
    _last_report = report
    if report.warnings:
        for warning in report.warnings:
            logger.warning("readings: %s", warning)
    logger.info(
        "Loaded %s readings across %s sites", f"{report.rows_out:,}", df["house_id"].nunique()
    )
    return df


def get_validation_report() -> dict:
    if _last_report is None:
        get_readings()
    assert _last_report is not None
    return _last_report.as_dict()


@lru_cache(maxsize=1)
def interval_hours() -> float:
    """Median sampling interval in hours, derived from the data rather than assumed."""
    df = get_readings()
    deltas = df.groupby("house_id")["date_time"].diff().dropna().dt.total_seconds() / 3600.0
    if deltas.empty:
        return NOMINAL_INTERVAL_HOURS
    return float(deltas.median())


@lru_cache(maxsize=1)
def list_sites() -> tuple[str, ...]:
    return tuple(sorted(get_readings()["house_id"].unique()))


def get_site_readings(site_id: str) -> pd.DataFrame:
    """Rows for one site, chronologically sorted. Raises ``KeyError`` if unknown."""
    if site_id not in list_sites():
        raise KeyError(site_id)
    df = get_readings()
    return df[df["house_id"] == site_id].sort_values("date_time").reset_index(drop=True)


@lru_cache(maxsize=64)
def channel_display_names(site_id: str) -> dict[str, str]:
    """Resolve each channel's label, preferring the ``<key>_name`` value in the CSV."""
    site = get_site_readings(site_id)
    names: dict[str, str] = {}
    for channel in ALL_CHANNELS:
        label = channel.label
        name_col = f"{channel.key}_name"
        if name_col in site.columns:
            distinct = [
                value
                for value in site[name_col].dropna().astype(str).unique()
                if value not in ("NA", "nan", "")
            ]
            if distinct:
                label = f"{channel.label} ({distinct[0]})"
        names[channel.key] = label
    return names


@lru_cache(maxsize=64)
def site_capabilities(site_id: str) -> tuple[ChannelCapability, ...]:
    """Which channels exist at a site, and what analysis each one supports.

    A channel is only reported when it carries a power or state signal. Channels with
    power but a permanently-zero state column are kept but flagged, because every
    feature in the ported ML pipeline is computed over on-state rows only.
    """
    site = get_site_readings(site_id)
    metadata = get_metadata()
    labels = channel_display_names(site_id)
    capabilities: list[ChannelCapability] = []

    for channel in ALL_CHANNELS:
        power_col = f"{channel.key}_power"
        state_col = f"{channel.key}_state"
        if power_col not in site.columns:
            continue

        has_power = bool(site[power_col].abs().sum() > 0)
        has_state = bool(state_col in site.columns and site[state_col].sum() > 0)
        if not has_power and not has_state:
            continue

        has_metadata = bool(
            channel.metadata_type is not None
            and not metadata[
                (metadata["house_id"] == site_id)
                & (metadata["appliance_type"] == channel.metadata_type)
            ].empty
        )

        notes: list[str] = []
        if has_power and not has_state:
            notes.append(
                "On/off state is 0 for every reading at this site, so behavioural "
                "features and inefficiency classification are unavailable."
            )
        if channel.ml_appliance and not has_metadata:
            notes.append(
                "No appliance metadata (brand / star rating) for this site, so the "
                "star-adjusted threshold and replacement analysis are unavailable."
            )

        capabilities.append(
            ChannelCapability(
                key=channel.key,
                label=labels.get(channel.key, channel.label),
                category=channel.category,
                flexibility=channel.flexibility,
                has_power_signal=has_power,
                has_state_signal=has_state,
                has_metadata=has_metadata,
                ml_supported=False,  # set by the ML registry once artefacts exist
                notes=notes,
            )
        )

    return tuple(capabilities)


def site_channel_keys(site_id: str) -> list[str]:
    return [c.key for c in site_capabilities(site_id)]


def flexibility_of(channel_key: str) -> Flexibility:
    spec = CHANNELS_BY_KEY.get(channel_key)
    return spec.flexibility if spec else Flexibility.LESS_FLEXIBLE


def clear_cache() -> None:
    """Drop every cached frame. Used by tests."""
    get_readings.cache_clear()
    list_sites.cache_clear()
    interval_hours.cache_clear()
    channel_display_names.cache_clear()
    site_capabilities.cache_clear()
