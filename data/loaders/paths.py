"""Filesystem locations for raw and derived data.

Every path in the project resolves through here so that moving the dataset only
requires editing one module.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

ML_DIR = PROJECT_ROOT / "ml"
ARTIFACT_DIR = ML_DIR / "artifacts"

#: Canonical half-hourly readings (superset of ``merged_df.csv``; see PROJECT_AUDIT.md section 2).
READINGS_CSV = RAW_DIR / "New_IM_output.csv"

#: Legacy subset kept for cross-checking. Same rows minus ``Singapore_2``.
LEGACY_READINGS_CSV = RAW_DIR / "merged_df.csv"

#: Appliance metadata: brand, star rating, unit count. Filename typo is upstream.
APPLIANCE_METADATA_CSV = RAW_DIR / "hosue_appliances_gt.csv"


def resolve(candidate: Path) -> Path:
    """Return ``candidate`` if it exists, else look for the same name at the project root.

    The CSVs were originally dropped at the repository root; this keeps the loader
    working if someone puts them back there.
    """
    if candidate.exists():
        return candidate
    fallback = PROJECT_ROOT / candidate.name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        f"Dataset not found. Looked in {candidate} and {fallback}."
    )


def ensure_dirs() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
