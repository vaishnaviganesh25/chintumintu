"""Threshold calibration.

The operating point is where this project makes its strongest claim - that the
obvious policy ("maximise precision subject to recall >= 90%") is the wrong one on
this data, and that pricing the trade in rupees reverses it. That argument is only
worth making if the arithmetic behind both policies is correct, so it is tested
against hand-constructed score distributions where the right answer is known.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from train_model import (
    calibrate_threshold,
    cost_optimal_threshold,
    expected_cost_at,
)


def separable_scores(n_pos: int = 40, n_neg: int = 360, overlap: float = 0.0):
    """A score distribution with a controllable amount of class overlap.

    Positives sit high and negatives low; `overlap` slides a slice of positives down
    into the negative mass, which is what forces a real precision/recall trade-off
    rather than a threshold that can have everything at once.
    """
    rng = np.random.default_rng(7)
    y = np.array([1] * n_pos + [0] * n_neg)

    pos = rng.uniform(0.70, 0.99, n_pos)
    n_buried = int(n_pos * overlap)
    if n_buried:
        pos[:n_buried] = rng.uniform(0.05, 0.25, n_buried)
    neg = rng.uniform(0.01, 0.30, n_neg)

    return y, np.concatenate([pos, neg])


# --------------------------------------------------------------------------- #
# precision-at-recall
# --------------------------------------------------------------------------- #
def test_the_chosen_point_actually_meets_the_recall_floor():
    y, scores = separable_scores(overlap=0.25)
    result = calibrate_threshold(y, scores, target_recall=0.90)

    assert result["met_target_recall"] is True
    achieved = ((scores >= result["threshold"]) & (y == 1)).sum() / y.sum()
    assert achieved >= 0.90


@pytest.mark.parametrize("target", [0.50, 0.90, 0.99, 1.0])
def test_any_recall_up_to_one_is_reachable_however_bad_the_scores(target):
    """The recall floor is always satisfiable, even on a near-useless model.

    Worth stating explicitly because it is counter-intuitive: a full precision-recall
    curve ends at the lowest observed score, where everything is flagged and recall is
    1.0. So no target in (0, 1] can be infeasible - a weak model meets the floor by
    alerting on almost everything, and pays for it in precision rather than in recall.

    That is exactly why the shipped policy is cost-based. "Recall >= 90%" constrains
    nothing on its own; the rupee cost of the alerts is what does the constraining.
    """
    y, scores = separable_scores(overlap=0.50)
    result = calibrate_threshold(y, scores, target_recall=target)

    assert result["met_target_recall"] is True
    achieved = ((scores >= result["threshold"]) & (y == 1)).sum() / y.sum()
    assert achieved >= target - 1e-9


def test_an_impossible_target_falls_back_to_f1_and_says_so():
    """The defensive branch, reachable only through a misconfigured target.

    A target above 1.0 is the one way to make the floor infeasible. The calibrator must
    then report `met_target_recall=False` rather than silently shipping a threshold
    that misses the stated goal.
    """
    y, scores = separable_scores(overlap=0.50)
    result = calibrate_threshold(y, scores, target_recall=1.5)

    assert result["met_target_recall"] is False
    assert result["threshold"] == pytest.approx(result["f1_optimal_threshold"])


def test_precision_ties_are_broken_towards_catching_more_fraud():
    """Within the tolerance band, prefer recall - a fraction of a percent of precision
    is often one false positive, and paying for it with real missed fraud is a bad trade.
    """
    y, scores = separable_scores(overlap=0.20)

    greedy = calibrate_threshold(y, scores, target_recall=0.80, precision_tolerance=0.0)
    tolerant = calibrate_threshold(y, scores, target_recall=0.80, precision_tolerance=0.05)

    assert tolerant["recall"] >= greedy["recall"]
    assert tolerant["precision"] >= greedy["precision"] - 0.05


def test_returned_metrics_describe_the_returned_threshold():
    """The reported precision and recall must be the ones the threshold produces.

    `precision_recall_curve` returns one more point than it does thresholds, and an
    off-by-one when trimming that sentinel would report a neighbouring operating
    point's numbers - plausible-looking and wrong.
    """
    y, scores = separable_scores(overlap=0.30)
    result = calibrate_threshold(y, scores, target_recall=0.85)

    predicted = scores >= result["threshold"]
    tp = int((predicted & (y == 1)).sum())
    expected_recall = tp / y.sum()
    expected_precision = tp / max(int(predicted.sum()), 1)

    assert result["recall"] == pytest.approx(expected_recall, abs=1e-9)
    assert result["precision"] == pytest.approx(expected_precision, abs=1e-9)


# --------------------------------------------------------------------------- #
# cost-optimal
# --------------------------------------------------------------------------- #
def test_cost_policy_prefers_catching_a_large_fraud_over_avoiding_small_alarms():
    """The whole argument in one test.

    One fraud worth Rs.500,000 sits just above the noise. Letting it through costs
    half a million rupees; the extra false alarms cost Rs.150 each. A cost-aware
    policy must reach down for it.
    """
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    scores = np.array([0.95, 0.20, 0.19, 0.18, 0.17, 0.05, 0.04, 0.03, 0.02, 0.01])
    amounts = np.array([50_000, 500_000, 900, 400, 250, 100, 100, 100, 100, 100], dtype=float)

    result = cost_optimal_threshold(y, scores, amounts, fp_cost=150.0, target_recall=0.5)

    assert result["threshold"] <= 0.20
    assert result["missed_fraud"] == 0
    assert result["recall"] == pytest.approx(1.0)


def test_cost_policy_tolerates_misses_when_the_money_is_small():
    """Symmetry check: the rule follows rupees, not a preference for high recall.

    Here the borderline fraud is worth Rs.60 and clearing it would cost several
    Rs.150 reviews, so leaving it is the cheaper answer.
    """
    y = np.array([1, 1, 0, 0, 0, 0, 0, 0])
    scores = np.array([0.95, 0.12, 0.30, 0.28, 0.26, 0.24, 0.22, 0.14])
    amounts = np.array([80_000, 60, 100, 100, 100, 100, 100, 100], dtype=float)

    result = cost_optimal_threshold(y, scores, amounts, fp_cost=150.0, target_recall=0.0)

    assert result["missed_fraud"] == 1
    assert result["threshold"] > 0.12


def test_the_recall_floor_still_binds_the_cost_policy():
    """Cost minimisation is constrained, not free. The floor is a contract."""
    y = np.array([1, 1, 1, 1, 0, 0, 0, 0, 0, 0])
    scores = np.array([0.99, 0.98, 0.97, 0.10, 0.30, 0.28, 0.26, 0.24, 0.22, 0.20])
    amounts = np.array([9000, 9000, 9000, 50, 100, 100, 100, 100, 100, 100], dtype=float)

    result = cost_optimal_threshold(y, scores, amounts, fp_cost=150.0, target_recall=1.0)

    assert result["recall"] == pytest.approx(1.0)
    assert result["missed_fraud"] == 0


def test_reported_cost_matches_an_independent_recomputation():
    """The sweep and the direct calculation must agree.

    `cost_optimal_threshold` computes every candidate at once with cumulative sums;
    `expected_cost_at` evaluates one threshold directly. They are separate code paths
    to the same number, which makes them a real cross-check.
    """
    y, scores = separable_scores(overlap=0.30)
    rng = np.random.default_rng(11)
    amounts = rng.uniform(100, 90_000, len(y))

    result = cost_optimal_threshold(y, scores, amounts, fp_cost=150.0, target_recall=0.5)
    recomputed = expected_cost_at(y, scores, amounts, result["threshold"], fp_cost=150.0)

    assert recomputed == pytest.approx(result["expected_cost"], rel=1e-9)


def test_the_cost_optimum_is_not_beaten_by_any_other_candidate():
    """Optimality, checked by brute force over the whole score grid."""
    y, scores = separable_scores(overlap=0.35)
    rng = np.random.default_rng(3)
    amounts = rng.uniform(100, 90_000, len(y))

    best = cost_optimal_threshold(y, scores, amounts, fp_cost=150.0, target_recall=0.0)

    for candidate in np.unique(scores):
        cost = expected_cost_at(y, scores, amounts, candidate, fp_cost=150.0)
        assert cost >= best["expected_cost"] - 1e-6


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #
@settings(max_examples=60, deadline=None)
@given(
    target=st.floats(min_value=0.50, max_value=0.99),
    overlap=st.floats(min_value=0.0, max_value=0.45),
)
def test_a_met_target_is_always_genuinely_met(target, overlap):
    """If the calibrator claims it hit the floor, it hit the floor. No exceptions."""
    y, scores = separable_scores(overlap=overlap)
    result = calibrate_threshold(y, scores, target_recall=target)

    if result["met_target_recall"]:
        achieved = ((scores >= result["threshold"]) & (y == 1)).sum() / y.sum()
        assert achieved >= target - 1e-9


@settings(max_examples=50, deadline=None)
@given(overlap=st.floats(min_value=0.0, max_value=0.4))
def test_recall_never_rises_as_the_threshold_rises(overlap):
    """A sanity property the whole calibration argument rests on."""
    y, scores = separable_scores(overlap=overlap)
    grid = np.linspace(0.01, 0.99, 25)
    recalls = [((scores >= t) & (y == 1)).sum() / y.sum() for t in grid]

    # Successive pairs, so the two sequences are deliberately unequal in length -
    # `zip(..., strict=True)` here would raise rather than compare.
    assert all(a >= b - 1e-12 for a, b in pairwise(recalls))


@settings(max_examples=40, deadline=None)
@given(fp_cost=st.floats(min_value=10.0, max_value=5_000.0))
def test_a_dearer_review_never_lowers_the_threshold(fp_cost):
    """As false alarms get more expensive, the policy must become more conservative.

    Monotonicity here is what makes the cost knob interpretable: if raising the review
    cost could ever loosen the threshold, the number would not mean what it says.
    """
    y, scores = separable_scores(overlap=0.25)
    rng = np.random.default_rng(5)
    amounts = rng.uniform(100, 90_000, len(y))

    cheap = cost_optimal_threshold(y, scores, amounts, fp_cost=10.0, target_recall=0.0)
    dearer = cost_optimal_threshold(y, scores, amounts, fp_cost=fp_cost, target_recall=0.0)

    assert dearer["threshold"] >= cheap["threshold"] - 1e-9
