"""The degradation ladder.

A fallback that has never executed is a comment, not a fallback. Every rung here is
driven directly, including the bottom two that a healthy system never reaches.

The property that matters most is the one about honesty: a degraded verdict has to
say so. A silent fallback is worse than a loud failure, because the alert rate moves
and everyone assumes the world changed rather than the engine.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from degradation import (
    MICRO_PAYMENT_INR,
    RULE_LARGE_AMOUNT_INR,
    RULE_NEW_RECEIVER_DAYS,
    VALUE_FLOOR_INR,
    Rung,
    fail_safe_verdict,
    fallback_verdict,
    rule_engine_verdict,
    value_floor_verdict,
)

ACTIONS = {"ACCEPT", "STEP_UP", "HOLD"}


# --------------------------------------------------------------------------- #
# Rung 1 - the rule engine
# --------------------------------------------------------------------------- #
def test_a_new_receiver_and_a_large_amount_is_held():
    """The rule Module 1 measures at 62.4% precision - the reason this rung exists."""
    verdict = rule_engine_verdict(48_500.0, receiver_vpa_age_days=0)

    assert verdict.action == "HOLD"
    assert verdict.rung is Rung.RULES
    assert verdict.reasons


def test_an_established_receiver_is_accepted_even_at_high_value():
    """Age alone is 7.1% precise on this data; value alone would bury the queue.

    It is the *combination* that carries the precision, so a large payment to a
    long-standing account must pass.
    """
    verdict = rule_engine_verdict(90_000.0, receiver_vpa_age_days=600)
    assert verdict.action == "ACCEPT"


def test_a_new_receiver_at_moderate_value_is_challenged_not_held():
    """The middle rung of the middle rung: a cheap challenge covers a coarse decision."""
    verdict = rule_engine_verdict(9_000.0, receiver_vpa_age_days=3)
    assert verdict.action == "STEP_UP"


def test_a_micro_payment_to_a_new_receiver_is_still_accepted():
    """The customer-experience guardrail survives the outage.

    Declining someone's Rs.40 chai because the model is down protects against a risk
    that is not there and is visible to every customer immediately.
    """
    verdict = rule_engine_verdict(40.0, receiver_vpa_age_days=0)
    assert verdict.action == "ACCEPT"


@pytest.mark.parametrize(
    ("age", "expected_flagged"),
    [(0, True), (RULE_NEW_RECEIVER_DAYS, True), (RULE_NEW_RECEIVER_DAYS + 1, False)],
)
def test_the_age_boundary_is_inclusive(age, expected_flagged):
    verdict = rule_engine_verdict(RULE_LARGE_AMOUNT_INR, receiver_vpa_age_days=age)
    assert (verdict.action == "HOLD") is expected_flagged


def test_an_unknown_receiver_age_is_not_treated_as_new():
    """A missing field must not manufacture an alert.

    The API defaults absent ages to an established account precisely so a caller who
    cannot supply one never has a payment held for it.
    """
    assert rule_engine_verdict(90_000.0, receiver_vpa_age_days=None).action == "ACCEPT"


def test_the_odd_hour_signal_survives_without_the_model():
    """Hour-of-day costs nothing to compute and carries real signal, so it stays."""
    verdict = rule_engine_verdict(48_500.0, receiver_vpa_age_days=0,
                                  timestamp=datetime(2026, 8, 23, 3, 20))
    assert any("1-4 AM" in reason for reason in verdict.reasons)


# --------------------------------------------------------------------------- #
# Rungs 2 and 3
# --------------------------------------------------------------------------- #
def test_the_value_floor_holds_large_payments_and_passes_small_ones():
    assert value_floor_verdict(VALUE_FLOOR_INR + 1).action == "HOLD"
    assert value_floor_verdict(VALUE_FLOOR_INR - 1).action == "ACCEPT"


def test_the_last_rung_is_not_accept_everything():
    """Failing open on a large payment because an artifact is missing is a real loss."""
    assert fail_safe_verdict(90_000.0).action == "HOLD"


def test_the_last_rung_is_not_decline_everything_either():
    """Nor is failing closed on micro-payments the safe choice."""
    assert fail_safe_verdict(40.0).action == "ACCEPT"


def test_the_ladder_descends_when_rules_are_unavailable():
    verdict = fallback_verdict(48_500.0, receiver_vpa_age_days=0, rules_available=False)
    assert verdict.rung is Rung.VALUE_FLOOR


def test_a_broken_rule_engine_descends_rather_than_raising(monkeypatch):
    """The ladder has to survive its own rungs failing, not just the model failing."""
    import degradation

    monkeypatch.setattr(degradation, "rule_engine_verdict",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    verdict = degradation.fallback_verdict(48_500.0, receiver_vpa_age_days=0)

    assert verdict.rung is Rung.VALUE_FLOOR
    assert verdict.action == "HOLD"


# --------------------------------------------------------------------------- #
# Honesty
# --------------------------------------------------------------------------- #
@settings(max_examples=200, deadline=None)
@given(
    amount=st.floats(min_value=1.0, max_value=1_000_000.0),
    age=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
    rules_available=st.booleans(),
)
def test_every_fallback_verdict_admits_it_is_one(amount, age, rules_available):
    """No rung below the model may present itself as a normal decision."""
    verdict = fallback_verdict(amount, age, rules_available=rules_available)

    assert verdict.degraded is True
    assert verdict.rung is not Rung.FULL
    assert verdict.action in ACTIONS


@settings(max_examples=200, deadline=None)
@given(
    amount=st.floats(min_value=1.0, max_value=1_000_000.0),
    age=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
)
def test_no_fallback_ever_invents_a_probability(amount, age):
    """A made-up score would flow into the cost model and the ledger and be read, months
    later, as though the model had produced it. None is the honest value."""
    assert fallback_verdict(amount, age).probability is None


@settings(max_examples=150, deadline=None)
@given(
    amount=st.floats(min_value=1.0, max_value=1_000_000.0),
    age=st.one_of(st.none(), st.integers(min_value=0, max_value=1000)),
)
def test_every_explanation_names_an_action_and_the_degradation(amount, age):
    """An operator reading one line has to learn both what to do and how much to trust it."""
    verdict = fallback_verdict(amount, age)
    text = verdict.explanation.lower()

    assert any(word in text for word in ("accept", "challenge", "hold"))
    assert any(word in text for word in ("unavailable", "is down", "coarser"))


@settings(max_examples=150, deadline=None)
@given(amount=st.floats(min_value=1.0, max_value=1_000_000.0))
def test_a_held_payment_always_carries_a_reason(amount):
    """A hold nobody can explain is a support ticket, on every rung."""
    for verdict in (
        rule_engine_verdict(amount, receiver_vpa_age_days=0),
        value_floor_verdict(amount),
        fail_safe_verdict(amount),
    ):
        if verdict.action == "HOLD":
            assert verdict.reasons


def test_the_ladder_is_ordered_so_lower_is_worse():
    """Comparisons read the way operators think, and the report depends on it."""
    assert Rung.FULL < Rung.RULES < Rung.VALUE_FLOOR < Rung.FAIL_SAFE
    assert all(rung.label for rung in Rung)


@settings(max_examples=100, deadline=None)
@given(amount=st.floats(min_value=MICRO_PAYMENT_INR + 0.01, max_value=1_000_000.0))
def test_the_bottom_rung_never_silently_clears_a_non_trivial_payment(amount):
    """The invariant that makes total failure survivable rather than expensive."""
    assert fail_safe_verdict(amount).action == "HOLD"
