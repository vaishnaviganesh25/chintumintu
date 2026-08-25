"""Relational features over the payment graph.

One property here matters more than the rest: **no window may read a row that arrives
later**. A graph feature that peeks forward inflates every offline metric and cannot
be reproduced at serving time, and nothing about it raises - the model simply looks
better than it is, right up until production. Several tests below exist solely to
make that failure loud.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from graph_features import (
    GRAPH_FEATURES,
    HUB_FANIN,
    LONG_WINDOW_S,
    SHORT_WINDOW_S,
    compute_graph_features,
    describe_ring,
)

BASE = datetime(2026, 7, 18, 0, 15, 0)


def txn(sender: str, receiver: str, offset_s: int, amount: float = 40_000.0) -> dict:
    return {
        "timestamp": pd.Timestamp(BASE + timedelta(seconds=offset_s)),
        "sender_vpa": sender,
        "receiver_vpa": receiver,
        "amount": amount,
    }


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# The star
# --------------------------------------------------------------------------- #
def test_fan_in_counts_distinct_payers_into_one_account():
    """The mule ring, reduced to its essentials: three victims, one collecting account."""
    g = compute_graph_features(frame([
        txn("victim.a@ybl", "mule@paytm", 0),
        txn("victim.b@oksbi", "mule@paytm", 60),
        txn("victim.c@axl", "mule@paytm", 120),
    ]))

    assert list(g["receiver_fanin_10m"]) == [1, 2, 3]


def test_fan_in_grows_as_the_ring_assembles_and_never_earlier():
    """The honesty property, stated as the demo tells it.

    Payment one into a mule sees a fan-in of one and looks entirely ordinary. The hub
    flag fires on payment five, when the third distinct victim arrives - not before,
    because the earlier rows genuinely could not have known.
    """
    g = compute_graph_features(frame([
        txn("victim.a@ybl", "mule@paytm", 0),
        txn("victim.a@ybl", "mule@paytm", 148),      # same payer again - not new fan-in
        txn("victim.b@oksbi", "mule@paytm", 263),
        txn("victim.b@oksbi", "mule@paytm", 422),
        txn("victim.c@axl", "mule@paytm", 531),
    ]))

    assert list(g["receiver_fanin_10m"]) == [1, 1, 2, 2, 3]
    assert list(g["receiver_is_hub"]) == [0, 0, 0, 0, 1]


def test_one_payer_paying_repeatedly_is_not_a_ring():
    """Distinct payers, not payment count. Ten payments from one person is a person."""
    g = compute_graph_features(frame([
        txn("regular@ybl", "shop@paytm", i * 30) for i in range(10)
    ]))

    assert set(g["receiver_fanin_10m"]) == {1}
    assert g["receiver_is_hub"].sum() == 0
    # Volume still registers, it just is not fan-in.
    assert g["receiver_txn_count_10m"].iloc[-1] == 10


def test_fan_out_is_the_mirror_pattern():
    """A compromised account spraying money at many receivers is a different shape."""
    g = compute_graph_features(frame([
        txn("compromised@ybl", f"receiver{i}@paytm", i * 60) for i in range(5)
    ]))

    assert list(g["sender_fanout_1h"]) == [1, 2, 3, 4, 5]
    # ...and it must not read as fan-in, which is a different scam entirely.
    assert set(g["receiver_fanin_10m"]) == {1}


def test_different_receivers_do_not_pool():
    """Two unrelated mules must not add up into one phantom ring."""
    g = compute_graph_features(frame([
        txn("a@ybl", "mule.one@paytm", 0),
        txn("b@oksbi", "mule.two@paytm", 10),
        txn("c@axl", "mule.one@paytm", 20),
    ]))

    assert list(g["receiver_fanin_10m"]) == [1, 1, 2]


# --------------------------------------------------------------------------- #
# Strictly backward-looking
# --------------------------------------------------------------------------- #
def test_a_later_payment_cannot_change_an_earlier_one():
    """The single most important property in this file.

    Truncating the frame must leave every surviving row's features untouched. If it
    does not, the window is reading forward and every offline number is fiction.
    """
    rows = [
        txn("victim.a@ybl", "mule@paytm", 0),
        txn("victim.b@oksbi", "mule@paytm", 60),
        txn("victim.c@axl", "mule@paytm", 120),
        txn("victim.d@ibl", "mule@paytm", 180),
    ]

    full = compute_graph_features(frame(rows))
    prefix = compute_graph_features(frame(rows[:2]))

    pd.testing.assert_frame_equal(full.iloc[:2], prefix)


@settings(max_examples=60, deadline=None)
@given(cut=st.integers(min_value=1, max_value=11))
def test_every_prefix_of_a_stream_agrees_with_the_whole(cut):
    """Generalises the above to every truncation point, not just one."""
    rows = [
        txn(f"victim.{i % 4}@ybl", f"mule.{i % 2}@paytm", i * 45, 10_000.0 + i)
        for i in range(12)
    ]

    full = compute_graph_features(frame(rows))
    prefix = compute_graph_features(frame(rows[:cut]))

    pd.testing.assert_frame_equal(full.iloc[:cut], prefix)


def test_row_order_within_the_frame_does_not_matter():
    """The sweep sorts internally, so a caller handing rows in any order gets the
    same answer keyed to their own index. Training sorts chronologically; the API
    merges two history indexes and cannot guarantee it."""
    rows = [
        txn("a@ybl", "mule@paytm", 0),
        txn("b@oksbi", "mule@paytm", 60),
        txn("c@axl", "mule@paytm", 120),
    ]
    ordered = compute_graph_features(frame(rows))
    shuffled_rows = [rows[2], rows[0], rows[1]]
    shuffled = compute_graph_features(frame(shuffled_rows))

    # Row 'c' is index 2 in one frame and index 0 in the other, but it is the same
    # payment and must carry the same fan-in.
    assert ordered["receiver_fanin_10m"].iloc[2] == shuffled["receiver_fanin_10m"].iloc[0]
    assert ordered["receiver_fanin_10m"].iloc[0] == shuffled["receiver_fanin_10m"].iloc[1]


# --------------------------------------------------------------------------- #
# Window edges
# --------------------------------------------------------------------------- #
def test_the_window_is_closed_at_both_ends():
    """A payment exactly `window` old is inside; one second older is out.

    Worth pinning because an off-by-one here silently shrinks every window and the
    only symptom is slightly weaker features.
    """
    inside = compute_graph_features(frame([
        txn("a@ybl", "mule@paytm", 0),
        txn("b@oksbi", "mule@paytm", SHORT_WINDOW_S),
    ]))
    assert inside["receiver_fanin_10m"].iloc[1] == 2

    outside = compute_graph_features(frame([
        txn("a@ybl", "mule@paytm", 0),
        txn("b@oksbi", "mule@paytm", SHORT_WINDOW_S + 1),
    ]))
    assert outside["receiver_fanin_10m"].iloc[1] == 1


def test_payments_sharing_a_timestamp_all_count():
    """Bursts generated to the second are exactly the case worth counting, not dropping."""
    g = compute_graph_features(frame([
        txn("a@ybl", "mule@paytm", 0),
        txn("b@oksbi", "mule@paytm", 0),
        txn("c@axl", "mule@paytm", 0),
    ]))

    assert g["receiver_fanin_10m"].iloc[-1] == 3


def test_the_long_window_sees_what_the_short_one_has_forgotten():
    g = compute_graph_features(frame([
        txn("a@ybl", "mule@paytm", 0),
        txn("b@oksbi", "mule@paytm", SHORT_WINDOW_S + 120),
    ]))

    assert g["receiver_fanin_10m"].iloc[1] == 1
    assert g["receiver_fanin_1h"].iloc[1] == 2


def test_an_old_payment_leaves_the_window_entirely():
    g = compute_graph_features(frame([
        txn("a@ybl", "mule@paytm", 0),
        txn("b@oksbi", "mule@paytm", LONG_WINDOW_S + 60),
    ]))

    assert g["receiver_fanin_1h"].iloc[1] == 1
    assert g["receiver_txn_count_10m"].iloc[1] == 1


# --------------------------------------------------------------------------- #
# Amounts and shape
# --------------------------------------------------------------------------- #
def test_collected_volume_accumulates_then_decays():
    g = compute_graph_features(frame([
        txn("a@ybl", "mule@paytm", 0, 10_000.0),
        txn("b@oksbi", "mule@paytm", 60, 25_000.0),
        txn("c@axl", "mule@paytm", SHORT_WINDOW_S + 120, 5_000.0),
    ]))

    assert g["receiver_amount_10m"].iloc[1] == pytest.approx(35_000.0)
    # The first two have aged out by the third.
    assert g["receiver_amount_10m"].iloc[2] == pytest.approx(5_000.0)


def test_a_single_row_is_its_own_neighbourhood():
    """The API's cold-start case: no history at all must not divide by zero or NaN."""
    g = compute_graph_features(frame([txn("a@ybl", "shop@paytm", 0)]))

    assert g["receiver_fanin_10m"].iloc[0] == 1
    assert g["receiver_txn_count_10m"].iloc[0] == 1
    assert g["receiver_is_hub"].iloc[0] == 0
    assert not g.isna().any().any()


def test_an_empty_frame_yields_an_empty_result_with_the_right_columns():
    g = compute_graph_features(pd.DataFrame(
        columns=["timestamp", "sender_vpa", "receiver_vpa", "amount"]
    ))
    assert list(g.columns) == GRAPH_FEATURES
    assert len(g) == 0


def test_a_frame_without_identity_columns_still_returns_the_column_set():
    """`engineer_features` may be handed a frame with the identifiers already dropped.

    Emitting zeros keeps the feature space stable; raising would break the caller for
    no benefit, and omitting the columns would be train/serve skew by another name.
    """
    g = compute_graph_features(pd.DataFrame({"timestamp": [pd.Timestamp(BASE)], "amount": [100.0]}))

    assert list(g.columns) == GRAPH_FEATURES
    assert (g.iloc[0] == 0).all()


@settings(max_examples=80, deadline=None)
@given(
    n_senders=st.integers(min_value=1, max_value=6),
    n_rows=st.integers(min_value=1, max_value=20),
)
def test_fan_in_never_exceeds_the_payers_present(n_senders, n_rows):
    """A distinct count cannot exceed the number of distinct things, however the
    window slides. Cheap invariant, catches a broken multiset immediately."""
    rows = [txn(f"s{i % n_senders}@ybl", "mule@paytm", i * 20) for i in range(n_rows)]
    g = compute_graph_features(frame(rows))

    assert g["receiver_fanin_10m"].max() <= n_senders
    assert (g["receiver_fanin_10m"] >= 1).all()
    assert (g["receiver_fanin_10m"] <= g["receiver_txn_count_10m"]).all()


def test_the_hub_threshold_is_the_flag_it_claims_to_be():
    rows = [txn(f"victim{i}@ybl", "mule@paytm", i * 30) for i in range(HUB_FANIN + 2)]
    g = compute_graph_features(frame(rows))

    assert (g["receiver_is_hub"] == (g["receiver_fanin_10m"] >= HUB_FANIN).astype(int)).all()


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #
@pytest.mark.slow
def test_the_sweep_stays_linear_enough_to_ship():
    """100,000 rows must not double the training run.

    The naive implementation - one window scan per row - is quadratic and would add
    minutes. This is the guard that stops it regressing back to that.
    """
    rng = np.random.default_rng(11)
    n = 100_000
    df = pd.DataFrame({
        "timestamp": pd.Timestamp(BASE) + pd.to_timedelta(np.sort(rng.integers(0, 2_592_000, n)), unit="s"),
        "sender_vpa": [f"s{i}@ybl" for i in rng.integers(0, 5_000, n)],
        "receiver_vpa": [f"r{i}@paytm" for i in rng.integers(0, 4_000, n)],
        "amount": rng.uniform(10, 90_000, n),
    })

    start = time.perf_counter()
    compute_graph_features(df)
    assert time.perf_counter() - start < 15.0


# --------------------------------------------------------------------------- #
# Ring description, for the dashboard
# --------------------------------------------------------------------------- #
def _ring_frame() -> pd.DataFrame:
    rows = [
        txn("victim.a@ybl", "mule@paytm", 0, 40_718.0),
        txn("victim.a@ybl", "mule@paytm", 148, 74_966.0),
        txn("victim.b@oksbi", "mule@paytm", 263, 77_763.0),
    ]
    df = frame(rows)
    df["ring_id"] = "ring_mule_0000"
    df["fraud_pattern"] = "new_vpa_velocity"
    df["receiver_vpa_age_days"] = 0
    return df


def test_describe_ring_returns_the_star_the_dashboard_draws():
    ring = describe_ring(_ring_frame(), "ring_mule_0000")

    assert ring["fanin"] == 2
    assert ring["receivers"] == ["mule@paytm"]
    assert ring["total_amount"] == pytest.approx(193_447.0)
    assert ring["window_seconds"] == 263
    assert len(ring["edges"]) == 3


def test_ring_edges_carry_their_offset_so_the_view_can_animate_in_order():
    ring = describe_ring(_ring_frame(), "ring_mule_0000")
    offsets = [e["offset_seconds"] for e in ring["edges"]]

    assert offsets == sorted(offsets)
    assert offsets[0] == 0


def test_an_unknown_ring_raises_rather_than_returning_an_empty_star():
    with pytest.raises(KeyError):
        describe_ring(_ring_frame(), "ring_does_not_exist")
