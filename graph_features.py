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

GRAPH_FEATURES = [
    "receiver_fanin_10m",
    "receiver_fanin_1h",
    "receiver_txn_count_10m",
    "receiver_amount_10m",
    "receiver_is_hub",
    "sender_fanout_1h",
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

    for start, end in zip(starts, ends):
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
