"""FinGuard Module 10 - cross-merchant reputation.

Razorpay's Vulcan announcement (18 August 2026) names four capabilities, and one of
them describes something no individual merchant can do for itself: *network-level
fraud detection - spots fraud visible only across merchants, flagging a stolen card
the moment it's used across unrelated sellers.*

That is a genuinely different signal from anything else in this project. Every other
feature here is computed from what one merchant can see. A payer who was confirmed
fraudulent at a phone reseller this morning is, to an unrelated grocery merchant this
afternoon, a brand-new customer with a clean record. Only the gateway sitting between
them knows otherwise - and the gateway is what FinGuard is modelled as.

**This is a runtime overlay, not a model feature, and the distinction is deliberate.**

Reputation cannot be trained on. At fit time there are no decisions yet, so a
"prior holds" column would be either empty or - worse - back-filled from labels the
model is trying to predict, which is target leakage wearing a convincing disguise. So
the classifier never sees it. The model scores the payment on its own merits, and this
layer then adjusts the *action* with its own stated reason. Two components, two
records, both auditable.

**Only confirmed fraud escalates hard.** A prior HOLD is a model opinion; escalating on
it lets one uncertain decision compound into a chain of them across every merchant a
customer touches, which is how a scoring system quietly builds a blacklist nobody
approved. An analyst disposition is a human conclusion, and that is what carries.

**Escalation only, never de-escalation.** A clean record is the default state of every
new customer, so treating it as positive evidence would just mean scoring first-time
buyers as safer than returning ones. Absence of history is not absence of risk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from audit_store import AuditStore

log = logging.getLogger("finguard.network")

# How far back the consortium view reaches. Seven days is a compromise: long enough to
# catch a card being worked across merchants over a weekend, short enough that a
# customer is not carrying a month-old flag into unrelated purchases.
LOOKBACK = timedelta(days=7)

# A payer touching this many distinct merchants inside the window is behaving like a
# card being tested rather than like a person shopping. Deliberately not tight: real
# people do buy from several merchants in a week, so this only contributes alongside
# other evidence rather than firing on its own.
SPRAY_MERCHANTS = 6

ESCALATION = {"ACCEPT": "STEP_UP", "STEP_UP": "HOLD", "HOLD": "HOLD"}


@dataclass(frozen=True)
class NetworkReputation:
    """What the gateway knows about this payer and payee that the merchant cannot."""

    payer_decisions: int = 0
    payer_actioned: int = 0
    payer_confirmed_fraud: int = 0
    payer_distinct_merchants: int = 0
    receiver_decisions: int = 0
    receiver_actioned: int = 0
    receiver_confirmed_fraud: int = 0
    receiver_distinct_payers: int = 0

    @property
    def has_history(self) -> bool:
        return bool(self.payer_decisions or self.receiver_decisions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "payer_decisions": self.payer_decisions,
            "payer_actioned": self.payer_actioned,
            "payer_confirmed_fraud": self.payer_confirmed_fraud,
            "payer_distinct_merchants": self.payer_distinct_merchants,
            "receiver_decisions": self.receiver_decisions,
            "receiver_actioned": self.receiver_actioned,
            "receiver_confirmed_fraud": self.receiver_confirmed_fraud,
            "receiver_distinct_payers": self.receiver_distinct_payers,
        }


def lookup(store: AuditStore, sender_vpa: str, receiver_vpa: str,
           now: datetime | None = None) -> NetworkReputation:
    """Read both sides' cross-merchant record. Never raises.

    A reputation lookup is an enrichment, not the decision. If the ledger is
    unavailable the payment is still scored and still actioned - it simply loses the
    consortium view, which is the same position a single merchant is in permanently.
    """
    if not store.ready:
        return NetworkReputation()

    cutoff = ((now or datetime.now(timezone.utc)) - LOOKBACK).isoformat(timespec="microseconds")

    try:
        with store._cursor() as cur:                  # noqa: SLF001 - same package
            payer = cur.execute(
                """
                SELECT
                    COUNT(*)                                                   AS decisions,
                    SUM(CASE WHEN decision NOT IN ('ACCEPT','APPROVED')
                             THEN 1 ELSE 0 END)                                AS actioned,
                    COUNT(DISTINCT receiver_vpa)                               AS merchants
                FROM decisions
                WHERE sender_vpa = ? AND scored_at >= ?
                """,
                (sender_vpa, cutoff),
            ).fetchone()

            receiver = cur.execute(
                """
                SELECT
                    COUNT(*)                                                   AS decisions,
                    SUM(CASE WHEN decision NOT IN ('ACCEPT','APPROVED')
                             THEN 1 ELSE 0 END)                                AS actioned,
                    COUNT(DISTINCT sender_vpa)                                 AS payers
                FROM decisions
                WHERE receiver_vpa = ? AND scored_at >= ?
                """,
                (receiver_vpa, cutoff),
            ).fetchone()

            # Confirmed fraud only - an analyst's conclusion, not the model's own
            # earlier opinion. Joining through dispositions is what makes that
            # distinction; counting prior HOLDs here would let the system build a
            # blacklist out of its own uncertainty.
            confirmed = cur.execute(
                """
                SELECT d.sender_vpa, d.receiver_vpa
                FROM decisions d
                JOIN dispositions p ON p.decision_id = d.decision_id
                WHERE p.outcome = 'confirmed_fraud'
                  AND d.scored_at >= ?
                  AND (d.sender_vpa = ? OR d.receiver_vpa = ?)
                """,
                (cutoff, sender_vpa, receiver_vpa),
            ).fetchall()

        return NetworkReputation(
            payer_decisions=payer["decisions"] or 0,
            payer_actioned=payer["actioned"] or 0,
            payer_confirmed_fraud=sum(1 for r in confirmed if r["sender_vpa"] == sender_vpa),
            payer_distinct_merchants=payer["merchants"] or 0,
            receiver_decisions=receiver["decisions"] or 0,
            receiver_actioned=receiver["actioned"] or 0,
            receiver_confirmed_fraud=sum(
                1 for r in confirmed if r["receiver_vpa"] == receiver_vpa
            ),
            receiver_distinct_payers=receiver["payers"] or 0,
        )
    except Exception as exc:                          # noqa: BLE001
        log.warning("Network reputation lookup failed (%s); scoring without it.", exc)
        return NetworkReputation()


def apply(action: str, reputation: NetworkReputation) -> tuple[str, list[str]]:
    """Adjust the action on consortium evidence, returning the reason for any change.

    Escalation is one step at a time and only on evidence a human has confirmed or on
    behaviour a person does not exhibit. Returning the reasons alongside the action is
    the point: an override with no stated cause is indistinguishable from a bug, and
    unappealable by the merchant it affects.
    """
    reasons: list[str] = []

    if reputation.payer_confirmed_fraud:
        reasons.append(
            f"this payer was confirmed fraudulent at another merchant "
            f"{reputation.payer_confirmed_fraud} time"
            f"{'s' if reputation.payer_confirmed_fraud != 1 else ''} in the last 7 days"
        )

    if reputation.receiver_confirmed_fraud:
        reasons.append(
            f"this receiving account was confirmed fraudulent "
            f"{reputation.receiver_confirmed_fraud} time"
            f"{'s' if reputation.receiver_confirmed_fraud != 1 else ''} in the last 7 days"
        )

    if reputation.payer_distinct_merchants >= SPRAY_MERCHANTS:
        reasons.append(
            f"this payer has paid {reputation.payer_distinct_merchants} unrelated "
            "merchants in 7 days, which reads as a card being tested rather than "
            "someone shopping"
        )

    if not reasons:
        return action, []

    return ESCALATION.get(action, action), reasons
