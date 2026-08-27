"""The decision ledger.

Two behaviours here are load-bearing and neither is obvious from the happy path:
the decision record must be immutable once written, and a ledger failure must never
propagate into a scoring failure. Both are tested directly.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from audit_store import VALID_OUTCOMES, AuditStore


def _record(store: AuditStore, **overrides) -> str:
    payload = {
        "transaction_id": "tx-abc123",
        "sender_vpa": "victim.suresh@okhdfcbank",
        "receiver_vpa": "verify.acct@paytm",
        "amount": 62000.0,
        "receiver_vpa_age_days": 0,
        "txn_timestamp": "2026-07-20T20:15:43",
        "sender_city": "Chennai",
        "fraud_probability": 0.9823,
        "threshold": 0.123,
        "decision": "HOLD",
        "model_name": "RandomForest",
        "model_trained_at": "2026-08-11T12:23:10+00:00",
        "threshold_policy": "cost",
        "latency_ms": 47,
        "reasons": ["transaction amount (Rs.62,000)", "age of the receiving UPI ID"],
        "shap_concepts": {"transaction amount": 0.21, "time of day": -0.03},
    }
    payload.update(overrides)
    decision_id = store.record_decision(**payload)
    assert decision_id is not None
    return decision_id


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #
def test_a_decision_round_trips_with_its_full_explanation(audit_db):
    decision_id = _record(audit_db)
    record = audit_db.get_decision(decision_id)

    assert record["transaction_id"] == "tx-abc123"
    assert record["decision"] == "HOLD"
    assert record["fraud_probability"] == pytest.approx(0.9823)
    # Signed values survive the JSON round trip - a mitigating factor stays negative.
    assert record["shap_concepts"]["time of day"] == pytest.approx(-0.03)
    assert len(record["reasons"]) == 2
    assert record["dispositions"] == []


def test_the_model_version_is_pinned_to_the_decision(audit_db):
    """Replaying a decision must report the model that made it, not the current one.

    This is the whole reason the ledger exists: after two retrains, a dispute about a
    payment held in July has to be answerable with July's model and July's threshold.
    """
    decision_id = _record(audit_db, model_name="XGBoost", threshold=0.657,
                          threshold_policy="precision_at_recall")
    record = audit_db.get_decision(decision_id)

    assert record["model_name"] == "XGBoost"
    assert record["threshold"] == pytest.approx(0.657)
    assert record["threshold_policy"] == "precision_at_recall"


def test_unknown_decision_reads_as_none(audit_db):
    assert audit_db.get_decision("dec-does-not-exist") is None


def test_one_transaction_can_own_several_decisions(audit_db):
    """A retry or a replayed webhook is a second scoring event, not an overwrite."""
    first = _record(audit_db, transaction_id="tx-same")
    second = _record(audit_db, transaction_id="tx-same", fraud_probability=0.4)

    assert first != second
    assert len(audit_db.recent_decisions()) == 2


# --------------------------------------------------------------------------- #
# Immutability
# --------------------------------------------------------------------------- #
def test_the_decision_row_is_never_rewritten(audit_db):
    """Dispositions must not touch the decision. An editable audit trail is not one."""
    decision_id = _record(audit_db)
    before = audit_db.get_decision(decision_id)

    audit_db.record_disposition(decision_id, "false_positive", reviewer="harsh")
    after = audit_db.get_decision(decision_id)

    for field in ("fraud_probability", "decision", "threshold", "model_name", "scored_at"):
        assert before[field] == after[field]


def test_a_reviewer_changing_their_mind_appends_rather_than_replaces(audit_db):
    decision_id = _record(audit_db)
    audit_db.record_disposition(decision_id, "false_positive", reviewer="first-pass")
    audit_db.record_disposition(decision_id, "confirmed_fraud", reviewer="second-pass",
                                note="victim confirmed by phone")

    record = audit_db.get_decision(decision_id)
    assert len(record["dispositions"]) == 2
    outcomes = {d["outcome"] for d in record["dispositions"]}
    assert outcomes == {"false_positive", "confirmed_fraud"}


def test_disposition_rejects_an_unknown_outcome(audit_db):
    decision_id = _record(audit_db)
    with pytest.raises(ValueError, match="outcome must be one of"):
        audit_db.record_disposition(decision_id, "probably_fine")


def test_disposition_on_a_missing_decision_raises(audit_db):
    with pytest.raises(KeyError):
        audit_db.record_disposition("dec-nope", "confirmed_fraud")


@pytest.mark.parametrize("outcome", VALID_OUTCOMES)
def test_every_documented_outcome_is_accepted(audit_db, outcome):
    decision_id = _record(audit_db)
    assert audit_db.record_disposition(decision_id, outcome)["outcome"] == outcome


# --------------------------------------------------------------------------- #
# Failure containment
# --------------------------------------------------------------------------- #
def test_a_write_failure_returns_none_instead_of_raising(audit_db):
    """Bookkeeping must never be the thing that stops a fraud engine detecting fraud.

    The caller has already computed a verdict by the time the ledger is touched.
    Losing the audit row is bad; losing the block is worse.
    """
    with patch.object(
        audit_db, "_cursor", side_effect=sqlite3.OperationalError("disk I/O error")
    ):
        result = audit_db.record_decision(
            transaction_id="tx-doomed", sender_vpa="a@ybl", receiver_vpa="b@paytm",
            amount=100.0, receiver_vpa_age_days=5, txn_timestamp=None, sender_city=None,
            fraud_probability=0.9, threshold=0.12, decision="HOLD",
            model_name="RandomForest", model_trained_at=None, threshold_policy="cost",
            latency_ms=40, reasons=[], shap_concepts={},
        )

    assert result is None
    assert audit_db.degraded is True
    assert "disk I/O error" in audit_db.last_error


def test_degradation_is_visible_rather_than_silent(audit_db):
    assert audit_db.degraded is False
    assert audit_db.last_error is None


def test_reading_before_connect_raises_rather_than_returning_empty():
    """A disconnected ledger must not look like an empty one.

    Silently returning no rows would report "zero decisions" on a dashboard, which is
    indistinguishable from a quiet day and far more dangerous than an error.
    """
    store = AuditStore("unused.db")
    assert store.ready is False
    with pytest.raises(RuntimeError, match="not connected"):
        store.recent_decisions()


# --------------------------------------------------------------------------- #
# Queue and statistics
# --------------------------------------------------------------------------- #
def test_recent_decisions_are_newest_first_and_can_filter_to_alerts(audit_db):
    _record(audit_db, transaction_id="tx-1", decision="ACCEPT", fraud_probability=0.01)
    _record(audit_db, transaction_id="tx-2", decision="HOLD")
    _record(audit_db, transaction_id="tx-3", decision="ACCEPT", fraud_probability=0.02)

    everything = audit_db.recent_decisions()
    assert [d["transaction_id"] for d in everything] == ["tx-3", "tx-2", "tx-1"]

    alerts = audit_db.recent_decisions(only_actioned=True)
    assert [d["transaction_id"] for d in alerts] == ["tx-2"]


def test_queue_entries_carry_the_latest_disposition(audit_db):
    decision_id = _record(audit_db)
    audit_db.record_disposition(decision_id, "false_positive")
    audit_db.record_disposition(decision_id, "confirmed_fraud")

    assert audit_db.recent_decisions()[0]["latest_disposition"] == "confirmed_fraud"


def test_limit_is_clamped_to_a_sane_ceiling(audit_db):
    """An unbounded `limit` is a denial-of-service on your own alert queue."""
    for i in range(5):
        _record(audit_db, transaction_id=f"tx-{i}")

    assert len(audit_db.recent_decisions(limit=10_000)) == 5
    assert len(audit_db.recent_decisions(limit=0)) == 1


def test_stats_counts_volume_and_exposure(audit_db):
    _record(audit_db, decision="HOLD", amount=62000.0)
    _record(audit_db, decision="STEP_UP", amount=8000.0)
    _record(audit_db, decision="ACCEPT", amount=240.0, fraud_probability=0.01)

    stats = audit_db.stats()
    assert stats["decisions_recorded"] == 3
    assert stats["blocked"] == 2
    assert stats["approved"] == 1
    assert stats["block_rate"] == pytest.approx(2 / 3)
    assert stats["value_blocked_inr"] == pytest.approx(70_000.0)


def test_reviewed_precision_ignores_unreviewed_alerts(audit_db):
    """Precision is reported over human judgements only, never assumed for the rest.

    In production there are no labels, only outcomes someone eventually confirms.
    Counting unreviewed alerts as correct would be assuming the answer.
    """
    confirmed = _record(audit_db, transaction_id="tx-real")
    wrong = _record(audit_db, transaction_id="tx-fp")
    _record(audit_db, transaction_id="tx-untouched")

    audit_db.record_disposition(confirmed, "confirmed_fraud")
    audit_db.record_disposition(wrong, "false_positive")

    stats = audit_db.stats()
    assert stats["reviewed"] == 2
    assert stats["precision_reviewed"] == pytest.approx(0.5)


def test_unclear_outcomes_are_excluded_from_precision(audit_db):
    confirmed = _record(audit_db, transaction_id="tx-a")
    murky = _record(audit_db, transaction_id="tx-b")
    audit_db.record_disposition(confirmed, "confirmed_fraud")
    audit_db.record_disposition(murky, "unclear")

    stats = audit_db.stats()
    assert stats["unclear"] == 1
    assert stats["reviewed"] == 1
    assert stats["precision_reviewed"] == pytest.approx(1.0)


def test_precision_is_none_rather_than_zero_when_nothing_is_reviewed(audit_db):
    """Nobody has judged anything yet - that is not the same as being wrong every time."""
    _record(audit_db)
    assert audit_db.stats()["precision_reviewed"] is None


def test_a_reopened_ledger_still_sees_its_history(audit_db, tmp_path):
    """Durability: the point of a ledger is that it outlives the process."""
    decision_id = _record(audit_db)
    audit_db.close()

    reopened = AuditStore(tmp_path / "audit.db")
    reopened.connect()
    try:
        assert reopened.get_decision(decision_id) is not None
        assert reopened.stats()["decisions_recorded"] == 1
    finally:
        reopened.close()


def test_the_two_queue_queries_differ_only_by_their_filter():
    """The queue SELECT is written out twice so that neither is built at runtime.

    That trade buys static SQL in the audit ledger at the cost of a copy that can drift.
    This is the thing standing between those two queries, and it is why the duplication
    is acceptable: strip the WHERE line and they must be identical.
    """
    actioned = [
        line for line in AuditStore._RECENT_ACTIONED.splitlines()
        if "WHERE d.decision NOT IN" not in line
    ]
    assert actioned == AuditStore._RECENT_ALL.splitlines()


def test_the_filter_has_a_placeholder_for_every_accepted_decision():
    """`NOT IN (?,?)` is written literally, so it must match the tuple bound into it.

    Adding a third accepted decision without widening the clause would bind an extra
    parameter against a two-slot filter - sqlite raises, but only on the code path that
    passes `only_actioned`, which is the operator queue rather than anything a test
    hits by default.
    """
    clause = next(
        line for line in AuditStore._RECENT_ACTIONED.splitlines()
        if "NOT IN" in line
    )
    assert clause.count("?") == len(AuditStore.ACCEPTED_DECISIONS)
