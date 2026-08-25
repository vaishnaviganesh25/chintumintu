"""FinGuard Module 6 - the chargeback evidence responder.

Detection stops a loss before it happens. This handles the ones that got through:
when a payment is disputed, it reconstructs the case from the decision ledger and
drafts the representment packet the acquirer submits back to the network.

This is the only place in FinGuard where a language model runs, and the boundaries
around it are deliberate:

**The model never touches the score.** A blocked payment has to be reproducible and
explainable months later, and a non-deterministic component in the decision path
would destroy both. The Random Forest decides; the model here writes.

**The evidence set is retrieved by code, not by the model.** It would have been easy
to hand the model a set of ledger tools and let it decide what to look up. It would also
have made the evidence behind a submitted document non-reproducible - run it twice,
get different citations. `build_case_file` is deterministic and fully logged; the
model's job is synthesis under a schema, not discovery.

**Reason codes come from an enumerated list.** Asking a model to recall a network
reason code from memory is asking for a plausible, wrong one on a document that goes
to an acquirer. The schema below only permits codes this module knows.

**It is allowed to recommend giving up.** A responder that always fights is not a risk
tool, it is a spam cannon - and representing a dispute you will lose costs the fee
again and worsens the merchant's win rate. `accept_liability` is a first-class outcome.

**It degrades to a deterministic draft.** No API key, a timeout, a refusal, a schema
mismatch - any of these and the module assembles the packet from the ledger with
templates instead. Every packet says which path produced it. A dispute has a filing
deadline; a fraud team that gets nothing because an LLM was unreachable has been
failed by its tooling.

**The provider is pluggable.** Adapters for Gemini and Claude sit behind one narrow
function - take a system prompt, a user prompt and a JSON schema, return a dict - and
the module picks whichever has credentials configured. Two consequences worth stating:
the schema is sent as plain JSON Schema rather than an SDK-specific object, because
that is the form both providers accept most reliably; and the response is validated
against the Pydantic model *here*, so a provider whose structured-output mode is
loose still cannot put a malformed packet in front of an acquirer.

Set one of these and the module uses it, in this order:

    GEMINI_API_KEY / GOOGLE_API_KEY     -> Gemini
    ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN -> Claude

With neither, everything still works and every packet comes back `degraded: true`.

    python chargeback_agent.py <decision_id>
"""

from __future__ import annotations

import json
import logging
import os
import textwrap
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from audit_store import AuditStore, store as default_store
from razorpay_client import (
    REASON_DESCRIPTIONS,
    DisputeEntity,
    DisputeEvidence,
    build_dispute_entity,
    to_paise,
)

log = logging.getLogger("finguard.chargeback")

# Per-provider defaults. Overridable with FINGUARD_LLM_MODEL when a deployment wants
# a different tier - a cheaper model is a perfectly reasonable choice here, since the
# task is synthesis over a case file rather than open-ended reasoning.
GEMINI_MODEL = os.environ.get("FINGUARD_LLM_MODEL", "gemini-3.7-flash")
ANTHROPIC_MODEL = os.environ.get("FINGUARD_LLM_MODEL", "claude-opus-5")

MAX_TOKENS = 8_000
# A dispute has a filing deadline measured in days, so a slow answer is still useful -
# but not an unbounded one, because this runs inside a request handler.
TIMEOUT_SECONDS = 90.0

# The reason code is no longer the model's to choose.
#
# It arrives on the dispute entity, set by the issuer, and it determines which evidence
# the packet must carry - shipping proof for a non-delivery claim, access logs for a
# digital one. Letting a language model pick it meant letting it decide what evidence
# was required, which is backwards. `razorpay_client.classify_reason` does the triage
# deterministically and this module reads the result.
REASON_CODES = REASON_DESCRIPTIONS


# --------------------------------------------------------------------------- #
# Output schema
# --------------------------------------------------------------------------- #
class EvidenceItem(BaseModel):
    """One piece of compelling evidence, tied to where it came from."""

    item: str = Field(..., description="What the evidence is, in the acquirer's language.")
    detail: str = Field(..., description="The specific value or finding.")
    source: str = Field(
        ...,
        description="Where it came from - a ledger field, the SHAP vector, sender history. "
                    "Never a guess.",
    )


class RepresentmentPacket(BaseModel):
    """A submittable dispute response, or a reasoned decision not to submit one.

    The prose fields map onto Razorpay's `evidence` sub-object - `summary` and
    `explanation_letter` are their field names, not ours. `evidence_cited` is local:
    it records where each claim came from, which the API has no field for and an
    auditor very much wants.
    """

    recommendation: Literal["represent", "accept_liability"] = Field(
        ...,
        description="represent = fight the dispute. accept_liability = concede, because "
                    "the evidence does not support a win and representing costs the fee again.",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Probability of winning if represented. Be conservative - an "
                    "over-confident packet wastes a filing.",
    )
    summary: str = Field(
        ...,
        description="Two or three sentences an ops lead can act on. Becomes "
                    "`evidence.summary` on the Razorpay dispute.",
    )
    compelling_evidence: list[EvidenceItem] = Field(
        default_factory=list,
        description="Evidence supporting the merchant, each tied to where it came "
                    "from. Empty is a valid and honest answer.",
    )
    argument: str = Field(
        ...,
        description="The narrative submitted to the issuer, becoming "
                    "`evidence.explanation_letter`. Factual, no adjectives, every "
                    "claim traceable to the case file.",
    )
    issuer_rebuttals: list[str] = Field(
        default_factory=list,
        description="What the issuer will argue back. Listing these is what makes the "
                    "confidence number mean something.",
    )
    generated_by: str = Field(
        default="unknown",
        description="Which path produced this packet - the model, or the deterministic "
                    "fallback. Set by the module, never by the model.",
    )
    degraded: bool = Field(
        default=False,
        description="True when the language model was unavailable and this is a "
                    "template draft needing a human pass.",
    )


SYSTEM_PROMPT = """\
You are a disputes analyst at an Indian payment gateway, preparing a representment \
packet for a merchant whose transaction has been charged back.

You are given a case file assembled from the fraud engine's decision ledger. Work \
only from it. Every claim in the packet must be traceable to a field in the case \
file; if the evidence is not there, say so rather than inferring it.

Two things matter more than winning:

Recommend `accept_liability` when the evidence genuinely does not support a win. \
Representing a losing dispute costs the merchant the filing fee a second time and \
worsens their win rate with the acquirer. A confident, well-argued concession is a \
better outcome than a hopeful representment.

Be conservative with `confidence`. It is the probability the issuer rules for the \
merchant. If the fraud engine itself scored this payment as high risk and held or \
challenged it, that is evidence *against* the merchant's position, and you should say \
so plainly rather than arguing around it.

Write the argument the way an acquirer reads them: short, factual, no adjectives, no \
appeals to fairness. Cite specific values.\
"""


# --------------------------------------------------------------------------- #
# Deterministic retrieval
# --------------------------------------------------------------------------- #
def build_case_file(
    decision_id: str,
    dispute_reason: str,
    store: AuditStore | None = None,
    history_window: int = 10,
    dispute: DisputeEntity | None = None,
) -> dict[str, Any]:
    """Assemble everything known about a disputed payment. No model involved.

    Deliberately deterministic: the evidence behind a document sent to an acquirer has
    to be the same every time it is built, and has to be reconstructable during an
    audit. Letting a model choose what to look up would make neither true.
    """
    store = store or default_store
    decision = store.get_decision(decision_id)
    if decision is None:
        raise KeyError(decision_id)

    # The sender's other payments give the issuer's "this was not the cardholder"
    # argument something to push against - or confirm it.
    related = [
        d for d in store.recent_decisions(limit=200)
        if d["sender_vpa"] == decision["sender_vpa"] and d["decision_id"] != decision_id
    ][:history_window]

    # Payments to the same receiver: a receiver with a history of disputes is a
    # different case from a first-time one.
    same_receiver = [
        d for d in store.recent_decisions(limit=200)
        if d["receiver_vpa"] == decision["receiver_vpa"] and d["decision_id"] != decision_id
    ][:history_window]

    concepts = decision["shap_concepts"]
    top_drivers = sorted(concepts.items(), key=lambda kv: -abs(kv[1]))[:6]

    dispute = dispute or build_dispute_entity(decision, dispute_reason)

    return {
        "decision_id": decision_id,
        "dispute_reason_stated_by_issuer": dispute_reason,
        # The Razorpay dispute this packet answers. Its reason code decides which
        # evidence is required, and `respond_by` is the clock the whole exercise runs
        # against - both belong in front of whoever is drafting.
        "dispute": dispute.model_dump(exclude_none=True),
        "hours_left_to_respond": round(dispute.hours_to_respond(), 1),
        "payment": {
            "transaction_id": decision["transaction_id"],
            "amount_inr": decision["amount"],
            "timestamp": decision["txn_timestamp"],
            "sender_vpa": decision["sender_vpa"],
            "receiver_vpa": decision["receiver_vpa"],
            "receiver_vpa_age_days": decision["receiver_vpa_age_days"],
            "sender_city": decision["sender_city"],
        },
        "engine_decision": {
            "action": decision["decision"],
            "fraud_probability": decision["fraud_probability"],
            "threshold_in_force": decision["threshold"],
            "threshold_policy": decision["threshold_policy"],
            "model": decision["model_name"],
            "model_trained_at": decision["model_trained_at"],
            "scored_at": decision["scored_at"],
            "latency_ms": decision["latency_ms"],
        },
        "explanation": {
            "reasons_given_at_the_time": decision["reasons"],
            "top_shap_drivers": [{"concept": c, "signed_contribution": v} for c, v in top_drivers],
            "note": (
                "Positive contributions pushed the payment towards fraud, negative "
                "argued against. These are the values recorded at decision time, not "
                "recomputed now."
            ),
        },
        "analyst_dispositions": decision["dispositions"],
        "sender_recent_payments": [
            {
                "amount_inr": d["amount"], "receiver_vpa": d["receiver_vpa"],
                "action": d["decision"], "fraud_probability": d["fraud_probability"],
                "scored_at": d["scored_at"],
            }
            for d in related
        ],
        "other_payments_to_this_receiver": [
            {
                "amount_inr": d["amount"], "sender_vpa": d["sender_vpa"],
                "action": d["decision"], "fraud_probability": d["fraud_probability"],
            }
            for d in same_receiver
        ],
        "reason_code_meanings": REASON_CODES,
    }


# --------------------------------------------------------------------------- #
# The fallback
# --------------------------------------------------------------------------- #
def deterministic_packet(case_file: dict[str, Any], why: str) -> RepresentmentPacket:
    """A usable draft built from templates when the model is unavailable.

    Not a placeholder. A dispute has a filing deadline, and an ops team that receives
    nothing because a third-party API was down has been failed by its tooling. This
    draft is weaker prose than the model produces and it says so, but it carries the
    same evidence and reaches the same recommendation by the same rule.
    """
    payment = case_file["payment"]
    engine = case_file["engine_decision"]

    risky = engine["fraud_probability"] >= engine["threshold_in_force"]
    confirmed_fraud = any(
        d["outcome"] == "confirmed_fraud" for d in case_file["analyst_dispositions"]
    )

    evidence = [
        EvidenceItem(
            item="Real-time risk assessment on file",
            detail=(f"Scored {engine['fraud_probability']:.4f} by {engine['model']} at "
                    f"{engine['scored_at']}, action {engine['action']}."),
            source="decision ledger",
        ),
        EvidenceItem(
            item="Receiver account age at transaction time",
            detail=f"{payment['receiver_vpa_age_days']} days",
            source="decision ledger",
        ),
    ]
    if case_file["sender_recent_payments"]:
        evidence.append(EvidenceItem(
            item="Prior payment history for this payer",
            detail=f"{len(case_file['sender_recent_payments'])} earlier payments on record",
            source="decision ledger",
        ))

    if confirmed_fraud or (risky and engine["action"] == "HOLD"):
        recommendation: Literal["represent", "accept_liability"] = "accept_liability"
        confidence = 0.15
        summary = (
            "Recommend conceding. The engine flagged this payment at the time and the "
            "evidence on file supports the issuer's position rather than the merchant's."
        )
    else:
        recommendation = "represent"
        confidence = 0.55
        summary = (
            "Recommend representing. The payment was assessed in real time and cleared, "
            "and the record supports that assessment."
        )

    argument = textwrap.dedent(f"""\
        Payment of Rs.{payment['amount_inr']:,.2f} from {payment['sender_vpa']} to
        {payment['receiver_vpa']} on {payment['timestamp']}.

        The transaction was scored by an automated risk engine before authorisation,
        at {engine['scored_at']}, producing a fraud probability of
        {engine['fraud_probability']:.4f} against a decision threshold of
        {engine['threshold_in_force']:.4f} under the '{engine['threshold_policy']}'
        policy. The resulting action was {engine['action']}. The receiving account was
        {payment['receiver_vpa_age_days']} days old at the time.

        Factors recorded at decision time: {'; '.join(case_file['explanation']['reasons_given_at_the_time']) or 'none recorded'}.
    """).strip()

    return RepresentmentPacket(
        recommendation=recommendation,
        confidence=confidence,
        summary=summary,
        compelling_evidence=evidence,
        argument=argument,
        issuer_rebuttals=[
            "The issuer may argue the cardholder did not authorise the payment "
            "regardless of the merchant's risk assessment.",
            "A recently created receiving account weakens the merchant's position.",
        ],
        generated_by=f"deterministic-fallback ({why})",
        degraded=True,
    )


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
# Each adapter takes the same three arguments and returns a plain dict, so the rest
# of the module never learns which vendor answered. Validation happens once, here,
# against the Pydantic schema - not inside an adapter, and not inside an SDK.
#
# The schema goes over the wire as JSON Schema rather than as a Pydantic class.
# Provider SDKs differ in how faithfully they translate a Pydantic model, and a
# mistranslation shows up as a silently different document rather than an error.
# Sending the schema we actually mean removes that whole class of surprise.
PACKET_SCHEMA = RepresentmentPacket.model_json_schema()


class ProviderUnavailable(RuntimeError):
    """Raised by an adapter when it cannot produce a packet. Always caught."""


def _gemini(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Draft with Gemini.

    Written against `google-genai`. The SDK has moved surface recently - older builds
    expose `models.generate_content(config=...)`, newer ones `interactions.create`
    - so both are attempted and whichever the installed version provides is used.
    Sniffing the client rather than pinning a version keeps this working across the
    move; if neither exists the adapter reports unavailable and the caller falls back.
    """
    try:
        from google import genai
    except ImportError as exc:
        raise ProviderUnavailable("google-genai SDK not installed") from exc

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    combined = f"{system_prompt}\n\n{user_prompt}"

    if hasattr(client, "interactions"):
        interaction = client.interactions.create(
            model=GEMINI_MODEL,
            input=combined,
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": schema},
        )
        text = interaction.output_text
    elif hasattr(client, "models"):
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=combined,
            config={"response_mime_type": "application/json", "response_schema": schema},
        )
        text = response.text
    else:
        raise ProviderUnavailable("google-genai client exposes no known generate surface")

    if not text or not text.strip():
        raise ProviderUnavailable("Gemini returned an empty response")
    return json.loads(text)


def _anthropic(system_prompt: str, user_prompt: str, schema: dict) -> dict:
    """Draft with Claude, using the Messages API's structured output mode."""
    try:
        import anthropic
    except ImportError as exc:
        raise ProviderUnavailable("anthropic SDK not installed") from exc

    client = anthropic.Anthropic(timeout=TIMEOUT_SECONDS, max_retries=2)
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )

    # A safety decline arrives as HTTP 200 with stop_reason "refusal", not an
    # exception. Reading content without checking would yield an empty packet and
    # call it a success.
    if getattr(response, "stop_reason", None) == "refusal":
        raise ProviderUnavailable("model declined the request")

    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text.strip():
        raise ProviderUnavailable("model returned no text block")
    return json.loads(text)


def available_provider() -> tuple[str, Any] | None:
    """Whichever provider has credentials, or None. Gemini first, then Claude.

    Credentials decide, not configuration: there is no provider setting to get out of
    step with the environment, and adding a key is the whole of the setup.
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return f"gemini:{GEMINI_MODEL}", _gemini
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return f"anthropic:{ANTHROPIC_MODEL}", _anthropic
    return None


# --------------------------------------------------------------------------- #
# The model call
# --------------------------------------------------------------------------- #
def draft_representment(case_file: dict[str, Any]) -> RepresentmentPacket:
    """Draft the packet with whichever model is configured, falling back on any failure.

    Every failure mode is a fallback rather than an exception: no credentials, an
    unreachable API, a rate limit, a refusal, a response that will not parse or will
    not validate. The caller always gets a packet and always learns which path
    produced it.
    """
    provider = available_provider()
    if provider is None:
        log.warning("No LLM credentials found; drafting deterministically.")
        return deterministic_packet(case_file, "no API credentials configured")

    label, call = provider
    user_prompt = (
        "Draft a representment packet for the disputed payment below.\n\n"
        "```json\n" + json.dumps(case_file, indent=2, default=str) + "\n```"
    )

    try:
        raw = call(SYSTEM_PROMPT, user_prompt, PACKET_SCHEMA)
        packet = RepresentmentPacket.model_validate(raw)
    except ProviderUnavailable as exc:
        log.warning("%s unavailable (%s); drafting deterministically.", label, exc)
        return deterministic_packet(case_file, str(exc))
    except (json.JSONDecodeError, ValidationError) as exc:
        # A malformed packet must never reach an acquirer - and must never take the
        # endpoint down either.
        log.warning("%s returned an invalid packet (%s); drafting deterministically.",
                    label, type(exc).__name__)
        return deterministic_packet(case_file, f"invalid response ({type(exc).__name__})")
    except Exception as exc:                          # noqa: BLE001
        # Transport errors, rate limits, timeouts - every SDK spells these differently,
        # and none of them is worth failing a filing deadline over.
        log.warning("%s call failed (%s); drafting deterministically.",
                    label, type(exc).__name__)
        return deterministic_packet(case_file, f"{type(exc).__name__}")

    # Provenance is stamped here, never by the model - a packet able to describe its
    # own origin is able to describe it wrongly, and "degraded" is the one field that
    # must always be true.
    packet.generated_by = label
    packet.degraded = False
    return packet


def to_razorpay_evidence(
    packet: RepresentmentPacket,
    case_file: dict[str, Any],
    submitted_at: datetime | None = None,
) -> DisputeEvidence:
    """Map a drafted packet onto Razorpay's `evidence` sub-object.

    The mapping is code, not prompt. Which evidence field a claim belongs in follows
    from the reason code - a non-delivery dispute needs `shipping_proof`, a digital
    one needs `access_activity_log` - and that is a rule, not a judgement. Leaving it
    to the model would mean the same evidence landing in different fields on different
    runs, which an acquirer would reject and an auditor could not reconcile.

    Fields hold document ids in the live API. Here they hold ledger references, which
    is the honest local equivalent: a pointer to where the claim came from rather than
    an assertion with no provenance.
    """
    reason = case_file["dispute"]["reason_code"]
    decision_ref = f"finguard:decision:{case_file['decision_id']}"

    evidence = DisputeEvidence(
        amount=to_paise(case_file["payment"]["amount_inr"]),
        summary=packet.summary,
        explanation_letter=[packet.argument],
        # The risk assessment made before authorisation, and the account history
        # behind it. Razorpay has no field for "our model scored this", so it goes in
        # `others` with its provenance rather than being forced into a proof field it
        # is not.
        others=[
            {
                "type": "risk_assessment",
                "description": (
                    f"Scored {case_file['engine_decision']['fraud_probability']:.4f} by "
                    f"{case_file['engine_decision']['model']} at "
                    f"{case_file['engine_decision']['scored_at']}, action "
                    f"{case_file['engine_decision']['action']}."
                ),
                "reference": decision_ref,
            },
            *(
                {"type": "cited_evidence", "description": f"{item.item}: {item.detail}",
                 "reference": item.source}
                for item in packet.compelling_evidence
            ),
        ],
        submitted_at=int((submitted_at or datetime.now(timezone.utc)).timestamp()),
    )

    # Reason-specific proof fields. Populated with what the ledger can actually
    # evidence; a field the ledger cannot speak to is left null rather than filled
    # with something that sounds right.
    if reason in ("FRAUD", "CHARGEBACK"):
        evidence.access_activity_log = [decision_ref]
        evidence.billing_proof = [f"finguard:payment:{case_file['payment']['transaction_id']}"]
    elif reason == "GOODS_NOT_RECEIVED":
        evidence.shipping_proof = None          # a payments engine has no shipping data
        evidence.proof_of_service = [decision_ref]
    elif reason == "GOODS_NOT_AS_DESCRIBED":
        evidence.term_and_conditions = None
        evidence.proof_of_service = [decision_ref]
    elif reason == "DUPLICATE_PROCESSING":
        evidence.billing_proof = [f"finguard:payment:{case_file['payment']['transaction_id']}"]
    elif reason == "CREDIT_NOT_PROCESSED":
        evidence.refund_confirmation = None     # the ledger records decisions, not refunds
        evidence.refund_cancellation_policy = None

    return evidence


def respond_to_dispute(
    decision_id: str,
    dispute_reason: str,
    store: AuditStore | None = None,
) -> dict[str, Any]:
    """End to end: ledger -> Razorpay dispute -> case file -> packet -> evidence.

    Returns the dispute with the drafted evidence attached, so the caller holds an
    object shaped exactly like one Razorpay would return - and one that could be
    submitted through their contest endpoint without reshaping.
    """
    store = store or default_store
    decision = store.get_decision(decision_id)
    if decision is None:
        raise KeyError(decision_id)

    dispute = build_dispute_entity(decision, dispute_reason)
    case_file = build_case_file(decision_id, dispute_reason, store=store, dispute=dispute)
    packet = draft_representment(case_file)

    # Evidence is only attached when the packet actually fights. Filing evidence
    # alongside a concession is a contradiction the acquirer would have to resolve.
    if packet.recommendation == "represent":
        dispute.evidence = to_razorpay_evidence(packet, case_file)

    return {
        "decision_id": decision_id,
        "drafted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason_code": dispute.reason_code,
        "reason_code_label": REASON_CODES[dispute.reason_code],
        "hours_left_to_respond": round(dispute.hours_to_respond(), 1),
        "dispute": dispute.model_dump(exclude_none=True),
        "packet": packet.model_dump(),
        "case_file": case_file,
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage: python chargeback_agent.py <decision_id> [dispute reason]")
        raise SystemExit(1)

    default_store.connect()
    try:
        result = respond_to_dispute(
            sys.argv[1],
            " ".join(sys.argv[2:]) or "Cardholder reports unauthorised transaction",
        )
    finally:
        default_store.close()

    packet = result["packet"]
    print(f"\n{result['reason_code']} - {result['reason_code_label']}")
    print(f"Respond within  : {result['hours_left_to_respond']:.0f} hours")
    print(f"Recommendation : {packet['recommendation']}  (confidence {packet['confidence']:.2f})")
    print(f"Drafted by     : {packet['generated_by']}")
    print(f"\n{packet['summary']}\n")
    print("Compelling evidence:")
    for item in packet["compelling_evidence"]:
        print(f"  - {item['item']}: {item['detail']}  [{item['source']}]")
    print("\nArgument:")
    for line in packet["argument"].splitlines():
        print(f"  {line}")
    if packet["issuer_rebuttals"]:
        print("\nExpect the issuer to argue:")
        for rebuttal in packet["issuer_rebuttals"]:
            print(f"  - {rebuttal}")
