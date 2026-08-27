"""Razorpay dispute objects.

Two things here are worth more than the rest: the object has to be shaped so their API
would accept it, and rupees must never leak into a field counted in paise. The second
is a factor-of-100 error that looks entirely plausible in a log line and is caught by
nothing except a test that looks for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from razorpay_client import (
    DISPUTE_TAT_DAYS,
    REASON_DESCRIPTIONS,
    REASON_PHASE,
    DisputeEntity,
    DisputeEvidence,
    RazorpayClient,
    RazorpayUnavailableError,
    build_dispute_entity,
    classify_reason,
    to_paise,
    to_rupees,
)

DECISION = {
    "amount": 62_000.0,
    "transaction_id": "pay_9Xk2LmQ4vB7nRt",
    "decision_id": "dec-abc123",
}


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
def test_rupees_become_integer_paise():
    assert to_paise(62_000.0) == 6_200_000
    assert to_paise(0.01) == 1
    assert isinstance(to_paise(240.5), int)


def test_paise_conversion_rounds_rather_than_truncates():
    """`int(0.1 * 3 * 100)` is 29 in floating point.

    A dispute one paisa short of the payment it contests gets rejected by the acquirer
    for a reason nobody enjoys diagnosing, and the arithmetic that caused it looks
    correct on the page.
    """
    assert to_paise(0.1 * 3) == 30
    assert to_paise(1.005) == 100 or to_paise(1.005) == 101   # banker's rounding either way
    assert to_paise(2.675) >= 267


@settings(max_examples=300, deadline=None)
@given(rupees=st.floats(min_value=0.01, max_value=1_000_000, allow_nan=False,
                        allow_infinity=False))
def test_the_round_trip_never_drifts_by_more_than_a_paisa(rupees):
    assert abs(to_rupees(to_paise(rupees)) - rupees) < 0.011


def test_the_disputed_amount_is_always_in_paise():
    """The single conversion point, asserted where it matters.

    Every rupee figure crossing the Razorpay boundary goes through `to_paise`, and the
    entity counts subunits throughout - including inside `evidence`.
    """
    dispute = build_dispute_entity(DECISION, "unauthorised")

    assert dispute.amount == 6_200_000
    assert dispute.evidence.amount == 6_200_000
    assert dispute.amount_rupees() == pytest.approx(62_000.0)


# --------------------------------------------------------------------------- #
# The entity
# --------------------------------------------------------------------------- #
def test_the_entity_matches_the_shape_razorpay_returns():
    dispute = build_dispute_entity(DECISION, "unauthorised transaction")
    payload = dispute.model_dump(exclude_none=True)

    for field in ("id", "entity", "payment_id", "amount", "currency", "amount_deducted",
                  "reason_code", "reason_description", "respond_by", "status", "phase",
                  "created_at", "evidence"):
        assert field in payload, field

    assert payload["entity"] == "dispute"
    assert payload["currency"] == "INR"
    assert payload["id"].startswith("disp_")


def test_timestamps_are_unix_integers_not_iso_strings():
    """Razorpay counts seconds since the epoch. An ISO string here would be rejected."""
    dispute = build_dispute_entity(DECISION, "unauthorised")

    assert isinstance(dispute.created_at, int)
    assert isinstance(dispute.respond_by, int)
    assert dispute.respond_by > dispute.created_at


def test_the_response_deadline_follows_the_regulated_turnaround():
    """RBI's harmonised TAT is what the responder is racing, so it has to be right."""
    created = datetime(2026, 8, 23, 3, 20, tzinfo=UTC)
    dispute = build_dispute_entity(DECISION, "unauthorised", raised_at=created)

    expected = created + timedelta(days=DISPUTE_TAT_DAYS)
    assert dispute.respond_by == int(expected.timestamp())


def test_hours_remaining_goes_negative_once_the_deadline_passes():
    created = datetime(2026, 8, 23, tzinfo=UTC)
    dispute = build_dispute_entity(DECISION, "unauthorised", raised_at=created)

    assert dispute.hours_to_respond(created) == pytest.approx(DISPUTE_TAT_DAYS * 24)
    late = created + timedelta(days=DISPUTE_TAT_DAYS + 2)
    assert dispute.hours_to_respond(late) < 0


def test_a_fresh_dispute_has_nothing_deducted_yet():
    """`amount_deducted` is what the merchant loses if the dispute is lost, not what is
    at stake. Conflating them would overstate every open dispute."""
    assert build_dispute_entity(DECISION, "unauthorised").amount_deducted == 0


def test_every_reason_code_has_a_description_and_a_phase():
    """The three tables must stay in step; a reason with no phase would fail validation
    at the worst possible moment."""
    assert set(REASON_DESCRIPTIONS) == set(REASON_PHASE)
    for code, description in REASON_DESCRIPTIONS.items():
        assert description.strip()
        assert REASON_PHASE[code] in (
            "fraud", "retrieval", "chargeback", "pre_arbitration", "arbitration"
        )


def test_fraud_disputes_skip_retrieval():
    """A fraud claim goes straight to chargeback, which shortens the clock.

    Worth pinning because it is the difference between the responder having thirty
    days and having considerably fewer.
    """
    assert REASON_PHASE["FRAUD"] == "chargeback"
    assert REASON_PHASE["GOODS_NOT_RECEIVED"] == "retrieval"


@pytest.mark.parametrize("status", ["open", "under_review", "won", "lost", "closed"])
def test_every_documented_status_validates(status):
    dispute = build_dispute_entity(DECISION, "unauthorised")
    assert DisputeEntity.model_validate({**dispute.model_dump(), "status": status})


def test_an_undocumented_status_is_rejected():
    """The value domain is theirs, not ours. Inventing one would fail on submission."""
    dispute = build_dispute_entity(DECISION, "unauthorised").model_dump()
    with pytest.raises(ValidationError):
        DisputeEntity.model_validate({**dispute, "status": "probably_fine"})


# --------------------------------------------------------------------------- #
# Triage
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("complaint", "expected"),
    [
        ("Cardholder did not authorise this transaction", "FRAUD"),
        ("unauthorised UPI transaction reported", "FRAUD"),
        ("I do not recognise this charge", "FRAUD"),
        ("my card was stolen", "FRAUD"),
        ("the account was compromised", "FRAUD"),
        ("goods were never delivered", "GOODS_NOT_RECEIVED"),
        ("item not received after two weeks", "GOODS_NOT_RECEIVED"),
        ("my parcel never arrived", "GOODS_NOT_RECEIVED"),
        ("item arrived defective", "GOODS_NOT_AS_DESCRIBED"),
        ("product was not as described", "GOODS_NOT_AS_DESCRIBED"),
        ("I was charged twice for one order", "DUPLICATE_PROCESSING"),
        ("the refund was never issued", "CREDIT_NOT_PROCESSED"),
        ("disputing this payment", "CHARGEBACK"),
    ],
)
def test_complaints_route_to_the_right_reason_code(complaint, expected):
    """The reason code decides which evidence is required, so triage is the step that
    determines whether the packet can be filed at all."""
    assert classify_reason(complaint) == expected


def test_triage_is_deterministic():
    """Run twice, same answer. A reason code that varied between runs would demand
    different evidence for the same complaint - the objection that keeps the language
    model out of this decision."""
    complaint = "Cardholder reports they did not authorise this transaction"
    assert classify_reason(complaint) == classify_reason(complaint)


@settings(max_examples=120, deadline=None)
@given(text=st.text(min_size=0, max_size=200))
def test_triage_always_returns_a_code_razorpay_knows(text):
    """Free text from an issuer is arbitrary. It must never produce a code that fails
    validation downstream, and it must never raise."""
    assert classify_reason(text) in REASON_DESCRIPTIONS


# --------------------------------------------------------------------------- #
# The live adapter
# --------------------------------------------------------------------------- #
def test_the_client_is_unconfigured_without_credentials(monkeypatch):
    for var in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
        monkeypatch.delenv(var, raising=False)

    client = RazorpayClient()
    assert client.configured is False
    assert client.mode == "unconfigured"


def test_the_key_prefix_reveals_which_mode_is_in_use(monkeypatch):
    """Anyone demoing should see at a glance that they are pointed at test mode, and
    anyone in production should see that they are not."""
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_abc123")
    assert RazorpayClient().mode == "test"

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_abc123")
    assert RazorpayClient().mode == "live"


def test_calling_the_api_without_credentials_raises_a_named_error(monkeypatch):
    """Not a generic exception. The caller has to be able to tell "not configured"
    apart from "configured and broken", because only one of them is a problem."""
    for var in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(RazorpayUnavailableError, match="not set"):
        RazorpayClient().fetch_disputes()


def test_health_explains_why_an_absent_key_is_not_a_failure(monkeypatch):
    for var in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
        monkeypatch.delenv(var, raising=False)

    health = RazorpayClient().health()
    assert health["status"] == "absent"
    assert health["mode"] == "unconfigured"
    # The note is the point: it stops the absence reading as a broken integration.
    assert "creates a dispute" in health["note"]


def test_a_live_dispute_payload_validates_against_our_entity():
    """The shape check that makes the local objects worth anything.

    This is a response body in the form Razorpay documents. If our model cannot parse
    it, the local disputes are the wrong shape however plausible they look.
    """
    payload = {
        "id": "disp_AHmDholrwPCbfN",
        "entity": "dispute",
        "payment_id": "pay_AHmA4XjJHiPCbf",
        "amount": 10000,
        "currency": "INR",
        "amount_deducted": 0,
        "reason_code": "CHARGEBACK",
        "reason_description": "Cardholder disputes the transaction with their issuer",
        "respond_by": 1590604200,
        "status": "open",
        "phase": "chargeback",
        "created_at": 1590059211,
        "evidence": {
            "amount": 10000,
            "summary": None,
            "shipping_proof": None,
            "billing_proof": None,
            "cancellation_proof": None,
            "customer_communication": None,
            "proof_of_service": None,
            "explanation_letter": None,
            "refund_confirmation": None,
            "access_activity_log": None,
            "refund_cancellation_policy": None,
            "term_and_conditions": None,
            "others": None,
            "submitted_at": None,
        },
    }

    dispute = DisputeEntity.model_validate(payload)
    assert dispute.amount_rupees() == pytest.approx(100.0)
    assert dispute.phase == "chargeback"


def test_the_evidence_object_accepts_every_documented_proof_field():
    """All thirteen, so a packet cannot fail to serialise because we omitted one."""
    evidence = DisputeEvidence(
        amount=10000, summary="s",
        shipping_proof=["doc_1"], billing_proof=["doc_2"], cancellation_proof=["doc_3"],
        customer_communication=["doc_4"], proof_of_service=["doc_5"],
        explanation_letter=["doc_6"], refund_confirmation=["doc_7"],
        access_activity_log=["doc_8"], refund_cancellation_policy=["doc_9"],
        term_and_conditions=["doc_10"], others=[{"type": "x", "description": "y"}],
        submitted_at=1590059211,
    )
    assert evidence.model_dump(exclude_none=True)["amount"] == 10000
