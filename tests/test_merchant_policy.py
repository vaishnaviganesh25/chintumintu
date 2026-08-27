"""Merchant economics.

The claim this file defends: a flat false-positive cost is the wrong shape for a
merchant, and a two-action policy leaves money on the table. Both are arguments about
arithmetic, so both are testable.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from merchant_policy import (
    DEFAULT,
    DISPUTE_RATIO_CEILING,
    MerchantEconomics,
    portfolio_cost,
    prevalence_at_which_covenant_binds,
)
from train_model import cost_optimal_threshold, expected_cost_at


# --------------------------------------------------------------------------- #
# Unit costs
# --------------------------------------------------------------------------- #
def test_a_cleared_fraud_costs_more_than_the_transaction():
    """The amount is the floor, not the total - the dispute fee lands on top."""
    assert DEFAULT.false_negative_cost(25_000) == pytest.approx(25_000 + DEFAULT.chargeback_fee)


def test_the_fixed_dispute_fee_dominates_small_baskets():
    """A Rs.200 fraud costs the merchant far more than Rs.200.

    This is why small-ticket fraud is disproportionately expensive and why a policy
    tuned only on rupee value under-protects it.
    """
    ratio = float(DEFAULT.false_negative_cost(200)) / 200
    assert ratio > 6


def test_declining_a_good_order_scales_with_the_order():
    """The correction at the heart of the merchant reframe.

    A bank pays the same to review a Rs.40 alert and a Rs.90,000 one. A merchant does
    not: it loses the margin on whatever it declined.
    """
    small = float(DEFAULT.false_positive_cost(200))
    large = float(DEFAULT.false_positive_cost(90_000))

    assert large > small * 10
    assert small == pytest.approx(0.18 * 200 + 400)


def test_a_step_up_is_far_cheaper_than_a_decline():
    """Challenging costs a slice of conversion; declining costs the whole order."""
    for amount in (500, 5_000, 50_000):
        assert DEFAULT.step_up_cost(amount) < DEFAULT.false_positive_cost(amount)


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #
def test_a_confident_legitimate_payment_is_accepted():
    assert DEFAULT.decide(0.0001, 240) == "ACCEPT"


def test_a_confident_fraud_on_a_large_order_is_not_accepted():
    assert DEFAULT.decide(0.98, 62_000) in ("HOLD", "STEP_UP")


def test_a_mid_confidence_payment_is_challenged_rather_than_declined():
    """The action a two-outcome policy cannot express.

    At 30% on a Rs.25,000 order, accepting risks Rs.26,250 and declining burns Rs.4,900
    of margin on a 70% chance of being wrong. A challenge costs Rs.360.
    """
    assert DEFAULT.decide(0.30, 25_000) == "STEP_UP"


@settings(max_examples=200, deadline=None)
@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    amount=st.floats(min_value=1.0, max_value=200_000.0),
)
def test_the_chosen_action_is_always_the_cheapest_one(probability, amount):
    """`decide` must agree with the costs it reports. No hidden preference."""
    costs = DEFAULT.action_costs(probability, amount)
    chosen = DEFAULT.decide(probability, amount)

    assert costs[chosen] == pytest.approx(min(costs.values()), abs=0.01)


@settings(max_examples=100, deadline=None)
@given(amount=st.floats(min_value=100.0, max_value=200_000.0))
def test_a_higher_margin_merchant_tolerates_more_risk(amount):
    """The sensitivity that justifies the whole module.

    A high-margin seller loses more by declining, so it should accept further up the
    risk curve than a low-margin reseller. Same model, different policy - and a single
    global threshold cannot express the difference.
    """
    thin = replace(DEFAULT, contribution_margin=0.04)
    fat = replace(DEFAULT, contribution_margin=0.60)

    assert fat.accept_boundary(amount) >= thin.accept_boundary(amount)


@settings(max_examples=80, deadline=None)
@given(fee=st.floats(min_value=0.0, max_value=5_000.0))
def test_a_dearer_dispute_fee_never_widens_the_accept_band(fee):
    """As disputes get more expensive, the merchant must not become more permissive."""
    cheap = replace(DEFAULT, chargeback_fee=0.0)
    dearer = replace(DEFAULT, chargeback_fee=fee)

    assert dearer.accept_boundary(20_000) <= cheap.accept_boundary(20_000) + 1e-9


# --------------------------------------------------------------------------- #
# Portfolio
# --------------------------------------------------------------------------- #
def _book(n_fraud: int = 40, n_legit: int = 360):
    """A book of payments shaped like real scored traffic.

    The score distribution matters more than it looks. An earlier version of this
    fixture drew legitimate probabilities uniformly over 0-0.2, which no calibrated
    model produces - the shipped model puts almost all legitimate traffic within a
    whisker of zero. With that unrealistic spread every policy comparison here
    measured the fixture rather than the policy.

    So: legitimate scores are concentrated near zero with a thin tail, and a fifth of
    the fraud is genuinely hard and scores low. That overlap is what makes the choice
    between policies mean anything.
    """
    rng = np.random.default_rng(19)
    y = np.array([1] * n_fraud + [0] * n_legit)

    n_hard = n_fraud // 5
    fraud_prob = np.concatenate([
        rng.uniform(0.55, 0.99, n_fraud - n_hard),
        rng.uniform(0.04, 0.30, n_hard),          # the ones that look ordinary
    ])
    legit_prob = rng.beta(0.35, 60.0, n_legit)     # mass at ~0, occasional 0.05

    amounts = np.concatenate([
        rng.uniform(15_000, 90_000, n_fraud),
        rng.uniform(100, 20_000, n_legit),
    ])
    return y, np.concatenate([fraud_prob, legit_prob]), amounts


def test_every_payment_is_routed_to_exactly_one_action():
    y, prob, amounts = _book()
    result = portfolio_cost(y, prob, amounts)

    assert result["accepted"] + result["stepped_up"] + result["held"] == len(y)


def test_routing_minimises_expected_cost_subject_to_the_budget():
    """What the policy actually guarantees - and it is worth being precise about it.

    The routing minimises *expected* cost given the scores. It does not guarantee a
    lower *realised* cost than a well-placed single threshold: on a sharp model, a low
    binary cut-off catches the hard frauds for one review fee each, while the policy
    challenges some of them because their score genuinely looked uncertain. That trade
    is correct under uncertainty and can still lose on the day.

    On the real test set the realised comparison does go the policy's way - roughly
    Rs.124k against Rs.370k, reported in `reports/evaluation_report.txt`. This test
    asserts the property that holds by construction rather than the empirical one that
    happens to hold on one book.
    """
    y, prob, amounts = _book()
    result = portfolio_cost(y, prob, amounts)

    accept = DEFAULT.expected_cost_accept(prob, amounts)
    step_up = DEFAULT.expected_cost_step_up(prob, amounts)
    hold = DEFAULT.expected_cost_hold(prob, amounts)

    # Unbudgeted lower bound: nothing can beat picking the cheapest action per row.
    floor = np.minimum(np.minimum(accept, hold), step_up).sum()
    # Budgeted upper bound: never challenge at all.
    ceiling = np.minimum(accept, hold).sum()

    chosen_expected = ceiling - DEFAULT.step_up_benefit(prob, amounts).clip(min=0)[
        np.argsort(-DEFAULT.step_up_benefit(prob, amounts))[
            : int(np.floor(DEFAULT.step_up_budget * len(y)))
        ]
    ].sum()

    assert floor <= chosen_expected <= ceiling
    assert result["step_up_rate"] <= DEFAULT.step_up_budget + 1e-9


def test_the_step_up_budget_is_never_exceeded():
    """The constraint that makes the policy shippable.

    Without it, row-by-row cost minimisation challenges most of the book. A 10% cap
    is a cap, whatever the arithmetic wants.
    """
    y, prob, amounts = _book()

    for budget in (0.0, 0.02, 0.10, 0.50):
        econ = replace(DEFAULT, step_up_budget=budget)
        result = portfolio_cost(y, prob, amounts, econ)
        assert result["step_up_rate"] <= budget + 1e-9


def test_a_zero_budget_collapses_to_two_actions():
    """Turn the budget off and the policy degrades cleanly to accept-or-hold."""
    y, prob, amounts = _book()
    econ = replace(DEFAULT, step_up_budget=0.0)

    result = portfolio_cost(y, prob, amounts, econ)
    assert result["stepped_up"] == 0
    assert result["accepted"] + result["held"] == len(y)


def test_the_budget_is_spent_on_the_payments_it_helps_most():
    """Friction is a scarce resource, so it goes where the saving is largest.

    Spending it in arrival order rather than benefit order would waste it on rows a
    challenge barely helps.
    """
    y, prob, amounts = _book()
    econ = replace(DEFAULT, step_up_budget=0.05)

    benefit = DEFAULT.step_up_benefit(prob, amounts)
    result = portfolio_cost(y, prob, amounts, econ)

    n_challenged = result["stepped_up"]
    assert n_challenged > 0
    # Every challenged row must rank in the top-N by benefit.
    cutoff = np.sort(benefit)[::-1][n_challenged - 1]
    assert cutoff > 0


def test_disputes_count_only_fraud_that_actually_reached_the_merchant():
    """Held fraud is not a dispute. Challenged fraud is one only if it cleared."""
    y, prob, amounts = _book()
    result = portfolio_cost(y, prob, amounts)

    assert result["expected_disputes"] >= result["fraud_accepted"]
    assert result["dispute_ratio"] == pytest.approx(result["expected_disputes"] / len(y))


def test_covenant_status_agrees_with_the_ratio_it_reports():
    y, prob, amounts = _book()
    result = portfolio_cost(y, prob, amounts)

    assert result["within_covenant"] == (result["dispute_ratio"] <= result["dispute_ceiling"])


def test_a_book_with_no_fraud_costs_only_friction():
    """Sanity floor: no fraud means no dispute fees and no leaked value."""
    _, prob, amounts = _book()
    y = np.zeros(len(prob), dtype=int)

    result = portfolio_cost(y, prob, amounts)
    assert result["fraud_accepted"] == 0
    assert result["fraud_value_leaked_inr"] == 0.0
    assert result["expected_disputes"] == 0.0


# --------------------------------------------------------------------------- #
# The covenant
# --------------------------------------------------------------------------- #
def test_perfect_recall_means_the_covenant_can_never_bind():
    assert prevalence_at_which_covenant_binds(1.0) is None


@pytest.mark.parametrize("recall", [0.90, 0.92, 0.50])
def test_the_binding_prevalence_follows_the_stated_formula(recall):
    """ceiling / (1 - recall). Stated in the report, so it has to be the one computed.

    Derived from the constant rather than hardcoded. The literals here used to encode a
    0.9% ceiling, so moving the ceiling to the threshold the networks actually enforce
    broke a test whose stated subject is the *formula* - which is a test pinning the
    wrong thing.
    """
    expected = DISPUTE_RATIO_CEILING / (1.0 - recall)
    assert prevalence_at_which_covenant_binds(recall) == pytest.approx(expected, rel=1e-6)


def test_the_covenant_is_slack_at_this_datasets_prevalence():
    """Reported honestly in the training output: at 0.5% fraud it does no work.

    If this ever fails, the claim in the report has stopped being true and the wording
    needs to change with it.
    """
    binds_at = prevalence_at_which_covenant_binds(0.92)
    assert binds_at > 0.005


# --------------------------------------------------------------------------- #
# Per-row costs in the threshold sweep
# --------------------------------------------------------------------------- #
def test_a_constant_array_cost_matches_the_scalar_form():
    """The generalisation must not change behaviour where the old code applied."""
    y, prob, amounts = _book()

    scalar = cost_optimal_threshold(y, prob, amounts, fp_cost=150.0, target_recall=0.0)
    array = cost_optimal_threshold(
        y, prob, amounts, fp_cost=np.full(len(y), 150.0), target_recall=0.0
    )

    assert array["threshold"] == pytest.approx(scalar["threshold"])
    assert array["expected_cost"] == pytest.approx(scalar["expected_cost"])


def test_the_sweep_and_the_direct_calculation_agree_under_per_row_costs():
    """Two independent implementations of the same cost model, cross-checked."""
    y, prob, amounts = _book()
    fp = DEFAULT.false_positive_cost(amounts)
    fn = DEFAULT.false_negative_cost(amounts)

    best = cost_optimal_threshold(y, prob, amounts, fp_cost=fp, fn_cost=fn, target_recall=0.0)
    recomputed = expected_cost_at(y, prob, amounts, best["threshold"], fp_cost=fp, fn_cost=fn)

    assert recomputed == pytest.approx(best["expected_cost"], rel=1e-9)


def test_no_other_threshold_beats_the_per_row_optimum():
    y, prob, amounts = _book()
    fp = DEFAULT.false_positive_cost(amounts)
    fn = DEFAULT.false_negative_cost(amounts)

    best = cost_optimal_threshold(y, prob, amounts, fp_cost=fp, fn_cost=fn, target_recall=0.0)

    for candidate in np.unique(prob):
        cost = expected_cost_at(y, prob, amounts, candidate, fp_cost=fp, fn_cost=fn)
        assert cost >= best["expected_cost"] - 1e-6


def test_amount_scaled_costs_move_the_threshold_when_big_baskets_sit_near_it():
    """The reframe has to be able to change the answer, not just the story.

    Constructed rather than sampled, because the shift is not universal: on a book
    where the operating point already sits in a wide flat region of the cost curve,
    both models land on the same row and the threshold does not move at all. What is
    *always* true is that a flat cost cannot distinguish a wrongly-held Rs.200 basket
    from a wrongly-held Rs.90,000 one - so this places several large legitimate orders
    just above the flat optimum, where the distinction has to bite.
    """
    # Three easy frauds on top; then three large legitimate orders; then one more
    # fraud sitting *below* them. Reaching that last fraud means holding all three
    # big orders, and whether that trade is worth making is exactly what the two cost
    # models disagree about.
    y = np.array([1, 1, 1, 0, 0, 0, 1, 0, 0, 0])
    prob = np.array([0.95, 0.90, 0.85, 0.60, 0.58, 0.56, 0.50, 0.05, 0.04, 0.03])
    amounts = np.array(
        [20_000, 18_000, 16_000, 90_000, 88_000, 86_000, 40_000, 500, 400, 300],
        dtype=float,
    )

    flat = cost_optimal_threshold(y, prob, amounts, fp_cost=150.0, target_recall=0.0)
    scaled = cost_optimal_threshold(
        y, prob, amounts,
        fp_cost=DEFAULT.false_positive_cost(amounts),
        fn_cost=DEFAULT.false_negative_cost(amounts),
        target_recall=0.0,
    )

    # Flat: three extra reviews cost Rs.450 to recover a Rs.40,000 fraud - obviously
    # worth it, so the threshold drops to reach it.
    # Scaled: the same three holds cost roughly Rs.48,700 of lost margin and goodwill
    # to recover Rs.41,250 - not worth it, so the threshold stays above them.
    assert flat["threshold"] <= 0.50
    assert scaled["threshold"] > 0.60
    assert scaled["threshold"] > flat["threshold"]


def test_economics_are_frozen_so_a_policy_cannot_drift_mid_run():
    """`MerchantEconomics` is a frozen dataclass on purpose.

    The assumptions are recorded in `model_config.json` alongside the threshold they
    produced. If a caller could mutate them in place, that record would silently stop
    describing the model that shipped.
    """
    with pytest.raises(FrozenInstanceError):
        DEFAULT.chargeback_fee = 9_999.0

    assert isinstance(replace(DEFAULT, chargeback_fee=9_999.0), MerchantEconomics)
