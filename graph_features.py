"""FinGuard Module 8 - relational features over the payment graph.

The `new_vpa_velocity` scam is a star: three victims paying one account created that
morning, inside a few minutes. Until now the model could only ever see it side-on -
one row at a time, inferring the ring from account age, amount and the gap since the
sender's last payment. Those are proxies for the structure, not the structure.

This module computes the structure directly. Every feature answers a question about
the *neighbourhood* a payment sits in rather than about the payment itself:

    How many different people have paid this account in the last ten minutes?
    How much has it collected?
    How many different accounts has this payer sent to in the last hour?

Three properties make these safe to ship:

**Strictly backward-looking.** Every window is `[t - w, t]`, closed at the current
payment. Nothing reads a row that arrives later, so a feature computed during training
is the same feature the API can compute at serving time with only past data in hand.
This is the property that makes graph features honest; get it wrong and the model
learns from the future and the offline metrics become fiction.

**Linear, not quadratic.** A two-pointer sweep per account with a running multiset,
so 100,000 rows costs one pass rather than one window scan per row. The training run
must not double because of this file.

**Identical alone and in a batch.** The API scores one payment against a short history
of that account's recent traffic; training scores 100,000 rows at once. Both paths go
through the same function, so the feature space cannot drift between them.

On what is deliberately *not* here: connected-component size. For a star topology the
component is the fan-in neighbourhood, so the component size is dominated by
`receiver_fanin_*` and the extra graph construction buys little. It becomes worth
adding when the data contains multi-hop layering - mule to mule to cash-out - which
this generator does not yet produce.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Windows. Ten minutes is the scam's own timescale - Module 1 builds each burst inside
# a few minutes - and an hour gives the slower patterns somewhere to show up.
SHORT_WINDOW_S = 600
LONG_WINDOW_S = 3_600

# Fan-in at or above this is a hub. Three is not arbitrary: it is the number of
# distinct victims Module 1 routes into each mule, so the flag fires exactly on the
# shape the scam has. A production threshold would come from the traffic, not the
# generator - noted because it is the kind of constant that silently overfits.
HUB_FANIN = 3

# Time constants for the decayed counterparts of the windowed features above.
#
# A window has a boundary, and a boundary is a seam an adversary can pace under: six
# payers arriving 601 seconds apart into one account leave `receiver_fanin_10m` reading
# 1 forever, and the hub flag never fires. Measured, not hypothesised - see
# `tests/test_graph_features.py::test_a_paced_ring_walks_straight_through_the_window`.
#
# An exponential decay has no boundary. Evidence fades smoothly instead of falling off
# a cliff, so there is no interval to find and sit just outside of. The attacker's
# lever becomes "go slower", which costs them time linearly rather than buying them
# invisibility at one specific gap.
#
# It is no more expensive to maintain than a counter: state decays multiplicatively
# between events and increments on arrival, one update per transaction either way.
DECAY_FAST_S = 600.0
DECAY_SLOW_S = 3_600.0

# Below this a payer's contribution is not worth carrying. Bounds the per-receiver
# state so a busy merchant does not accumulate an unbounded dictionary.
DECAY_FLOOR = 1e-3

GRAPH_FEATURES = [
    "receiver_fanin_10m",
    "receiver_fanin_1h",
    "receiver_txn_count_10m",
    "receiver_amount_10m",
    "receiver_is_hub",
    "sender_fanout_1h",
    "receiver_payers_decay_fast",
    "receiver_payers_decay_slow",
    "receiver_inflow_decay",
]


def _rolling_distinct_and_counts(
    group_keys: np.ndarray,
    timestamps: np.ndarray,
    partners: np.ndarray,
    amounts: np.ndarray,
    window_s: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Distinct partners, row count and summed amount in `[t - window, t]` per group.

    One forward sweep per group holding a multiset of partners currently inside the
    window, with a trailing pointer that evicts rows as they age out. Every row is
    added once and removed once, so the whole pass is O(n).

    Ties matter here. Several payments can share a timestamp - a burst generated to
    the second, or a replayed batch - and the window is closed at both ends, so a row
    sharing `t` with the current one is *inside* the window. That is deliberate: those
    rows have already happened, and excluding them would understate a burst by exactly
    the amount that makes a burst interesting.

    Returns arrays aligned to the input order.
    """
    n = len(group_keys)
    distinct = np.zeros(n, dtype=np.int32)
    counts = np.zeros(n, dtype=np.int32)
    totals = np.zeros(n, dtype=np.float64)

    if n == 0:
        return distinct, counts, totals

    # Sort by group then time. `mergesort` is stable, so rows sharing a timestamp keep
    # their original relative order and the result is reproducible.
    order = np.lexsort((timestamps, group_keys))
    g = group_keys[order]
    t = timestamps[order]
    p = partners[order]
    a = amounts[order]

    # Group boundaries in the sorted array.
    starts = np.flatnonzero(np.r_[True, g[1:] != g[:-1]])
    ends = np.r_[starts[1:], n]

    for start, end in zip(starts, ends, strict=True):
        seen: dict[int, int] = {}
        tail = start
        running = 0.0

        for head in range(start, end):
            partner = p[head]
            seen[partner] = seen.get(partner, 0) + 1
            running += a[head]

            # Evict everything older than the window. Closed interval, so a row
            # exactly `window_s` old still counts.
            cutoff = t[head] - window_s
            while t[tail] < cutoff:
                old = p[tail]
                if seen[old] == 1:
                    del seen[old]
                else:
                    seen[old] -= 1
                running -= a[tail]
                tail += 1

            idx = order[head]
            distinct[idx] = len(seen)
            counts[idx] = head - tail + 1
            totals[idx] = running

    return distinct, counts, totals


def _rolling_decayed(
    group_keys: np.ndarray,
    timestamps: np.ndarray,
    partners: np.ndarray,
    tau_fast: float,
    tau_slow: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decayed partner diversity and inflow intensity, with no window boundary.

    For each account, every distinct partner contributes `exp(-age / tau)` based on how
    long ago it was last seen. Three payers in five minutes sums to nearly three; the
    same three spread over an hour sums to a fraction of one - and every value in
    between exists, which is the point. There is no gap at which the measure resets.

    Maintained incrementally. Each partner's last-seen time is stored, and its weight
    is derived on read rather than recomputed over a history, so the cost per
    transaction is one dictionary write and a bounded scan. Entries below `DECAY_FLOOR`
    are pruned, which caps the state a busy account can accumulate.

    Returns fast diversity, slow diversity, and a decayed count of arrivals.
    """
    n = len(group_keys)
    fast = np.zeros(n, dtype=np.float64)
    slow = np.zeros(n, dtype=np.float64)
    inflow = np.zeros(n, dtype=np.float64)

    if n == 0:
        return fast, slow, inflow

    order = np.lexsort((timestamps, group_keys))
    g, t, p = group_keys[order], timestamps[order], partners[order]

    starts = np.flatnonzero(np.r_[True, g[1:] != g[:-1]])
    ends = np.r_[starts[1:], n]

    for start, end in zip(starts, ends, strict=True):
        last_seen: dict[int, float] = {}
        intensity = 0.0
        previous_t = t[start]

        for head in range(start, end):
            now = t[head]
            # Decay the running intensity forward to this instant, then count the
            # arrival. This is the O(1) half - no history is re-read.
            intensity *= np.exp(-(now - previous_t) / tau_fast)
            intensity += 1.0
            previous_t = now

            last_seen[p[head]] = float(now)

            weight_fast = 0.0
            weight_slow = 0.0
            stale = []
            for partner, seen_at in last_seen.items():
                age = now - seen_at
                wf = np.exp(-age / tau_fast)
                ws = np.exp(-age / tau_slow)
                if ws < DECAY_FLOOR:
                    stale.append(partner)
                    continue
                weight_fast += wf
                weight_slow += ws
            for partner in stale:
                del last_seen[partner]

            idx = order[head]
            fast[idx] = weight_fast
            slow[idx] = weight_slow
            inflow[idx] = intensity

    return fast, slow, inflow


def _codes(series: pd.Series) -> np.ndarray:
    """Stable integer codes for a string column - dict lookups on ints beat strings."""
    return pd.factorize(series.astype("string").fillna(""), sort=False)[0].astype(np.int64)


def compute_graph_features(df: pd.DataFrame) -> pd.DataFrame:
    """Relational features for every row, using only rows at or before it.

    Expects `timestamp`, `sender_vpa`, `receiver_vpa` and `amount`. Returns a frame
    indexed like the input, so the caller can concatenate it straight on.
    """
    out = pd.DataFrame(index=df.index)

    if not {"sender_vpa", "receiver_vpa"}.issubset(df.columns):
        # Called on a frame without the identity columns - training drops them before
        # the model sees them, but `engineer_features` runs before that. Emitting
        # zeros keeps the column set stable rather than raising.
        for name in GRAPH_FEATURES:
            out[name] = 0
        return out

    timestamps = (
        pd.to_datetime(df["timestamp"]).astype("int64") // 1_000_000_000
    ).to_numpy()
    senders = _codes(df["sender_vpa"])
    receivers = _codes(df["receiver_vpa"])
    amounts = df["amount"].astype(float).to_numpy()

    # Receiver side: who is paying this account, how often, how much.
    fanin_short, count_short, amount_short = _rolling_distinct_and_counts(
        receivers, timestamps, senders, amounts, SHORT_WINDOW_S
    )
    fanin_long, _, _ = _rolling_distinct_and_counts(
        receivers, timestamps, senders, amounts, LONG_WINDOW_S
    )

    # Sender side: the mirror pattern. A compromised account spraying money at many
    # new receivers looks nothing like a mule collecting from many victims, and the
    # model should be able to tell them apart.
    fanout_long, _, _ = _rolling_distinct_and_counts(
        senders, timestamps, receivers, amounts, LONG_WINDOW_S
    )

    out["receiver_fanin_10m"] = fanin_short
    out["receiver_fanin_1h"] = fanin_long
    out["receiver_txn_count_10m"] = count_short
    out["receiver_amount_10m"] = amount_short
    out["receiver_is_hub"] = (fanin_short >= HUB_FANIN).astype(int)
    out["sender_fanout_1h"] = fanout_long

    # The same questions without a boundary to pace under. Kept alongside the windowed
    # features rather than replacing them: a window is the sharper signal when the
    # burst really is inside it, and the decay is what remains when the burst has been
    # deliberately stretched to sit outside.
    payers_fast, payers_slow, inflow = _rolling_decayed(
        receivers, timestamps, senders, DECAY_FAST_S, DECAY_SLOW_S
    )
    out["receiver_payers_decay_fast"] = payers_fast
    out["receiver_payers_decay_slow"] = payers_slow
    out["receiver_inflow_decay"] = inflow

    return out


def describe_ring(df: pd.DataFrame, ring_id: str) -> dict:
    """Everything the dashboard needs to draw one incident as a graph.

    Lives here rather than in the API because it is a property of the payment graph,
    and because the same shape is useful from a notebook when investigating a ring.
    """
    rows = df[df["ring_id"].astype(str) == ring_id].sort_values("timestamp")
    if rows.empty:
        raise KeyError(ring_id)

    receivers = rows["receiver_vpa"].unique().tolist()
    senders = rows["sender_vpa"].unique().tolist()

    return {
        "ring_id": ring_id,
        "pattern": str(rows["fraud_pattern"].iloc[0]),
        "receivers": receivers,
        "senders": senders,
        "fanin": len(senders),
        "total_amount": float(rows["amount"].sum()),
        "window_seconds": int(
            (
                pd.to_datetime(rows["timestamp"].iloc[-1])
                - pd.to_datetime(rows["timestamp"].iloc[0])
            ).total_seconds()
        ),
        "receiver_age_days": int(rows["receiver_vpa_age_days"].iloc[0]),
        "edges": [
            {
                "sender": str(r["sender_vpa"]),
                "receiver": str(r["receiver_vpa"]),
                "amount": float(r["amount"]),
                "timestamp": str(r["timestamp"]),
                "offset_seconds": int(
                    (
                        pd.to_datetime(r["timestamp"])
                        - pd.to_datetime(rows["timestamp"].iloc[0])
                    ).total_seconds()
                ),
            }
            for _, r in rows.iterrows()
        ],
    }
