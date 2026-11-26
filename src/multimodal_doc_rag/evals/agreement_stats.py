"""Uncertainty on judge-vs-human agreement. REPORTED BESIDE the gate, not instead of it.

The calibration gate (ADR 0016, 0019) is Cohen's kappa >= 0.60 on the point estimate, from
`calibration.cohens_kappa`. With about 25 hand grades (`gates.toml` evidence minimum) a
point estimate is noisy. These functions show how noisy. Changing the gate itself needs a
superseding ADR, so nothing here may be wired into `release_check.py` as a gate.

Options:
- Unweighted kappa (status quo). Every disagreement counts the same. But grades are ordinal
  (0, 0.5, 1): judge 1 vs human 0 is worse than judge 1 vs human 0.5.
- Weighted kappa (linear or quadratic). Disagreements are penalised by distance, so a near
  miss costs less. Quadratic is the usual default and tracks correlation. Linear is easier
  to explain. Formula: 1 - sum(w * observed) / sum(w * expected), with w = |i - j| (linear)
  or (i - j)^2 (quadratic) over the grade levels.
- Bootstrap confidence interval. Resample the items with replacement, recompute kappa each
  time, take the alpha/2 and 1 - alpha/2 percentiles. Why it works: it asks how much kappa
  would move if we had graded a different sample of the same size, with no formula needed.
  Resample ITEMS (pairs), never the two lists separately. Skip resamples where kappa is
  undefined.
- Gwet's AC1. Kappa collapses when one grade dominates (most answers are correct), because
  chance agreement p_e gets large. AC1 uses a different chance model that stays stable. Not
  implemented here; named so you can explain why a low kappa with high raw agreement happens.

Reported next to the existing numbers in the calibration report. Both functions return None
when the statistic is undefined (for example both raters always give one grade).
"""

from collections.abc import Sequence
from typing import Literal


def weighted_kappa(
    a: Sequence[float],
    b: Sequence[float],
    weights: Literal["linear", "quadratic"] = "quadratic",
) -> float | None:
    """Weighted Cohen's kappa over ordinal grades. 1.0 for identical lists, None if undefined."""
    # TODO(human): build the observed and expected matrices over the grade levels, apply weights.
    raise NotImplementedError("TODO(human): weighted kappa, None when expected disagreement is 0")


def kappa_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    n_resamples: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval (lo, hi) for unweighted kappa, resampling item pairs."""
    # TODO(human): seeded resampling of indices, kappa per resample, percentiles; None if no kappa.
    raise NotImplementedError("TODO(human): seeded percentile bootstrap of cohens_kappa over items")
