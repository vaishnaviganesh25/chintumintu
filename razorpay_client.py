"""FinGuard Module 9 - Razorpay dispute objects, and an optional live adapter.

FinGuard's disputes were its own invention: a reason code, a respond-by date, a bespoke
evidence list. Plausible, and not something that would round-trip against a real API.
This module reshapes them to Razorpay's actual `dispute` entity, field for field, and
adds a thin client that talks to the live API when credentials exist.

Two things worth knowing before reading further.

**You cannot create a dispute through the API, and that is not a gap in this module.**
Razorpay exposes fetch-all, fetch-by-id, accept and contest. There is no create
endpoint, because disputes originate at the issuer or the network - a merchant never
raises one against itself. So test-mode credentials would return an empty list and
demo nothing. What matters is that the object shape is authentic and the code path is
real, which is what this file provides.

**Amounts are integer subunits.** Razorpay counts paise; the model, the cost policy
and every report in this project count rupees. Mixing them is a factor-of-100 error
that looks entirely plausible in a log line, so the conversion happens here and only
here, in two named functions with tests around them.

Set `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` to fetch real disputes. Unset, the
ledger serves its own - identically shaped.
"""

from __future__ import annotations

import base64
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

log = logging.getLogger("finguard.razorpay")

API_BASE = "https://api.razorpay.com/v1"
REQUEST_TIMEOUT_S = 20.0

# RBI's harmonised turnaround time for customer-raised disputes. A representment has
# to be filed inside it, which is why `respond_by` is on the entity at all.
DISPUTE_TAT_DAYS = 30

DisputeStatus = Literal["open", "under_review", "won", "lost", "closed"]
DisputePhase = Literal["fraud", "retrieval", "chargeback", "pre_arbitration", "arbitration"]

# The network reason code carried through to the merchant. Razorpay surfaces the
# scheme's own code rather than inventing one, so these are the scheme values.
REASON_DESCRIPTIONS: dict[str, str] = {
    "FRAUD": "Cardholder does not recognise the transaction",
    "CHARGEBACK": "Cardholder disputes the transaction with their issuer",
    "GOODS_NOT_RECEIVED": "Goods or services were not received",
    "GOODS_NOT_AS_DESCRIBED": "Goods or services were not as described",
    "DUPLICATE_PROCESSING": "The transaction was processed more than once",
    "CREDIT_NOT_PROCESSED": "An agreed refund was not issued",
}

# Which phase a reason lands in. `fraud` disputes skip retrieval and go straight to a
# chargeback, which shortens the clock - the reason the responder surfaces `respond_by`
# rather than assuming a fixed 30 days is always available.
REASON_PHASE: dict[str, DisputePhase] = {
    "FRAUD": "chargeback",
    "CHARGEBACK": "chargeback",
    "GOODS_NOT_RECEIVED": "retrieval",
    "GOODS_NOT_AS_DESCRIBED": "retrieval",
    "DUPLICATE_PROCESSING": "retrieval",
    "CREDIT_NOT_PROCESSED": "retrieval",
}


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
def to_paise(rupees: float) -> int:
    """Rupees to integer subunits, the only representation Razorpay accepts.

    Rounded rather than truncated: `int(0.1 * 3 * 100)` is 29 in floating point, and a
    dispute that is one paisa short of the payment it contests will be rejected by the
    acquirer for a reason nobody will enjoy diagnosing.
    """
    return round(float(rupees) * 100)


def to_rupees(paise: int) -> float:
    """Subunits back to rupees, for anything that has to face a human or the model."""
    return round(int(paise) / 100, 2)


def _rzp_id(prefix: str) -> str:
    """A Razorpay-shaped identifier: prefix plus 14 alphanumerics."""
    return f"{prefix}{uuid.uuid4().hex[:14]}"


def _unix(dt: datetime) -> int:
    return int(dt.replace(tzinfo=dt.tzinfo or UTC).timestamp())


# --------------------------------------------------------------------------- #
# The entity
# --------------------------------------------------------------------------- #
class DisputeEvidence(BaseModel):
    """Razorpay's evidence sub-object.

    These field names are the contract. The chargeback responder used to emit a
    free-form `compelling_evidence` list, which read well and could not be submitted -
    an acquirer wants `shipping_proof`, not prose. Targeting the real fields is what
    turns the packet from a plausible document into one that could actually be filed.

    Every proof field holds document ids in the live API. Here they hold the ledger
    references the evidence was drawn from, which is the honest local equivalent: a
    pointer to where the claim came from rather than a claim with no provenance.
    """

    amount: int = Field(..., description="Amount being contested, in paise.")
    summary: str | None = None
    shipping_proof: list[str] | None = None
    billing_proof: list[str] | None = None
    cancellation_proof: list[str] | None = None
    customer_communication: list[str] | None = None
    proof_of_service: list[str] | None = None
    explanation_letter: list[str] | None = None
    refund_confirmation: list[str] | None = None
    access_activity_log: list[str] | None = None
    refund_cancellation_policy: list[str] | None = None
    term_and_conditions: list[str] | None = None
    others: list[dict[str, Any]] | None = None
    submitted_at: int | None = None


class DisputeEntity(BaseModel):
    """A Razorpay dispute, shaped exactly as their API returns one."""

    id: str
    entity: Literal["dispute"] = "dispute"
    payment_id: str
    amount: int = Field(..., description="Disputed amount in paise.")
    currency: str = "INR"
    amount_deducted: int = Field(0, description="Deducted from balance when lost, in paise.")
    reason_code: str
    reason_description: str
    respond_by: int = Field(..., description="Unix timestamp of the filing deadline.")
    status: DisputeStatus = "open"
    phase: DisputePhase = "chargeback"
    created_at: int
    evidence: DisputeEvidence

    def amount_rupees(self) -> float:
        """Convenience for anything internal, which counts rupees."""
        return to_rupees(self.amount)

    def hours_to_respond(self, now: datetime | None = None) -> float:
        """How long is left to file. Negative once the deadline has passed."""
        reference = now or datetime.now(UTC)
        return (self.respond_by - _unix(reference)) / 3600


def classify_reason(dispute_reason: str) -> str:
    """Map a free-text customer complaint onto a scheme reason code.

    Deterministic keyword triage rather than a model call. This decides which evidence
    the packet needs, and a decision that changes between runs would make the resulting
    document unreproducible - the same objection that keeps the language model out of
    the retrieval path.
    """
    text = dispute_reason.lower()

    # Non-delivery is the phrasing most likely to arrive in a hundred variants, so it
    # matches on the combination of a delivery word and a negation rather than on a
    # fixed list. "goods were never delivered" and "item not received" are the same
    # complaint and must route to the same evidence requirements.
    delivery_words = ("received", "delivered", "arrived", "shipped", "dispatch")
    negations = ("not ", "never ", "n't ", "no ")
    if any(w in text for w in delivery_words) and any(n in text for n in negations):
        return "GOODS_NOT_RECEIVED"

    if "not as described" in text or "defective" in text or "damaged" in text or "wrong item" in text:
        return "GOODS_NOT_AS_DESCRIBED"
    if "duplicate" in text or "charged twice" in text or "double charg" in text:
        return "DUPLICATE_PROCESSING"
    if "refund" in text and ("not" in text or "never" in text):
        return "CREDIT_NOT_PROCESSED"
    # "did not authorise" and "unauthorised" are the same complaint; matching only the
    # closed-up spelling sent the commonest phrasing of the commonest dispute to the
    # generic bucket, and with it the wrong evidence requirements.
    fraud_markers = (
        "unauthoris", "unauthoriz", "not authoris", "not authoriz",
        "did not make", "didn't make", "do not recognise", "does not recognise",
        "not recognise", "not recognize", "fraud", "stolen", "compromis",
    )
    if any(marker in text for marker in fraud_markers):
        return "FRAUD"
    return "CHARGEBACK"


def build_dispute_entity(
    decision: dict[str, Any],
    dispute_reason: str,
    payment_id: str | None = None,
    raised_at: datetime | None = None,
) -> DisputeEntity:
    """Turn a ledger decision into a Razorpay-shaped dispute against it.

    Synthesised locally because no API creates disputes, but shaped so that swapping in
    a real one changes only where the object comes from, never what the responder does
    with it.
    """
    created = raised_at or datetime.now(UTC)
    reason_code = classify_reason(dispute_reason)
    amount_paise = to_paise(decision["amount"])

    return DisputeEntity(
        id=_rzp_id("disp_"),
        payment_id=payment_id or decision.get("transaction_id") or _rzp_id("pay_"),
        amount=amount_paise,
        amount_deducted=0,                       # nothing is deducted until it is lost
        reason_code=reason_code,
        reason_description=REASON_DESCRIPTIONS[reason_code],
        respond_by=_unix(created + timedelta(days=DISPUTE_TAT_DAYS)),
        status="open",
        phase=REASON_PHASE[reason_code],
        created_at=_unix(created),
        evidence=DisputeEvidence(amount=amount_paise),
    )


# --------------------------------------------------------------------------- #
# The live adapter
# --------------------------------------------------------------------------- #
class RazorpayUnavailableError(RuntimeError):
    """Raised when the live API cannot be reached or is not configured."""


class RazorpayClient:
    """Optional adapter over the live Disputes API.

    Same posture as the LLM provider layer: credentials decide whether it is used,
    nothing depends on it, and its absence is a documented state rather than an error.
    Basic auth over HTTPS - key id as username, secret as password, which is what
    Razorpay's API expects.
    """

    def __init__(self, key_id: str | None = None, key_secret: str | None = None) -> None:
        self.key_id = key_id or os.environ.get("RAZORPAY_KEY_ID")
        self.key_secret = key_secret or os.environ.get("RAZORPAY_KEY_SECRET")

    @property
    def configured(self) -> bool:
        return bool(self.key_id and self.key_secret)

    @property
    def mode(self) -> str:
        """`test`, `live` or `unconfigured`, read off the key prefix.

        Surfaced on the health endpoint. Anyone demoing should be able to see at a
        glance that they are pointed at test mode, and anyone in production should be
        able to see that they are not.
        """
        if not self.configured:
            return "unconfigured"
        return "test" if str(self.key_id).startswith("rzp_test") else "live"

    def _auth_header(self) -> dict[str, str]:
        token = base64.b64encode(f"{self.key_id}:{self.key_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise RazorpayUnavailableError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set")
        try:
            import httpx
        except ImportError as exc:                    # pragma: no cover - httpx ships with the API
            raise RazorpayUnavailableError("httpx is not installed") from exc

        try:
            response = httpx.get(f"{API_BASE}{path}", headers=self._auth_header(),
                                 params=params, timeout=REQUEST_TIMEOUT_S)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise RazorpayUnavailableError(f"{type(exc).__name__}: {exc}") from exc

    def fetch_disputes(self, count: int = 20) -> list[DisputeEntity]:
        """Live disputes, newest first. Empty in test mode - see the module docstring."""
        body = self._get("/disputes", {"count": count})
        return [DisputeEntity.model_validate(item) for item in body.get("items", [])]

    def fetch_dispute(self, dispute_id: str) -> DisputeEntity:
        return DisputeEntity.model_validate(self._get(f"/disputes/{dispute_id}"))

    def health(self) -> dict[str, Any]:
        """What to report on the deep health probe."""
        return {
            "status": "configured" if self.configured else "absent",
            "mode": self.mode,
            "note": (
                "Disputes are served from the local ledger. Razorpay has no endpoint "
                "that creates a dispute, so test-mode credentials would add a code "
                "path, not a demo."
            ),
        }


client = RazorpayClient()
