"""Ingestion, validation and aggregation."""

from __future__ import annotations

import pandas as pd
import pytest

from data.loaders import (
    get_metadata,
    get_readings,
    get_site_readings,
    get_validation_report,
    interval_hours,
    list_sites,
    site_capabilities,
)
from data.schema import Flexibility
from data.transformers import (
    add_energy_columns,
    complete_days_only,
    resample_energy,
    site_interval_energy,
)
from tests.conftest import INDUSTRIAL_SITE, NO_STATE_SITE, PRIMARY_SITE


def test_all_rows_load_and_validate():
    report = get_validation_report()
    assert report["rows_in"] == 22084
    assert report["rows_out"] == 22084, "no row should be dropped by validation"
    assert report["dropped_unparseable_time"] == 0
    assert report["dropped_duplicates"] == 0


def test_timestamps_are_parsed_day_first():
    """The CSV is DD-MM-YYYY. Month-first parsing would silently corrupt the series."""
    readings = get_site_readings(PRIMARY_SITE)
    span = readings["date_time"].max() - readings["date_time"].min()
    # House_4 covers roughly mid-June to mid-October 2025.
    assert pd.Timedelta(days=100) < span < pd.Timedelta(days=130)
    assert readings["date_time"].min().year == 2025


def test_readings_are_sorted_per_site():
    for site in list_sites():
        readings = get_site_readings(site)
        assert readings["date_time"].is_monotonic_increasing


def test_site_aliases_are_normalised():
    sites = list_sites()
    assert "House_1" in sites and "House_4" in sites
    for legacy in ("House1_Jaipur", "House2_Jaipur", "House3_Jaipur"):
        assert legacy not in sites


def test_interval_is_half_hourly():
    assert interval_hours() == pytest.approx(0.5)


def test_energy_conversion_matches_power_times_interval():
    frame = site_interval_energy(PRIMARY_SITE)
    expected = frame["ac_power"] * interval_hours() / 1000.0
    assert frame["ac_energy_kwh"].sub(expected).abs().max() < 1e-9


def test_no_negative_energy_anywhere():
    for site in list_sites():
        frame = site_interval_energy(site)
        assert (frame["total_energy_kwh"] >= 0).all()


def test_metadata_drops_blank_separator_rows():
    metadata = get_metadata()
    assert len(metadata) == 23
    assert metadata["house_id"].nunique() == 3
    # Unknown ratings stay NaN rather than being defaulted.
    assert metadata["star_rating"].isna().sum() == 5


def test_site_without_state_signal_is_flagged_not_hidden():
    capabilities = {c.key: c for c in site_capabilities(NO_STATE_SITE)}
    assert "ac" in capabilities, "the channel is still reported"
    assert capabilities["ac"].has_power_signal is True
    assert capabilities["ac"].has_state_signal is False
    assert capabilities["ac"].notes, "the reason must be stated"


def test_industrial_chambers_are_classified_critical():
    capabilities = {c.key: c for c in site_capabilities(INDUSTRIAL_SITE)}
    chambers = [c for key, c in capabilities.items() if key.startswith("chamber")]
    assert chambers
    assert all(c.flexibility is Flexibility.CRITICAL for c in chambers)


def test_zero_power_channels_are_not_reported():
    """chamber2, chamber3 and chamber9 read 0 W throughout and must not appear."""
    keys = {c.key for c in site_capabilities(INDUSTRIAL_SITE)}
    assert "chamber2" not in keys
    assert "chamber9" not in keys


def test_complete_days_filter_removes_partial_days():
    daily = resample_energy(site_interval_energy(PRIMARY_SITE), "daily")
    complete = complete_days_only(daily)
    assert len(complete) < len(daily), "this dataset has partial days"
    assert (complete["reading_count"] >= 43).all()


def test_add_energy_columns_handles_missing_channel():
    frame = get_readings().head(10).copy()
    out = add_energy_columns(frame, ["ac", "does_not_exist"])
    assert "ac_energy_kwh" in out.columns
    assert "total_energy_kwh" in out.columns
