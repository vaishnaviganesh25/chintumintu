"""Cross-merchant reputation.

The capability Razorpay's Vulcan describes as network-level fraud detection: evidence
that exists only between merchants, not inside any one of them. Most of these tests
are about restraint rather than reach - what the layer must *refuse* to do, because an
escalation nobody can appeal is worse than a fraud nobody caught.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from network_signals import (
    LOOKBACK,
    SPRAY_MERCHANTS,
    NetworkReputation,
    apply,
    lookup,
)

NOW = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)


def _decision(store, sender="payer@ybl", receiver="shop@paytm", decision="HOLD",
              scored_at=None, **overrides):
    payload = {
        "transaction_id": "tx-1", "sender_vpa": sender, "receiver_vpa": receiver,
        "amount": 41_000.0, "receiver_vpa_age_days": 400,
        "txn_timestamp": "2026-08-23T13:00:00", "sender_city": "Pune",
        "fraud_probability": 0.62, "threshold": 0.07, "decision": decision,
        "model_name": "RandomForest", "model_trained_at": None,
        "threshold_policy": "cost", "latency_ms": 50, "reasons": [], "shap_concepts": {},
    }
    payload.update(overrides)
    decision_id = store.record_decision(**payload)
    assert decision_id is not None

    # `scored_at` is stamped by the ledger, so ageing a row means rewriting it. Done
    # directly rather than through the public API precisely because the ledger refuses
    # to rewrite decisions - which is the property under test elsewhere.
    if scored_at is not None:
        with store._cursor() as cur:
            cur.execute("UPDATE decisions SET scored_at = ? WHERE decision_id = ?",
                        (scored_at.isoformat(timespec="microseconds"), decision_id))
    return decision_id


# --------------------------------------------------------------------------- #
# What it sees
# --------------------------------------------------------------------------- #
def test_a_payer_with_no_history_carries_no_reputation(audit_db):
    reputation = lookup(audit_db, "brand.new@ybl", "shop@paytm", now=NOW)

    assert reputation.has_history is False
    assert reputation.payer_confirmed_fraud == 0


def test_it_counts_a_payer_across_unrelated_merchants(audit_db):
    """The whole point: one payer, several merchants, one view.

    No individual merchant here can see more than its own row.
    """
    for i, receiver in enumerate(["electronics@paytm", "kirana@okbizaxis", "travel@ybl"]):
        _decision(audit_db, sender="spray@ybl", receiver=receiver,
                  transaction_id=f"tx-{i}", scored_at=NOW - timedelta(hours=i + 1))

    reputation = lookup(audit_db, "spray@ybl", "somewhere.else@paytm", now=NOW)
    assert reputation.payer_decisions == 3
    assert reputation.payer_distinct_merchants == 3


def test_it_counts_distinct_payers_into_one_receiver(audit_db):
    """Consortium-level fan-in: a mule collecting across merchants, not just within one."""
    for i, sender in enumerate(["a@ybl", "b@oksbi", "c@axl"]):
        _decision(audit_db, sender=sender, receiver="mule@paytm",
                  transaction_id=f"tx-{i}", scored_at=NOW - timedelta(minutes=i * 5))

    reputation = lookup(audit_db, "d@ibl", "mule@paytm", now=NOW)
    assert reputation.receiver_distinct_payers == 3


def test_only_analyst_confirmed_fraud_counts_as_confirmed(audit_db):
    """A prior HOLD is the model's opinion; a disposition is a human conclusion."""
    held = _decision(audit_db, sender="payer@ybl", decision="HOLD", scored_at=NOW - timedelta(hours=2))
    reputation = lookup(audit_db, "payer@ybl", "shop@paytm", now=NOW)
    assert reputation.payer_actioned == 1
    assert reputation.payer_confirmed_fraud == 0

    audit_db.record_disposition(held, "confirmed_fraud", reviewer="analyst-1")
    assert lookup(audit_db, "payer@ybl", "shop@paytm", now=NOW).payer_confirmed_fraud == 1


def test_a_false_positive_disposition_does_not_stain_a_payer(audit_db):
    """An analyst clearing an alert must not leave the customer worse off than before.

    Counting any disposition would mean a wrongly-flagged customer carries the flag
    anyway, which turns the review process into theatre.
    """
    held = _decision(audit_db, sender="wronged@ybl", scored_at=NOW - timedelta(hours=1))
    audit_db.record_disposition(held, "false_positive", reviewer="analyst-1")

    assert lookup(audit_db, "wronged@ybl", "shop@paytm", now=NOW).payer_confirmed_fraud == 0


def test_history_older_than_the_window_is_forgotten(audit_db):
    """A customer must not carry a flag indefinitely. Reputation has to expire."""
    stale = _decision(audit_db, sender="payer@ybl",
                      scored_at=NOW - LOOKBACK - timedelta(days=1))
    audit_db.record_disposition(stale, "confirmed_fraud")

    reputation = lookup(audit_db, "payer@ybl", "shop@paytm", now=NOW)
    assert reputation.payer_decisions == 0
    assert reputation.payer_confirmed_fraud == 0


def test_a_lookup_never_raises_when_the_ledger_is_unavailable():
    """Reputation is an enrichment. Losing it drops the consortium view, not the payment."""
    from audit_store import AuditStore

    disconnected = AuditStore("unused.db")
    reputation = lookup(disconnected, "a@ybl", "b@paytm", now=NOW)

    assert reputation == NetworkReputation()
    assert reputation.has_history is False


# --------------------------------------------------------------------------- #
# What it does with it
# --------------------------------------------------------------------------- #
def test_nothing_changes_when_there_is_nothing_to_add(audit_db):
    """The normal case. Most payments have no consortium evidence either way."""
    action, reasons = apply("ACCEPT", NetworkReputation())

    assert action == "ACCEPT"
    assert reasons == []


def test_confirmed_fraud_elsewhere_escalates_the_action():
    action, reasons = apply("ACCEPT", NetworkReputation(payer_confirmed_fraud=1))

    assert action == "STEP_UP"
    assert reasons and "another merchant" in reasons[0]


def test_escalation_moves_one_step_at_a_time():
    """A single piece of evidence should not take a payment from accept to hold.

    Stacking straight to the most expensive action on one signal is how a network
    layer starts declining good customers on thin evidence.
    """
    assert apply("ACCEPT", NetworkReputation(payer_confirmed_fraud=1))[0] == "STEP_UP"
    assert apply("STEP_UP", NetworkReputation(payer_confirmed_fraud=1))[0] == "HOLD"
    assert apply("HOLD", NetworkReputation(payer_confirmed_fraud=1))[0] == "HOLD"


def test_a_prior_hold_alone_never_escalates():
    """The restraint that stops the system building a blacklist out of its own doubt.

    If uncertain decisions escalated each other, one borderline hold would follow a
    customer across every merchant they touch, compounding at each one, with no human
    ever having agreed to it.
    """
    action, reasons = apply("ACCEPT", NetworkReputation(payer_decisions=9, payer_actioned=9))

    assert action == "ACCEPT"
    assert reasons == []


def test_a_clean_record_never_de_escalates():
    """Absence of history is not absence of risk.

    Treating a clean record as positive evidence would score first-time buyers as
    riskier than returning ones, which is both wrong and quietly discriminatory.
    """
    trusted = NetworkReputation(payer_decisions=40, payer_actioned=0,
                                payer_distinct_merchants=3)

    assert apply("HOLD", trusted)[0] == "HOLD"
    assert apply("STEP_UP", trusted)[0] == "STEP_UP"


@pytest.mark.parametrize("merchants", [SPRAY_MERCHANTS, SPRAY_MERCHANTS + 4])
def test_a_card_sprayed_across_many_merchants_escalates(merchants):
    """Card testing looks like shopping until you count the sellers."""
    action, reasons = apply("ACCEPT", NetworkReputation(payer_distinct_merchants=merchants))

    assert action == "STEP_UP"
    assert any("unrelated merchants" in r for r in reasons)


def test_ordinary_multi_merchant_shopping_does_not_escalate():
    """People do buy from several merchants in a week. The threshold has to allow it."""
    action, reasons = apply(
        "ACCEPT", NetworkReputation(payer_decisions=5, payer_distinct_merchants=SPRAY_MERCHANTS - 1)
    )

    assert action == "ACCEPT"
    assert reasons == []


def test_every_escalation_states_its_reason():
    """An override with no stated cause is indistinguishable from a bug, and cannot be
    appealed by the merchant it affects."""
    for reputation in (
        NetworkReputation(payer_confirmed_fraud=2),
        NetworkReputation(receiver_confirmed_fraud=1),
        NetworkReputation(payer_distinct_merchants=SPRAY_MERCHANTS + 1),
    ):
        action, reasons = apply("ACCEPT", reputation)
        assert action != "ACCEPT"
        assert reasons and all(r.strip() for r in reasons)


def test_a_tainted_receiver_escalates_a_clean_payer():
    """The mirror case: the collecting account is the thing that was confirmed, and the
    next victim paying into it is a different person entirely."""
    action, reasons = apply("ACCEPT", NetworkReputation(receiver_confirmed_fraud=1))

    assert action == "STEP_UP"
    assert any("receiving account" in r for r in reasons)


def test_reputation_serialises_for_the_ledger():
    """It is recorded alongside the decision, so an override stays answerable later."""
    payload = NetworkReputation(payer_confirmed_fraud=1, payer_distinct_merchants=7).as_dict()

    assert payload["payer_confirmed_fraud"] == 1
    assert payload["payer_distinct_merchants"] == 7
    assert all(isinstance(v, int) for v in payload.values())
