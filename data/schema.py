"""Canonical vocabulary for the dataset: channels, sites, and load flexibility.

Everything here is derived from the audit in PROJECT_AUDIT.md. Nothing is invented:
if a fact is not in the CSVs it is marked unknown rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Flexibility(str, Enum):
    """How freely a load may be moved in time.

    ``CRITICAL`` loads are never proposed for shifting or shedding.
    """

    FLEXIBLE = "flexible"
    LESS_FLEXIBLE = "less_flexible"
    CRITICAL = "critical"


class Provenance(str, Enum):
    """Where a number came from. Every figure the API emits carries one of these."""

    MEASURED = "measured"
    PREDICTED = "predicted"
    ESTIMATED = "estimated"
    SIMULATED = "simulated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ChannelSpec:
    """A metered channel as it appears in ``New_IM_output.csv``."""

    key: str
    """Column prefix, e.g. ``ac`` gives ``ac_state`` / ``ac_power``."""

    label: str
    """Human-readable default name."""

    category: str
    """Coarse grouping used for icons and rollups."""

    flexibility: Flexibility

    metadata_type: str | None = None
    """Matching ``appliance_type`` value in the metadata CSV, when one exists."""

    named: bool = False
    """True when the CSV also carries a ``<key>_name`` column."""

    ml_appliance: bool = False
    """True when the existing notebook pipeline covers this channel."""


#: Aggregate household channels. These two are the ones the notebook models.
HOUSEHOLD_CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec(
        key="ac",
        label="Air Conditioning",
        category="cooling",
        flexibility=Flexibility.LESS_FLEXIBLE,
        metadata_type="AC",
        ml_appliance=True,
    ),
    ChannelSpec(
        key="geyser",
        label="Water Heater",
        category="water_heating",
        flexibility=Flexibility.FLEXIBLE,
        metadata_type="Geyser",
        ml_appliance=True,
    ),
)

#: Sub-metered channels. Present only on the industrial site in this dataset.
SUB_CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec("ac1", "AC Unit 1", "cooling", Flexibility.LESS_FLEXIBLE, named=True),
    ChannelSpec("ac2", "AC Unit 2", "cooling", Flexibility.LESS_FLEXIBLE, named=True),
    ChannelSpec("ac3", "AC Unit 3", "cooling", Flexibility.LESS_FLEXIBLE, named=True),
    ChannelSpec(
        "cell_tester1", "Cell Tester 1", "test_equipment", Flexibility.LESS_FLEXIBLE, named=True
    ),
    # Environmental chambers hold samples at a controlled temperature. Interrupting one
    # invalidates the test inside it, so they are treated as critical load.
    *(
        ChannelSpec(f"chamber{i}", f"Chamber {i}", "process", Flexibility.CRITICAL, named=True)
        for i in range(1, 10)
    ),
)

ALL_CHANNELS: tuple[ChannelSpec, ...] = HOUSEHOLD_CHANNELS + SUB_CHANNELS

CHANNELS_BY_KEY: dict[str, ChannelSpec] = {c.key: c for c in ALL_CHANNELS}

#: Appliance keys the ported notebook pipeline supports.
ML_APPLIANCES: tuple[str, ...] = tuple(c.key for c in ALL_CHANNELS if c.ml_appliance)

#: ``merged_df.csv`` uses older site identifiers for three Jaipur homes.
SITE_ALIASES: dict[str, str] = {
    "House1_Jaipur": "House_1",
    "House2_Jaipur": "House_2",
    "House3_Jaipur": "House_4",
}


@dataclass(frozen=True)
class SiteProfile:
    """Descriptive context for a site. Location is read off the identifier."""

    site_id: str
    display_name: str
    location: str
    kind: str  # "residential" | "industrial"


def _profile(site_id: str) -> SiteProfile:
    if site_id.startswith("Singapore"):
        return SiteProfile(site_id, site_id.replace("_", " "), "Singapore", "industrial")
    if "_" in site_id and not site_id.split("_")[-1].isdigit():
        base, location = site_id.split("_", 1)
        number = "".join(ch for ch in base if ch.isdigit()) or "1"
        return SiteProfile(site_id, f"House {number}, {location}", location, "residential")
    number = site_id.split("_")[-1]
    # House_1 / House_2 / House_4 are the Jaipur homes (see SITE_ALIASES).
    return SiteProfile(site_id, f"House {number}, Jaipur", "Jaipur", "residential")


def site_profile(site_id: str) -> SiteProfile:
    return _profile(site_id)


#: Reading interval in hours. Confirmed at 30 minutes across all 22,084 rows,
#: but the loader re-derives it from the data and warns on mismatch.
NOMINAL_INTERVAL_HOURS: float = 0.5


@dataclass
class ChannelCapability:
    """What the platform is actually able to do for one channel at one site."""

    key: str
    label: str
    category: str
    flexibility: Flexibility
    has_power_signal: bool
    has_state_signal: bool
    has_metadata: bool
    ml_supported: bool = False
    notes: list[str] = field(default_factory=list)
