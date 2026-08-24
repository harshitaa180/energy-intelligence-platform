"""Appliance metadata: brand, BEE star rating and unit count per site.

Source: ``hosue_appliances_gt.csv`` (filename typo is upstream). Covers only
House_1, House_2 and House_4 -- see PROJECT_AUDIT.md section 4.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from . import paths


@lru_cache(maxsize=1)
def get_metadata() -> pd.DataFrame:
    """Return cleaned appliance metadata.

    The CSV contains blank separator rows between houses; they are dropped here.
    ``star_rating`` stays ``NaN`` when unknown -- it is never defaulted.
    """
    path = paths.resolve(paths.APPLIANCE_METADATA_CSV)
    df = pd.read_csv(path)
    df = df.dropna(subset=["house_id", "appliance_type"])
    df = df[df["house_id"].astype(str).str.strip() != ""]

    df["house_id"] = df["house_id"].astype(str).str.strip()
    df["appliance_type"] = df["appliance_type"].astype(str).str.strip()
    df["brand"] = df["brand"].astype(str).str.strip().replace({"NA": None, "nan": None})
    df["star_rating"] = pd.to_numeric(
        df["star_rating"].replace({"NA": np.nan}), errors="coerce"
    )
    df["appliance_count"] = (
        pd.to_numeric(df["appliance_count"], errors="coerce").fillna(1).astype(int)
    )
    return df.reset_index(drop=True)


@lru_cache(maxsize=1)
def sites_with_metadata() -> tuple[str, ...]:
    return tuple(sorted(get_metadata()["house_id"].unique()))


def get_star_ratings(appliance_type: str) -> pd.DataFrame:
    """Unit-count-weighted mean star rating per house, matching the notebook.

    Rows with an unknown rating are excluded from the weighting rather than
    imputed, so a house whose ratings are all unknown simply does not appear.
    """
    metadata = get_metadata()
    subset = metadata[metadata["appliance_type"] == appliance_type].dropna(
        subset=["star_rating"]
    )
    if subset.empty:
        return pd.DataFrame(columns=["house_id", "star_rating"])

    records = []
    for house, group in subset.groupby("house_id"):
        records.append(
            {
                "house_id": house,
                "star_rating": float(
                    np.average(group["star_rating"], weights=group["appliance_count"])
                ),
            }
        )
    return pd.DataFrame(records)


def units_for(site_id: str, appliance_type: str) -> pd.DataFrame:
    """Individual metadata rows for one site and appliance type."""
    metadata = get_metadata()
    return metadata[
        (metadata["house_id"] == site_id) & (metadata["appliance_type"] == appliance_type)
    ].reset_index(drop=True)


def unit_count(site_id: str, appliance_type: str) -> int:
    rows = units_for(site_id, appliance_type)
    return int(rows["appliance_count"].sum()) if not rows.empty else 0


def clear_cache() -> None:
    get_metadata.cache_clear()
    sites_with_metadata.cache_clear()
