"""FinGuard Module 7 - the degradation ladder.

A fraud engine that stops scoring is worse than one that scores badly. If the model
cannot load, or SHAP throws, or the process comes up before its artifacts do, the
payments do not stop arriving - and the choice is between failing every one of them
and falling back to something cruder that still separates a Rs.40 chai payment from a
Rs.90,000 transfer to an account created this morning.

So there are four rungs, and the engine is always on exactly one of them:

    FULL         Random Forest + SHAP. Full explanations, calibrated probabilities.
    RULES        Model unavailable. A deterministic rule stands in, with no SHAP.
    VALUE_FLOOR  Rules unavailable too. Hold anything above a value floor.
    FAIL_SAFE    Nothing works. Hold high value, accept micro-payments.

Two things make this more than a `try/except`:

**Each rung is honest about what it is.** A response scored on the RULES rung says so,
carries `degraded: true`, and its explanation says the model was unavailable rather
than inventing SHAP values. A silent fallback is worse than a loud failure, because
the alert rate moves and everyone assumes the world changed.

**The last rung is not "accept everything".** Failing open on a Rs.90,000 payment to
a fresh account because a joblib file is missing is a real loss. Failing *closed* on
micro-payments is also wrong - it declines the customer's morning chai to protect
against a risk that is not there. So the bottom rung splits on value, which is the
one signal available with no model, no rules, and no history.

The rule on the RULES rung is not invented for this file. It is the one Module 1
measures: `receiver <= 20 days old AND amount >= Rs.15,000` scores 62.4% precision on
the synthetic data, against 7.1% for account age alone. That is a poor detector and a
good fallback, and the report states both numbers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any

log = logging.getLogger("finguard.degradation")


class Rung(IntEnum):
    """Lower is better. Ordered so comparisons read the way operators think."""

    FULL = 0
    RULES = 1
    VALUE_FLOOR = 2
    FAIL_SAFE = 3

    @property
    def label(self) -> str:
        return {
            Rung.FULL: "full model",
            Rung.RULES: "rule engine (model unavailable)",
            Rung.VALUE_FLOOR: "value floor (rules unavailable)",
            Rung.FAIL_SAFE: "fail-safe (nothing available)",
        }[self]


# The rule Module 1 measures. Both numbers matter: 62.4% precision is far too weak to
# ship as a detector, and far better than declining everything.
RULE_NEW_RECEIVER_DAYS = 20
RULE_LARGE_AMOUNT_INR = 15_000.0
RULE_PRECISION_ON_SYNTHETIC = 0.624

# Above this, a payment is worth an analyst's time even with no model to justify it.
VALUE_FLOOR_INR = 25_000.0

# Below this, holding costs more than the risk it avoids. Module 2 calls this the
# customer-experience guardrail; here it is what stops the bottom rung declining
# everyone's chai.
MICRO_PAYMENT_INR = 500.0

# Odd hours are free to compute and carry real signal, so the rule keeps them even
# though the model is gone.
NIGHT_HOURS = range(1, 4)


@dataclass(frozen=True)
class Verdict:
    """One scoring result, whichever rung produced it."""

    action: str                     # ACCEPT / STEP_UP / HOLD
    rung: Rung
    reasons: list[str]
    explanation: str
    degraded: bool
    # No probability on the lower rungs: emitting a made-up number that flows into the
    # cost model and the ledger would be worse than emitting none.
    probability: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "rung": int(self.rung),
            "rung_label": self.rung.label,
            "reasons": list(self.reasons),
            "explanation": self.explanation,
            "degraded": self.degraded,
            "probability": self.probability,
        }


def _is_night(timestamp: datetime | None) -> bool:
    return timestamp is not None and timestamp.hour in NIGHT_HOURS


def rule_engine_verdict(
    amount: float,
    receiver_vpa_age_days: int | None,
    timestamp: datetime | None = None,
) -> Verdict:
    """Rung 1. The deterministic stand-in when the model will not load.

    Two signals, both available without any fitted artifact: how old the receiving
    account is and how much is moving. The combination is what carries the precision -
    account age alone is 7.1% precise on this data and would bury the queue.
    """
    reasons: list[str] = []
    age = receiver_vpa_age_days

    new_receiver = age is not None and age <= RULE_NEW_RECEIVER_DAYS
    large = amount >= RULE_LARGE_AMOUNT_INR

    if new_receiver and large:
        reasons.append(
            f"receiving account is {age} day{'s' if age != 1 else ''} old and the amount "
            f"is Rs.{amount:,.0f}"
        )
        if _is_night(timestamp):
            reasons.append(f"sent at {timestamp:%H:%M}, inside the 1-4 AM window")
        return Verdict(
            action="HOLD",
            rung=Rung.RULES,
            reasons=reasons,
            explanation=(
                f"Hold for review before fulfilment. Rs.{amount:,.0f}. Flagged on "
                f"{reasons[0]}. Scored by the fallback rule engine because the model is "
                "unavailable - this is a coarser check than usual and merits a human look."
            ),
            degraded=True,
        )

    if new_receiver and amount >= MICRO_PAYMENT_INR:
        reasons.append(f"receiving account is {age} day{'s' if age != 1 else ''} old")
        return Verdict(
            action="STEP_UP",
            rung=Rung.RULES,
            reasons=reasons,
            explanation=(
                f"Challenge before capture. Rs.{amount:,.0f}. Flagged on {reasons[0]}. "
                "Scored by the fallback rule engine because the model is unavailable; a "
                "step-up is the cheap way to cover a decision made without one."
            ),
            degraded=True,
        )

    return Verdict(
        action="ACCEPT",
        rung=Rung.RULES,
        reasons=[],
        explanation=(
            f"Accept and fulfil. Rs.{amount:,.0f}. Nothing in the fallback rule set "
            "flags this payment. Note the model was unavailable, so this is a coarser "
            "check than usual."
        ),
        degraded=True,
    )


def value_floor_verdict(amount: float) -> Verdict:
    """Rung 2. No model, no rules - only the amount is left."""
    if amount >= VALUE_FLOOR_INR:
        return Verdict(
            action="HOLD",
            rung=Rung.VALUE_FLOOR,
            reasons=[f"amount is Rs.{amount:,.0f}, above the Rs.{VALUE_FLOOR_INR:,.0f} review floor"],
            explanation=(
                f"Hold for review before fulfilment. Rs.{amount:,.0f}. Risk scoring is "
                "unavailable and this payment is above the value floor, so it is being "
                "held for a human rather than accepted unchecked."
            ),
            degraded=True,
        )
    return Verdict(
        action="ACCEPT",
        rung=Rung.VALUE_FLOOR,
        reasons=[],
        explanation=(
            f"Accept and fulfil. Rs.{amount:,.0f}. Risk scoring is unavailable; this "
            "payment is below the value floor and is being accepted rather than blocking "
            "ordinary traffic during an outage."
        ),
        degraded=True,
    )


def fail_safe_verdict(amount: float) -> Verdict:
    """Rung 3. The last rung, and deliberately not "accept everything".

    Failing open on a large payment because an artifact is missing is a real loss.
    Failing closed on micro-payments is also wrong - it declines someone's morning
    chai to protect against a risk that is not there. So the split is on value, the
    only signal left.
    """
    if amount > MICRO_PAYMENT_INR:
        return Verdict(
            action="HOLD",
            rung=Rung.FAIL_SAFE,
            reasons=["risk scoring is completely unavailable"],
            explanation=(
                f"Hold for review before fulfilment. Rs.{amount:,.0f}. The risk engine is "
                "down. Payments above Rs.{:,.0f} are held rather than accepted unchecked "
                "until it recovers.".format(MICRO_PAYMENT_INR)
            ),
            degraded=True,
        )
    return Verdict(
        action="ACCEPT",
        rung=Rung.FAIL_SAFE,
        reasons=[],
        explanation=(
            f"Accept and fulfil. Rs.{amount:,.0f}. The risk engine is down; micro-payments "
            "are accepted rather than declining ordinary traffic during an outage."
        ),
        degraded=True,
    )


def fallback_verdict(
    amount: float,
    receiver_vpa_age_days: int | None,
    timestamp: datetime | None = None,
    rules_available: bool = True,
) -> Verdict:
    """Descend to the highest rung that can still answer.

    Called when full scoring has already failed. `rules_available` exists so the lower
    rungs are reachable and testable rather than theoretical - a ladder whose bottom
    two rungs have never executed is a comment, not a fallback.
    """
    if rules_available:
        try:
            return rule_engine_verdict(amount, receiver_vpa_age_days, timestamp)
        except Exception:                             # noqa: BLE001
            log.exception("Rule engine failed; descending to the value floor.")

    try:
        return value_floor_verdict(amount)
    except Exception:                                 # noqa: BLE001
        log.exception("Value floor failed; descending to fail-safe.")

    return fail_safe_verdict(amount)
