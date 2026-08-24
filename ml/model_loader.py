"""Load and cache trained artefacts. Serving never retrains.

Artefacts are produced by :mod:`ml.train` and written to ``ml/artifacts/``:

* ``registry.json`` -- index of every trained (site, appliance) pair with its metrics
* ``<site>__<appliance>.joblib`` -- the baseline, the classifier and their metadata

If artefacts are missing the platform degrades gracefully: expected-vs-actual analysis
still works wherever a baseline can be fitted on the fly, and the API reports the
classifier as unavailable rather than failing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import joblib

from data.loaders import paths

from .baseline import BaselineModel

logger = logging.getLogger(__name__)

REGISTRY_PATH = paths.ARTIFACT_DIR / "registry.json"


def artifact_path(site_id: str, appliance: str) -> "Any":
    return paths.ARTIFACT_DIR / f"{site_id}__{appliance}.joblib"


@dataclass
class TrainedPair:
    """Everything needed to score one (site, appliance) pair."""

    site_id: str
    appliance: str
    baseline: BaselineModel
    classifier: Any | None
    model_features: tuple[str, ...]
    metrics: dict
    trained_at: str
    pipeline_version: str

    @property
    def has_classifier(self) -> bool:
        return self.classifier is not None

    def feature_importance(self) -> dict[str, float]:
        if self.classifier is None:
            return {}
        return {
            name: float(value)
            for name, value in zip(self.model_features, self.classifier.feature_importances_)
        }


@lru_cache(maxsize=1)
def load_registry() -> dict:
    """Return the artefact index, or an empty registry when nothing is trained yet."""
    if not REGISTRY_PATH.exists():
        logger.warning(
            "No model registry at %s. Run `python -m ml.train` to build artefacts.",
            REGISTRY_PATH,
        )
        return {"pipeline_version": None, "trained_at": None, "pairs": []}
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def registry_pairs() -> list[dict]:
    return load_registry().get("pairs", [])


def is_trained(site_id: str, appliance: str) -> bool:
    return artifact_path(site_id, appliance).exists()


def trained_pairs_for_site(site_id: str) -> list[str]:
    return [
        entry["appliance"]
        for entry in registry_pairs()
        if entry["site_id"] == site_id and entry.get("has_classifier")
    ]


@lru_cache(maxsize=64)
def load_pair(site_id: str, appliance: str) -> TrainedPair | None:
    """Load one trained pair. Returns ``None`` when no artefact exists."""
    path = artifact_path(site_id, appliance)
    if not path.exists():
        return None
    try:
        payload = joblib.load(path)
    except Exception:  # pragma: no cover - corrupt artefact
        logger.exception("Failed to load artefact %s", path)
        return None
    return TrainedPair(
        site_id=site_id,
        appliance=appliance,
        baseline=payload["baseline"],
        classifier=payload.get("classifier"),
        model_features=tuple(payload["model_features"]),
        metrics=payload.get("metrics", {}),
        trained_at=payload.get("trained_at", "unknown"),
        pipeline_version=payload.get("pipeline_version", "unknown"),
    )


def save_pair(
    site_id: str,
    appliance: str,
    baseline: BaselineModel,
    classifier: Any | None,
    model_features: tuple[str, ...],
    metrics: dict,
    trained_at: str,
    pipeline_version: str,
) -> None:
    paths.ensure_dirs()
    joblib.dump(
        {
            "baseline": baseline,
            "classifier": classifier,
            "model_features": list(model_features),
            "metrics": metrics,
            "trained_at": trained_at,
            "pipeline_version": pipeline_version,
        },
        artifact_path(site_id, appliance),
    )


def save_registry(registry: dict) -> None:
    paths.ensure_dirs()
    with REGISTRY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(registry, handle, indent=2, default=str)
    load_registry.cache_clear()


def clear_cache() -> None:
    load_registry.cache_clear()
    load_pair.cache_clear()
