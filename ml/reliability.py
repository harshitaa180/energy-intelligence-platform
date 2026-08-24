"""Grade how much weight a trained pair's classifier output deserves.

Four of the five candidate pairs in this dataset have very short histories, and one
of them ranks no better than chance. Rather than hiding that, every classifier result
the API emits carries a grade from here, and the UI leads with the expected-energy
deviation -- which is well defined even on short histories -- whenever the classifier
is not trustworthy.
"""

from __future__ import annotations

from enum import Enum


class Reliability(str, Enum):
    GOOD = "good"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"
    UNAVAILABLE = "unavailable"


#: Minimum test-window positives before F1 / ROC-AUC mean anything.
MIN_TEST_POSITIVES = 3

#: Minimum test days before the split is worth reporting.
MIN_TEST_DAYS = 8

#: ROC-AUC at or below this is no better than coin-flipping.
CHANCE_ROC_AUC = 0.6


def grade(metrics: dict | None) -> tuple[Reliability, str]:
    """Return a grade and a one-line justification for a pair's metrics."""
    if not metrics or "test_accuracy" not in metrics:
        return (
            Reliability.UNAVAILABLE,
            "No classifier was trained for this appliance; only the expected-energy "
            "baseline is available.",
        )

    positives = int(metrics.get("test_positives", 0) or 0)
    test_days = int(metrics.get("test_days", 0) or 0)
    roc_auc = metrics.get("roc_auc")

    if positives < MIN_TEST_POSITIVES:
        return (
            Reliability.INSUFFICIENT,
            f"Only {positives} inefficient day(s) in the {test_days}-day validation "
            "window, which is too few to measure classifier quality.",
        )

    if roc_auc is not None and roc_auc <= CHANCE_ROC_AUC:
        return (
            Reliability.LIMITED,
            f"Validation ROC-AUC is {roc_auc:.2f}, at or near chance, so this "
            "classifier does not rank days better than the baseline residual does.",
        )

    if test_days < MIN_TEST_DAYS:
        return (
            Reliability.LIMITED,
            f"Validated on only {test_days} days; treat the score as indicative.",
        )

    return (
        Reliability.GOOD,
        f"Validated on {test_days} held-out days "
        f"(ROC-AUC {roc_auc:.2f}, PR-AUC {metrics.get('pr_auc', float('nan')):.2f})."
        if roc_auc is not None
        else f"Validated on {test_days} held-out days.",
    )


def trust_classifier(reliability: Reliability) -> bool:
    """Whether classifier output should drive the headline verdict."""
    return reliability is Reliability.GOOD
