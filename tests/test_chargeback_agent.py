"""The chargeback responder.

Most of this file is about what happens when the language model is *not* available,
because that is the part that decides whether the feature is a demo or a tool. A
dispute has a filing deadline; an ops team that receives nothing because a third-party
API was down has been failed by its tooling, not served by it.

The rest asserts the boundaries: the model never sees the score-making path, never
invents a reason code, and never gets to describe its own provenance.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import chargeback_agent as agent
from chargeback_agent import (
    REASON_CODES,
    ProviderUnavailable,
    RepresentmentPacket,
    available_provider,
    build_case_file,
    deterministic_packet,
    draft_representment,
    respond_to_dispute,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def _decision(store, **overrides) -> str:
    payload = {
        "transaction_id": "tx-disputed",
        "sender_vpa": "victim.suresh@okhdfcbank",
        "receiver_vpa": "verify.acct@paytm",
        "amount": 62_000.0,
        "receiver_vpa_age_days": 0,
        "txn_timestamp": "2026-08-23T03:20:00",
        "sender_city": "Chennai",
        "fraud_probability": 0.8357,
        "threshold": 0.1361,
        "decision": "HOLD",
        "model_name": "RandomForest",
        "model_trained_at": "2026-08-23T07:11:45+00:00",
        "threshold_policy": "cost",
        "latency_ms": 85,
        "reasons": ["age of the receiving UPI ID (created today)", "transaction amount"],
        "shap_concepts": {"transaction amount": 0.21, "time of day": 0.07,
                          "receiver looks like a registered merchant": -0.04},
    }
    payload.update(overrides)
    decision_id = store.record_decision(**payload)
    assert decision_id is not None
    return decision_id


@pytest.fixture
def case(audit_db):
    decision_id = _decision(audit_db)
    return audit_db, decision_id, build_case_file(
        decision_id, "Cardholder reports an unauthorised transaction", store=audit_db
    )


@pytest.fixture(autouse=True)
def no_ambient_credentials(monkeypatch):
    """Never let a developer's real key make these tests hit the network.

    Every provider the module knows about is cleared, so a machine configured for one
    of them does not quietly turn these into live API calls.
    """
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY",
                "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def _valid_packet(**overrides) -> RepresentmentPacket:
    payload = {
        "recommendation": "represent", "confidence": 0.5,
        "summary": "s", "argument": "a",
    }
    payload.update(overrides)
    return RepresentmentPacket(**payload)


# --------------------------------------------------------------------------- #
# Deterministic retrieval
# --------------------------------------------------------------------------- #
def test_the_case_file_is_built_from_the_ledger_not_recomputed(case):
    """The evidence must be what was recorded at decision time.

    Re-scoring the payment now would produce today's model's answer to a question that
    was asked months ago, which is precisely the thing the ledger exists to prevent.
    """
    _, _, case_file = case

    assert case_file["engine_decision"]["fraud_probability"] == pytest.approx(0.8357)
    assert case_file["engine_decision"]["model"] == "RandomForest"
    assert case_file["engine_decision"]["threshold_in_force"] == pytest.approx(0.1361)
    assert case_file["explanation"]["reasons_given_at_the_time"]


def test_evidence_retrieval_is_deterministic(audit_db):
    """Built twice against the same dispute, identical.

    The dispute entity is an *input*, not something retrieval invents - it carries a
    fresh id and creation timestamp each time it is minted, exactly as Razorpay's does.
    What has to be reproducible is the evidence gathered around it, because a document
    sent to an acquirer cannot rest on a retrieval step that varies between runs.
    """
    from razorpay_client import build_dispute_entity

    decision_id = _decision(audit_db)
    decision = audit_db.get_decision(decision_id)
    dispute = build_dispute_entity(decision, "unauthorised")

    first = build_case_file(decision_id, "unauthorised", store=audit_db, dispute=dispute)
    second = build_case_file(decision_id, "unauthorised", store=audit_db, dispute=dispute)

    assert first == second


def test_shap_drivers_are_ranked_by_absolute_contribution(case):
    _, _, case_file = case
    drivers = case_file["explanation"]["top_shap_drivers"]

    magnitudes = [abs(d["signed_contribution"]) for d in drivers]
    assert magnitudes == sorted(magnitudes, reverse=True)
    # Mitigating factors survive with their sign intact.
    assert any(d["signed_contribution"] < 0 for d in drivers)


def test_an_unknown_decision_cannot_be_disputed(audit_db):
    with pytest.raises(KeyError):
        build_case_file("dec-not-here", "anything", store=audit_db)


def test_the_case_file_carries_the_senders_other_payments(audit_db):
    """Context the issuer's "this was not the cardholder" argument has to survive."""
    _decision(audit_db, transaction_id="tx-earlier", amount=240.0, decision="ACCEPT",
              fraud_probability=0.001)
    disputed = _decision(audit_db, transaction_id="tx-disputed")

    case_file = build_case_file(disputed, "unauthorised", store=audit_db)
    assert len(case_file["sender_recent_payments"]) >= 1


# --------------------------------------------------------------------------- #
# The fallback
# --------------------------------------------------------------------------- #
def test_missing_credentials_produce_a_usable_draft_not_an_error(case):
    _, _, case_file = case
    packet = draft_representment(case_file)

    assert isinstance(packet, RepresentmentPacket)
    assert packet.degraded is True
    assert "no API credentials" in packet.generated_by
    assert packet.argument.strip()
    assert packet.summary.strip()


def test_the_provider_is_chosen_by_which_credentials_exist(monkeypatch):
    """No provider setting to fall out of step with the environment.

    Adding a key is the whole of the setup, and Gemini is preferred when both are
    present only because it is the configured default - not because it is better.
    """
    assert available_provider() is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    label, _ = available_provider()
    assert label.startswith("anthropic:")

    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")
    label, _ = available_provider()
    assert label.startswith("gemini:")


def test_google_api_key_is_accepted_as_well_as_gemini_api_key(monkeypatch):
    """Both names are in circulation; a working key under the other one must not
    silently produce degraded packets."""
    monkeypatch.setenv("GOOGLE_API_KEY", "gm-test")
    label, _ = available_provider()
    assert label.startswith("gemini:")


@pytest.mark.parametrize(
    ("raised", "expected_marker"),
    [
        (ProviderUnavailable("SDK not installed"), "SDK not installed"),
        (TimeoutError("timed out"), "TimeoutError"),
        (ConnectionError("unreachable"), "ConnectionError"),
        (RuntimeError("rate limited"), "RuntimeError"),
    ],
)
def test_every_provider_failure_mode_falls_back(case, monkeypatch, raised, expected_marker):
    """Any way a provider can fail is a fallback, never an exception.

    Deliberately not enumerating one SDK's exception classes: each vendor spells
    timeouts and rate limits differently, and a responder that only survives the
    failures of the provider it was written against is not portable.
    """
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    with patch.object(agent, "_gemini", side_effect=raised):
        packet = draft_representment(case_file)

    assert packet.degraded is True
    assert expected_marker in packet.generated_by


def test_a_provider_refusal_falls_back_rather_than_returning_nothing(case, monkeypatch):
    """A safety decline is not a transport error, and must not read as success."""
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    with patch.object(agent, "_gemini",
                      side_effect=ProviderUnavailable("model declined the request")):
        packet = draft_representment(case_file)

    assert packet.degraded is True
    assert "declined" in packet.generated_by


def test_unparseable_json_falls_back(case, monkeypatch):
    """Structured-output modes vary in strictness between providers; ours does not."""
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    with patch.object(agent, "_gemini", side_effect=json.JSONDecodeError("bad", "{", 0)):
        packet = draft_representment(case_file)

    assert packet.degraded is True
    assert "JSONDecodeError" in packet.generated_by


def test_a_response_that_does_not_validate_falls_back(case, monkeypatch):
    """A malformed packet must never reach an acquirer - nor take the endpoint down.

    This is why the response is validated here rather than trusted from the SDK: a
    provider that returns a confidence of 4.2 or an invented reason code is caught on
    our side regardless of how loose its own schema enforcement is.
    """
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    for bad in (
        {"recommendation": "represent", "confidence": 4.2,
         "summary": "s", "argument": "a"},                       # out-of-range confidence
        {"recommendation": "sue_them", "confidence": 0.5,
         "summary": "s", "argument": "a"},                       # unknown recommendation
        {"recommendation": "represent", "confidence": -1.0,
         "summary": "s", "argument": "a"},                       # negative confidence
        {"recommendation": "represent"},                         # missing everything else
    ):
        with patch.object(agent, "_gemini", return_value=bad):
            packet = draft_representment(case_file)

        assert packet.degraded is True
        assert "invalid response" in packet.generated_by


def test_a_valid_provider_response_is_used_as_is(case, monkeypatch):
    """The happy path, so the fallback tests above are not passing vacuously."""
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    drafted = _valid_packet(recommendation="accept_liability", confidence=0.2,
                            summary="Concede.", argument="Evidence is thin.")

    with patch.object(agent, "_gemini", return_value=drafted.model_dump()):
        packet = draft_representment(case_file)

    assert packet.degraded is False
    assert packet.recommendation == "accept_liability"
    assert packet.confidence == pytest.approx(0.2)
    assert packet.generated_by.startswith("gemini:")


# --------------------------------------------------------------------------- #
# Judgement
# --------------------------------------------------------------------------- #
def test_a_confirmed_fraud_is_conceded_rather_than_fought(audit_db):
    """A responder that always fights is a spam cannon.

    Representing a dispute the merchant will lose costs the filing fee again and
    worsens their win rate with the acquirer. Conceding is a real outcome.
    """
    decision_id = _decision(audit_db)
    audit_db.record_disposition(decision_id, "confirmed_fraud", reviewer="analyst-1")

    case_file = build_case_file(decision_id, "unauthorised transaction", store=audit_db)
    packet = deterministic_packet(case_file, "test")

    assert packet.recommendation == "accept_liability"
    assert packet.confidence < 0.5


def test_a_payment_the_engine_cleared_is_represented(audit_db):
    decision_id = _decision(audit_db, decision="ACCEPT", fraud_probability=0.004,
                            reasons=[])
    case_file = build_case_file(decision_id, "goods not received", store=audit_db)
    packet = deterministic_packet(case_file, "test")

    assert packet.recommendation == "represent"


@pytest.mark.parametrize(
    ("complaint", "expected"),
    [
        ("Cardholder did not authorise this", "FRAUD"),
        ("goods were never delivered", "GOODS_NOT_RECEIVED"),
        ("item arrived defective", "GOODS_NOT_AS_DESCRIBED"),
        ("I was charged twice", "DUPLICATE_PROCESSING"),
        ("something else entirely", "CHARGEBACK"),
    ],
)
def test_the_reason_code_is_triaged_deterministically_not_chosen_by_a_model(
    audit_db, complaint, expected
):
    """The reason code decides which evidence the packet must carry.

    Letting a language model pick it meant letting it decide what evidence was
    required, which is backwards - and non-reproducible, so two runs could demand
    different proof for the same complaint. It is keyword triage now, and it always
    lands on a code Razorpay recognises.
    """
    decision_id = _decision(audit_db, transaction_id=f"tx-{complaint[:8]}")
    result = respond_to_dispute(decision_id, complaint, store=audit_db)

    assert result["reason_code"] == expected
    assert result["reason_code"] in REASON_CODES
    assert result["dispute"]["reason_description"] == REASON_CODES[expected]


def test_every_packet_names_what_the_issuer_will_argue_back(case):
    """Listing the counter-arguments is what makes the confidence number mean anything."""
    _, _, case_file = case
    packet = deterministic_packet(case_file, "test")

    assert packet.issuer_rebuttals
    assert all(r.strip() for r in packet.issuer_rebuttals)


def test_evidence_items_always_cite_a_source(case):
    _, _, case_file = case
    packet = deterministic_packet(case_file, "test")

    assert packet.compelling_evidence
    assert all(item.source.strip() for item in packet.compelling_evidence)


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
def test_provenance_is_stamped_by_the_module_not_the_model(case, monkeypatch):
    """A packet that could describe its own origin could describe it wrongly.

    The schema handed to the provider contains `generated_by` and `degraded`, and
    whatever comes back in them is overwritten. Otherwise a degraded draft could claim
    to be a full one, which is the single lie that matters here.
    """
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    lying = _valid_packet(generated_by="a-model-that-does-not-exist", degraded=True)

    with patch.object(agent, "_gemini", return_value=lying.model_dump()):
        packet = draft_representment(case_file)

    assert packet.generated_by == f"gemini:{agent.GEMINI_MODEL}"
    assert packet.degraded is False


def test_the_provider_is_never_given_tools_or_the_scoring_path(case, monkeypatch):
    """The boundary that keeps the decision auditable.

    The adapter receives three things: a system prompt, a user prompt, and a JSON
    schema. No tools, no ledger handle, no model. If it ever gained the ability to
    fetch its own evidence or change the score, a held payment would stop being
    reproducible - so the contract is deliberately too narrow to allow it.
    """
    _, _, case_file = case
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test")

    with patch.object(agent, "_gemini", return_value=_valid_packet().model_dump()) as call:
        draft_representment(case_file)

    (system_prompt, user_prompt, schema), kwargs = call.call_args
    assert kwargs == {}
    assert isinstance(system_prompt, str) and isinstance(user_prompt, str)
    assert schema is agent.PACKET_SCHEMA
    # The recorded probability is passed in as evidence, never as something to redo.
    assert "fraud_probability" in user_prompt
    assert "predict_proba" not in user_prompt


def test_the_schema_pins_the_recommendation_to_two_outcomes(case):
    """Enumerated in the schema, not merely requested in the prompt.

    A prompt can be ignored; an enum in a JSON Schema is enforced by the provider's
    structured-output mode and, failing that, by validation on our side. `represent`
    and `accept_liability` are the only two things a responder may conclude.
    """
    enum = agent.PACKET_SCHEMA["properties"]["recommendation"]["enum"]
    assert set(enum) == {"represent", "accept_liability"}

    bounds = agent.PACKET_SCHEMA["properties"]["confidence"]
    assert bounds["minimum"] == 0.0 and bounds["maximum"] == 1.0


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #
def test_respond_to_dispute_returns_packet_and_case_file(audit_db):
    decision_id = _decision(audit_db)
    result = respond_to_dispute(decision_id, "unauthorised", store=audit_db)

    assert result["decision_id"] == decision_id
    assert result["reason_code_label"] in REASON_CODES.values()
    assert result["dispute"]["entity"] == "dispute"
    assert result["packet"]["argument"].strip()
    assert result["case_file"]["decision_id"] == decision_id


def test_a_dispute_is_persisted_and_readable_afterwards(audit_db):
    """What was submitted, and on what evidence, has to stay answerable."""
    decision_id = _decision(audit_db)
    result = respond_to_dispute(decision_id, "unauthorised", store=audit_db)

    stored = audit_db.record_dispute(decision_id, "unauthorised", result["packet"])
    record = audit_db.get_dispute(stored["dispute_id"])

    assert record["decision_id"] == decision_id
    assert record["packet"]["argument"] == result["packet"]["argument"]
    assert record["degraded"] is True
    assert audit_db.disputes_for(decision_id)[0]["dispute_id"] == stored["dispute_id"]


def test_a_dispute_against_a_missing_decision_raises(audit_db):
    with pytest.raises(KeyError):
        audit_db.record_dispute("dec-nope", "unauthorised", {"reason_code": "VISA_10.4"})


def test_degraded_drafts_are_counted_in_the_operating_stats(audit_db):
    """An ops lead needs to know how many packets went out without a model pass."""
    decision_id = _decision(audit_db)
    result = respond_to_dispute(decision_id, "unauthorised", store=audit_db)
    audit_db.record_dispute(decision_id, "unauthorised", result["packet"])

    stats = audit_db.stats()
    assert stats["disputes_raised"] == 1
    assert stats["packets_drafted_degraded"] == 1
