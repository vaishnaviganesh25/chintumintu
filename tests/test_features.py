"""Feature engineering - the surface where train/serve skew would live.

`engineer_features` is called from three places: the training run over 100,000 rows,
the explainability module, and the API scoring one live transaction. If those three
ever disagree about what a column means, nothing raises - the model simply starts
scoring production traffic against a slightly different feature space than it was
fitted on, and the only symptom is a drift in the alert rate that looks like the
world changing rather than a bug. These tests exist to make that failure loud.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from conftest import raw_txn
from train_model import (
    IDENTIFIER_COLUMNS,
    KNOWN_HANDLES,
    LEAKAGE_COLUMNS,
    MICRO_PAYMENT_CEILING,
    engineer_features,
    split_feature_types,
)


# --------------------------------------------------------------------------- #
# Purity and leakage
# --------------------------------------------------------------------------- #
def test_label_and_leakage_columns_never_reach_the_matrix(single_row):
    """The target and `fraud_pattern` must be structurally impossible to leak.

    `engineer_features` builds a fresh frame rather than dropping columns from the
    input, so the guarantee holds even when the caller passes a labelled frame - as
    the training run does.
    """
    labelled = single_row.assign(is_fraud=1, fraud_pattern="odd_hour_phishing")
    features = engineer_features(labelled)

    forbidden = {"is_fraud", *LEAKAGE_COLUMNS, *IDENTIFIER_COLUMNS}
    assert forbidden.isdisjoint(features.columns)


def test_does_not_mutate_its_input(single_row):
    before = single_row.copy(deep=True)
    engineer_features(single_row)
    pd.testing.assert_frame_equal(single_row, before)


def test_is_deterministic(single_row):
    pd.testing.assert_frame_equal(engineer_features(single_row), engineer_features(single_row))


# --------------------------------------------------------------------------- #
# Train/serve skew
# --------------------------------------------------------------------------- #
def test_single_row_yields_the_same_columns_as_a_batch(single_row):
    """One row through the API must produce the same feature space as the training batch.

    This is the specific regression that would silently break scoring: add a feature
    that only materialises when the frame has more than one row, and the API keeps
    working right up until the preprocessor rejects the column count.
    """
    batch = pd.DataFrame([raw_txn(), raw_txn(amount=980.0), raw_txn(amount=15_000.0)])

    single_cols = list(engineer_features(single_row).columns)
    batch_cols = list(engineer_features(batch).columns)

    assert single_cols == batch_cols


def test_row_features_are_independent_of_batch_position(single_row):
    """A transaction scored alone and inside a batch agrees - given the same neighbours.

    Two families of feature legitimately depend on other rows, and the test has to
    hold both constant to mean anything:

    * lag features look at the same *sender's* previous payment;
    * graph features count the same *receiver's* recent payers.

    So the row under test uses a sender and a receiver that appear nowhere else in the
    batch. Sharing either would make the two results differ by design - which is the
    point of those features, not a bug in them.
    """
    target = raw_txn(sender="solo.payer@oksbi", receiver="solo.shop@paytm", amount=7400.0)
    alone = engineer_features(pd.DataFrame([target])).iloc[0]

    crowd = pd.DataFrame([
        raw_txn(sender="other.a@ybl", receiver="other.shop.a@paytm"),
        target,
        raw_txn(sender="other.b@ybl", receiver="other.shop.b@paytm"),
    ])
    in_batch = engineer_features(crowd).iloc[1]

    pd.testing.assert_series_equal(alone, in_batch, check_names=False)


def test_a_shared_receiver_is_exactly_what_the_graph_features_should_notice():
    """The complement of the test above, so the isolation there is not mistaken for
    a claim that batch position never matters.

    A payment into an account two other people have just paid *must* score differently
    from the same payment into a quiet account. That is the mule signal.
    """
    target = raw_txn(sender="third.payer@oksbi", receiver="mule@paytm", amount=7400.0)

    alone = engineer_features(pd.DataFrame([target])).iloc[0]
    crowded = engineer_features(pd.DataFrame([
        raw_txn(sender="first@ybl", receiver="mule@paytm"),
        raw_txn(sender="second@axl", receiver="mule@paytm"),
        target,
    ])).iloc[2]

    assert alone["receiver_fanin_10m"] == 1
    assert crowded["receiver_fanin_10m"] == 3
    assert crowded["receiver_is_hub"] == 1


def test_type_partition_covers_every_column(single_row):
    """Every engineered column lands in exactly one of the preprocessor's three groups.

    A column that falls through all three is dropped by `remainder="drop"` without
    complaint, which is how a feature gets engineered and then quietly never used.
    """
    features = engineer_features(single_row)
    numeric, binary, categorical = split_feature_types(features)

    assert len(numeric) + len(binary) + len(categorical) == features.shape[1]
    assert set(numeric) | set(binary) | set(categorical) == set(features.columns)
    assert not (set(numeric) & set(binary))
    assert not (set(binary) & set(categorical))


# --------------------------------------------------------------------------- #
# The Rs.1 test - the sequence the lag features exist for
# --------------------------------------------------------------------------- #
def test_lag_features_reconstruct_the_rupee_one_pair(rupee_one_pair):
    features = engineer_features(rupee_one_pair)
    probe, drain = features.iloc[0], features.iloc[1]

    # The probe has no predecessor for this sender, so the ratio is undefined rather
    # than a number. It used to be `amount / (0 + 1)` - the transaction amount itself,
    # which is the largest value the feature can take and a terrible default for a
    # first-time payer.
    assert probe["prev_amount"] == 0.0
    assert probe["same_receiver_as_prev"] == 0
    assert pd.isna(probe["prev_amount_ratio"])
    # Note this row is *not* `is_first_txn`: it carries a recorded 7,200s gap from a
    # payment outside the frame. The two flags answer different questions - one about
    # the gap column, one about whether a predecessor row is present to compare against.
    assert probe["is_first_txn"] == 0

    # The drain sees the Rs.1 that came 43 seconds earlier, to the same receiver -
    # a genuine 62,000x jump, and now the only row of the pair reporting one.
    assert drain["prev_amount"] == pytest.approx(1.0)
    assert drain["same_receiver_as_prev"] == 1
    assert drain["is_rapid_txn"] == 1
    assert drain["prev_amount_ratio"] == pytest.approx(62000.0)


def test_a_different_receiver_breaks_the_pair(rupee_one_pair):
    """`same_receiver_as_prev` must key on the receiver, not merely on adjacency."""
    diverted = rupee_one_pair.copy()
    diverted.loc[1, "receiver_vpa"] = "someone.else@ybl"

    assert engineer_features(diverted).iloc[1]["same_receiver_as_prev"] == 0


def test_lags_do_not_cross_senders():
    """One sender's history must never leak into another's - a cross-account bug.

    Ordering the frame so two senders interleave is the case a naive `shift(1)` on
    the whole frame would get wrong.
    """
    base = datetime(2026, 7, 20, 12, 0)
    frame = pd.DataFrame([
        raw_txn(sender="a@ybl", receiver="shop.one@paytm", amount=1.0, timestamp=base),
        raw_txn(sender="b@ybl", receiver="shop.two@paytm", amount=500.0,
                timestamp=base + timedelta(seconds=5)),
        raw_txn(sender="a@ybl", receiver="shop.one@paytm", amount=90_000.0,
                timestamp=base + timedelta(seconds=10)),
    ])
    features = engineer_features(frame)

    # b's first row has no predecessor of its own, despite sitting after one of a's.
    assert features.iloc[1]["prev_amount"] == 0.0
    assert features.iloc[1]["same_receiver_as_prev"] == 0
    # a's second row correctly reaches back past b's row.
    assert features.iloc[2]["prev_amount"] == pytest.approx(1.0)
    assert features.iloc[2]["same_receiver_as_prev"] == 1


# --------------------------------------------------------------------------- #
# Boundaries that carry meaning
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, 0), (1, 1), (2, 1), (3, 1), (4, 0), (12, 0), (23, 0)],
)
def test_night_flag_covers_exactly_one_to_four(hour, expected):
    """`is_night_txn` is the odd-hour phishing signature and its edges are the whole point.

    01:00 through 03:59 inclusive - so 04:00 is daytime. Off-by-one here would move
    a scam signature by an hour and nothing else would notice.
    """
    row = pd.DataFrame([raw_txn(timestamp=datetime(2026, 7, 15, hour, 30))])
    assert engineer_features(row).iloc[0]["is_night_txn"] == expected


def test_a_first_payment_has_no_spending_jump_to_report():
    """The defect this test exists for.

    `amount / (prev_amount + 1)` made a first-time payer's ordinary payment arrive as a
    jump equal to the amount itself - Rs.35,334 read as a 35,334x escalation. The
    report's own worked false positive is that row. `is_first_txn` already marks these,
    so the ratio is left missing and imputed.
    """
    row = pd.DataFrame([raw_txn(amount=35_334.0, gap_sec=-1.0)])
    out = engineer_features(row).iloc[0]

    assert out["is_first_txn"] == 1
    assert pd.isna(out["prev_amount_ratio"])


def test_first_transaction_is_flagged_and_the_gap_is_left_missing():
    """A `-1` gap means "no prior activity", not "minus one second".

    Feeding -1 through as a magnitude would put a sender's first payment at the far
    end of the velocity axis. It becomes NaN plus an explicit flag, so the imputer
    fills it and the model can tell imputed apart from genuinely small.
    """
    row = pd.DataFrame([raw_txn(gap_sec=-1.0)])
    out = engineer_features(row).iloc[0]

    assert out["is_first_txn"] == 1
    assert pd.isna(out["time_since_last_txn_sec"])
    assert pd.isna(out["log_time_since_last"])
    assert out["is_rapid_txn"] == 0


def test_unknown_bank_handle_collapses_to_other():
    """An unseen PSP handle must not reach the one-hot encoder as a novel category.

    New handles appear in the real UPI ecosystem constantly; the model should treat
    one it has never seen as unremarkable rather than fail to score the payment.
    """
    row = pd.DataFrame([raw_txn(sender="someone@brandnewpsp", receiver="shop@alsonew")])
    out = engineer_features(row).iloc[0]

    assert out["sender_bank_handle"] == "other"
    assert out["receiver_bank_handle"] == "other"


@pytest.mark.parametrize("handle", sorted(KNOWN_HANDLES)[:5])
def test_known_handles_survive_intact(handle):
    row = pd.DataFrame([raw_txn(sender=f"person@{handle}")])
    assert engineer_features(row).iloc[0]["sender_bank_handle"] == handle


def test_merchant_and_keyword_signals_fire():
    qr = pd.DataFrame([raw_txn(receiver="q53337100@icici")])
    assert engineer_features(qr).iloc[0]["receiver_is_merchant_like"] == 1

    lure = pd.DataFrame([raw_txn(receiver="kyc.update@paytm")])
    out = engineer_features(lure).iloc[0]
    assert out["receiver_has_suspicious_keyword"] == 1
    assert out["receiver_is_merchant_like"] == 0


# --------------------------------------------------------------------------- #
# Properties - things that must hold for every input, not just the ones we chose
# --------------------------------------------------------------------------- #
@settings(max_examples=120, deadline=None)
@given(amount=st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False))
def test_log_amount_is_monotone_and_finite(amount):
    """`log_amount` must preserve ordering, or the model's amount axis is scrambled."""
    smaller = engineer_features(pd.DataFrame([raw_txn(amount=amount)])).iloc[0]
    larger = engineer_features(pd.DataFrame([raw_txn(amount=amount * 2)])).iloc[0]

    assert np.isfinite(smaller["log_amount"])
    assert larger["log_amount"] > smaller["log_amount"]


@settings(max_examples=120, deadline=None)
@given(amount=st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False))
def test_micro_payment_flag_agrees_with_the_ceiling(amount):
    out = engineer_features(pd.DataFrame([raw_txn(amount=amount)])).iloc[0]
    assert out["is_micro_payment"] == int(amount <= MICRO_PAYMENT_CEILING)


@settings(max_examples=150, deadline=None)
@given(
    amount=st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False),
    age=st.integers(min_value=0, max_value=1000),
    gap=st.floats(min_value=-1, max_value=86_400, allow_nan=False),
    hour=st.integers(min_value=0, max_value=23),
)
def test_binary_columns_are_always_zero_or_one(amount, age, gap, hour):
    """Every flag stays a clean 0/1 across the whole input space.

    A binary column that silently produces NaN passes straight through the
    preprocessor's passthrough branch and reaches the classifier as a missing value.
    """
    row = pd.DataFrame([raw_txn(
        amount=amount, age_days=age, gap_sec=gap,
        timestamp=datetime(2026, 7, 15, hour, 30),
    )])
    features = engineer_features(row)
    _, binary, _ = split_feature_types(features)

    for column in binary:
        value = features.iloc[0][column]
        assert value in (0, 1), f"{column} produced {value!r}"


@settings(max_examples=80, deadline=None)
@given(
    age=st.integers(min_value=0, max_value=1000),
    gap=st.floats(min_value=0, max_value=86_400, allow_nan=False),
)
def test_no_unexpected_nans_outside_the_documented_ones(age, gap):
    """Only the lookback columns may be missing, and only with no predecessor.

    `prev_amount_ratio` belongs on this list: a sender's first payment has nothing to
    compare against, and the imputer fills it exactly as it does the velocity columns.
    Substituting a number there is what produced the false positive in the report.
    """
    row = pd.DataFrame([raw_txn(age_days=age, gap_sec=gap)])
    features = engineer_features(row)

    missing = {c for c in features.columns if features[c].isna().any()}
    assert missing <= {"time_since_last_txn_sec", "log_time_since_last", "prev_amount_ratio"}


@settings(max_examples=60, deadline=None)
@given(local=st.text(alphabet=st.characters(whitelist_categories=("Ll", "Nd")), min_size=1, max_size=30))
def test_arbitrary_vpa_local_parts_do_not_crash_the_encoder(local):
    """A VPA local part is user-controlled input and must never take the scorer down."""
    assume("@" not in local)
    row = pd.DataFrame([raw_txn(receiver=f"{local}@ybl")])
    out = engineer_features(row).iloc[0]

    assert 0.0 <= out["receiver_digit_ratio"] <= 1.0
    assert out["receiver_local_len"] == len(local)
