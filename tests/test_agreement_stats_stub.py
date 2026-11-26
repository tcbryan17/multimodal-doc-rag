# These tests define the contract Toby must meet. They are marked xfail(strict=True) so CI
# stays green while the function is a stub. Once you implement it, each test flips to a
# strict XPASS failure: that is your reminder to delete the xfail marker.
"""Contract tests for weighted kappa and the bootstrap CI (hand-computed expected values)."""

import pytest

from multimodal_doc_rag.evals.agreement_stats import kappa_bootstrap_ci, weighted_kappa
from multimodal_doc_rag.evals.calibration import cohens_kappa

TODO = pytest.mark.xfail(raises=NotImplementedError, strict=True, reason="TODO(human): agreement")

A = [0.0, 0.5, 1.0, 1.0, 0.0, 0.5, 1.0, 0.0, 1.0, 0.5]
B = [0.0, 0.5, 1.0, 0.5, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0]


@TODO
@pytest.mark.parametrize("weights", ["linear", "quadratic"])
def test_weighted_kappa_identical_is_one(weights: str) -> None:
    assert weighted_kappa(A, A, weights=weights) == pytest.approx(1.0)  # type: ignore[arg-type]


@TODO
def test_weighted_kappa_single_grade_is_undefined() -> None:
    assert weighted_kappa([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) is None


@TODO
def test_weighted_kappa_binary_grades_equal_unweighted() -> None:
    # With two levels the only weight is 1, so weighted kappa is plain kappa.
    a = [0.0, 0.0, 1.0, 1.0, 1.0, 0.0]
    b = [0.0, 1.0, 1.0, 1.0, 0.0, 0.0]
    assert weighted_kappa(a, b) == pytest.approx(cohens_kappa(a, b))


@TODO
def test_weighted_kappa_hand_computed_quadratic() -> None:
    # a = [0, 1], b = [0, 0.5]. Level indexes: 0 -> 0, 0.5 -> 1, 1 -> 2.
    # Observed disagreement: pairs (0,0) and (2,1) -> (0 + 1) / 2 = 0.5.
    # Expected: marginals a = {0: .5, 2: .5}, b = {0: .5, 1: .5}. Sum of p_a * p_b * (i-j)^2
    # = .25*0 + .25*1 + .25*4 + .25*1 = 1.5. Kappa = 1 - 0.5 / 1.5 = 2/3.
    assert weighted_kappa([0.0, 1.0], [0.0, 0.5]) == pytest.approx(2 / 3)


@TODO
def test_near_miss_costs_less_than_far_miss() -> None:
    base = [0.0, 0.5, 1.0, 0.0, 1.0, 0.5]
    near = [0.0, 0.5, 0.5, 0.0, 1.0, 0.5]  # one 1 -> 0.5
    far = [0.0, 0.5, 0.0, 0.0, 1.0, 0.5]  # one 1 -> 0
    kn = weighted_kappa(base, near)
    kf = weighted_kappa(base, far)
    assert kn is not None and kf is not None
    assert kn > kf


@TODO
def test_ci_brackets_point_estimate_and_is_ordered() -> None:
    ci = kappa_bootstrap_ci(A, B, n_resamples=500)
    point = cohens_kappa(A, B)
    assert ci is not None and point is not None
    lo, hi = ci
    assert lo <= hi
    assert lo <= point <= hi


@TODO
def test_ci_is_deterministic_for_a_seed() -> None:
    assert kappa_bootstrap_ci(A, B, seed=3, n_resamples=200) == kappa_bootstrap_ci(
        A, B, seed=3, n_resamples=200
    )


@TODO
def test_ci_is_narrower_for_larger_alpha() -> None:
    wide = kappa_bootstrap_ci(A, B, n_resamples=500, alpha=0.05)
    narrow = kappa_bootstrap_ci(A, B, n_resamples=500, alpha=0.5)
    assert wide is not None and narrow is not None
    assert wide[1] - wide[0] >= narrow[1] - narrow[0]


@TODO
def test_ci_none_when_kappa_undefined() -> None:
    assert kappa_bootstrap_ci([1.0] * 5, [1.0] * 5) is None
