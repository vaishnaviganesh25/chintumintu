"""Merchant-side economics: what a fraud decision actually costs the business.

FinGuard scores payments for a *merchant* on a payment gateway, not for a bank
protecting a consumer. That changes the arithmetic in three ways, and every one of
them moves the operating point:

**A false negative is not just the transaction amount.** When fraud clears, the money
is clawed back *and* the merchant pays a dispute fee, *and* — for a physical-goods
merchant — the goods are already gone. The amount is the floor, not the total.

**A false positive is not a flat review cost.** A bank pays an analyst a fixed sum to
look at an alert. A merchant declining a good customer loses the contribution margin
on that order plus the cost of re-acquiring a buyer who has just been accused of
fraud. Declining a Rs.200 order costs almost nothing; declining a Rs.80,000 order is
expensive. **A flat false-positive cost is the wrong shape** — it systematically
over-blocks small baskets and under-protects large ones.

**There is a third action.** A bank blocks or allows. A gateway can also *challenge* —
3-D Secure, an OTP step-up. It costs a slice of conversion rather than the whole
order, and it stops most fraud that faces it. Any policy with only two outcomes leaves
that option on the table.

Everything here is a stated assumption with a named constant. The numbers below are
defensible industry mid-points for Indian e-commerce, not measurements, and a merchant
plugging in their own margin and dispute fee should get a different threshold — which
is the point. `python merchant_policy.py` prints the sensitivity table.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

# --------------------------------------------------------------------------- #
# Cost assumptions
# --------------------------------------------------------------------------- #
# Levied per dispute by the acquirer regardless of whether the merchant wins the
# representment. Indian gateways publish figures in the Rs.500-2,500 band depending
# on category and volume; 1,250 is a mid-point.
CHARGEBACK_FEE_INR = 1_250.0

# Share of order value the merchant actually keeps. Used to price a *declined* good
# order: the merchant does not lose the sale price, it loses the margin on it.
CONTRIBUTION_MARGIN = 0.18

# Re-acquiring a customer who was wrongly declined. Blended CAC is far higher than
# this; 400 is the incremental cost of winning back someone already acquired once,
# and it is the part attributable to the false decline.
FALSE_DECLINE_GOODWILL_INR = 400.0

# One analyst looking at one held payment.
MANUAL_REVIEW_INR = 150.0

# A 3-D Secure challenge is not free: a share of legitimate buyers abandon at the
# OTP screen. This is the most uncertain number here and the one worth sweeping.
STEP_UP_ABANDON_RATE = 0.08

# Share of fraud that fails a step-up challenge. Not 1.0 — a scammer running a
# social-engineering play often has the OTP, which is exactly how the UPI scams in
# Module 1 work.
STEP_UP_CATCH_RATE = 0.85

# Card-network dispute monitoring. Visa retired VDMP on 31 March 2025 and folded it,
# together with the fraud programme VFMP, into VAMP; from 1 April 2026 a merchant is
# "excessive" at a VAMP ratio of 1.5%, down from 2.2%. Mastercard's ECM sits at the same
# 1.5% chargeback-to-transaction ratio once a merchant clears 100 chargebacks in a month.
# Fines and ultimately termination follow, so this is a hard operating covenant rather
# than a preference.
#
# This file previously encoded 0.9% and named VDMP, a programme that had been dead for a
# year. The number was right for VDMP and wrong for anything current.
#
# Two things a single ratio cannot carry, recorded rather than quietly corrected. VAMP's
# numerator is reported fraud *plus* disputes over settled card-not-present volume, so
# the disputes-only figure computed below sits under what Visa actually measures. And
# neither programme reaches the UPI leg - those disputes run through NPCI - while the
# ratio below is taken across the whole book. On this dataset the covenant is slack by
# roughly two orders of magnitude either way, so neither approximation changes a
# decision; both would matter on a book that ran anywhere near the line.
#
#   Visa VAMP thresholds ....... https://merchantriskcouncil.org/learning/resource-center
#   Mastercard ECM ............. chargeback-to-transaction ratio, >=100 chargebacks/month
DISPUTE_RATIO_CEILING = 0.015

# Ceiling on the share of payments that may be challenged.
#
# Without this the policy is myopically correct and operationally absurd. A step-up is
# so cheap per row that row-by-row cost minimisation will challenge anything carrying
# more than a fraction of a percent of risk - on a book with diffuse scores that came
# out at 94% of legitimate traffic, which would collapse conversion however good the
# arithmetic looks. Friction is a portfolio-level resource, not a per-row one, so it
# has to be allocated under a budget: spend it where it buys the most.
STEP_UP_BUDGET = 0.10


@dataclass(frozen=True)
class MerchantEconomics:
    """One merchant's cost structure. Swap the numbers, get a different threshold."""

    chargeback_fee: float = CHARGEBACK_FEE_INR
    contribution_margin: float = CONTRIBUTION_MARGIN
    goodwill: float = FALSE_DECLINE_GOODWILL_INR
    manual_review: float = MANUAL_REVIEW_INR
    step_up_abandon_rate: float = STEP_UP_ABANDON_RATE
    step_up_catch_rate: float = STEP_UP_CATCH_RATE
    dispute_ratio_ceiling: float = DISPUTE_RATIO_CEILING
    step_up_budget: float = STEP_UP_BUDGET

    # ---------------- unit costs ---------------- #
    def false_negative_cost(self, amount):
        """Fraud that cleared: the amount is reversed, plus the dispute fee."""
        return np.asarray(amount, dtype=float) + self.chargeback_fee

    def false_positive_cost(self, amount):
        """A good order declined: lost margin plus the cost of winning them back.

        Scales with the order. This is the change that matters most versus the
        bank-side flat review cost - it stops the policy from spending the same
        Rs.150 defending a Rs.40 chai payment and a Rs.90,000 electronics order.
        """
        amount = np.asarray(amount, dtype=float)
        return self.contribution_margin * amount + self.goodwill

    def step_up_cost(self, amount):
        """Challenging a good customer: the share who abandon, times the margin lost."""
        amount = np.asarray(amount, dtype=float)
        return self.step_up_abandon_rate * self.contribution_margin * amount

    # ---------------- expected cost of each action ---------------- #
    def expected_cost_accept(self, probability, amount):
        return np.asarray(probability, dtype=float) * self.false_negative_cost(amount)

    def expected_cost_step_up(self, probability, amount):
        """Challenge: stops most fraud, annoys some good customers, leaks the rest."""
        p = np.asarray(probability, dtype=float)
        leaked = p * (1.0 - self.step_up_catch_rate) * self.false_negative_cost(amount)
        friction = (1.0 - p) * self.step_up_cost(amount)
        return leaked + friction

    def expected_cost_hold(self, probability, amount):
        """Manual review: an analyst costs a fixed sum; a wrong hold costs the order."""
        p = np.asarray(probability, dtype=float)
        return self.manual_review + (1.0 - p) * self.false_positive_cost(amount)

    # ---------------- the decision ---------------- #
    def decide(self, probability: float, amount: float) -> str:
        """Pick the cheapest of the three actions at this probability and amount.

        No threshold constant appears here. The action boundaries fall out of the
        cost curves, which is why the same model yields a different policy for a
        digital-goods merchant with 80% margins and a phone reseller with 4%.
        """
        costs = {
            "ACCEPT": float(self.expected_cost_accept(probability, amount)),
            "STEP_UP": float(self.expected_cost_step_up(probability, amount)),
            "HOLD": float(self.expected_cost_hold(probability, amount)),
        }
        return min(costs, key=costs.get)

    def action_costs(self, probability: float, amount: float) -> dict[str, float]:
        """The three expected costs behind a decision, for the audit trail."""
        return {
            "ACCEPT": round(float(self.expected_cost_accept(probability, amount)), 2),
            "STEP_UP": round(float(self.expected_cost_step_up(probability, amount)), 2),
            "HOLD": round(float(self.expected_cost_hold(probability, amount)), 2),
        }

    def step_up_benefit(self, probability, amount):
        """How much a challenge saves over the best alternative for this payment.

        Negative where challenging is not worth it at all. This is the quantity the
        step-up budget is allocated against - rank by it, spend the budget from the
        top, and the friction lands where it buys the most.
        """
        alternative = np.minimum(
            self.expected_cost_accept(probability, amount),
            self.expected_cost_hold(probability, amount),
        )
        return alternative - self.expected_cost_step_up(probability, amount)

    def accept_boundary(self, amount: float, grid: int = 2000) -> float:
        """Lowest probability at which accepting stops being the cheapest action.

        Reported rather than configured. It is the merchant-side equivalent of the
        decision threshold, and it moves with the order value - which is the whole
        argument for an amount-scaled cost model.
        """
        probabilities = np.linspace(0.0, 1.0, grid)
        accept = self.expected_cost_accept(probabilities, amount)
        best_other = np.minimum(
            self.expected_cost_step_up(probabilities, amount),
            self.expected_cost_hold(probabilities, amount),
        )
        crossed = np.flatnonzero(accept > best_other)
        return float(probabilities[crossed[0]]) if crossed.size else 1.0


DEFAULT = MerchantEconomics()


# --------------------------------------------------------------------------- #
# Merchant-facing language
# --------------------------------------------------------------------------- #
# What each action means operationally, in the merchant's own workflow. Nothing here
# addresses a cardholder: the reader is the person deciding whether to ship the goods.
ACTION_HEADLINE = {
    "ACCEPT": "Accept and fulfil.",
    "STEP_UP": "Challenge before capture.",
    "HOLD": "Hold for review before fulfilment.",
}


def merchant_advice(action: str, amount: float, reasons: list[str],
                    econ: MerchantEconomics = DEFAULT) -> str:
    """Render a decision as guidance a merchant can act on.

    Deliberately not a customer notification. The bank-side framing this project
    started from - "we have paused a payment from your account for your safety" -
    addresses the payer, who is not the person a gateway is protecting. The merchant
    is the one carrying the chargeback, and the only useful output is what to do with
    the order.

    Only risk-*increasing* factors are narrated; a reason list that mixes in mitigating
    evidence reads as equivocation on a queue someone is working through quickly.
    """
    headline = ACTION_HEADLINE.get(action, "Review.")
    because = ""
    if reasons:
        joined = reasons[0] if len(reasons) == 1 else " and ".join(reasons[:2])
        because = f" Flagged on {joined}."

    if action == "ACCEPT":
        return (f"{headline} Rs.{amount:,.0f}. This payment looks consistent with "
                "ordinary traffic; no intervention needed.")

    if action == "STEP_UP":
        exposure = float(econ.false_negative_cost(amount))
        return (
            f"{headline} Rs.{amount:,.0f}.{because} Send this one through 3-D Secure or "
            f"an OTP challenge rather than declining it: a decline costs you the margin "
            f"on the order plus the customer, while a cleared chargeback here would cost "
            f"about Rs.{exposure:,.0f} including the dispute fee."
        )

    exposure = float(econ.false_negative_cost(amount))
    return (
        f"{headline} Rs.{amount:,.0f}.{because} Do not ship until this is cleared. "
        f"If it is fraud and it settles, the exposure is roughly Rs.{exposure:,.0f} "
        f"including the dispute fee, and it counts against your dispute ratio."
    )


# --------------------------------------------------------------------------- #
# Portfolio-level evaluation
# --------------------------------------------------------------------------- #
def portfolio_cost(y_true, y_prob, amounts, econ: MerchantEconomics = DEFAULT) -> dict:
    """Total expected loss over a book of payments under the three-action policy.

    Every row is routed to whichever action is cheapest for it, then charged what
    that action actually costs given the true label. This is the number a merchant
    would recognise; precision and recall are inputs to it, not the goal.
    """
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    amounts = np.asarray(amounts, dtype=float)

    accept = econ.expected_cost_accept(y_prob, amounts)
    step_up = econ.expected_cost_step_up(y_prob, amounts)
    hold = econ.expected_cost_hold(y_prob, amounts)

    # Route under the step-up budget rather than row by row.
    #
    # Unconstrained, `argmin` over the three costs challenges anything carrying more
    # than a fraction of a percent of risk, because a step-up is so cheap per row.
    # On a book with diffuse scores that reaches most of the legitimate traffic - a
    # policy that is arithmetically optimal and would destroy the merchant's
    # conversion. So each payment first gets its best *unchallenged* action, and the
    # budget is then spent on the rows where a challenge saves the most.
    chosen = np.where(accept <= hold, 0, 2)         # 0 accept, 1 step_up, 2 hold
    benefit = np.minimum(accept, hold) - step_up
    n = len(y_true)
    budget_rows = int(np.floor(econ.step_up_budget * n))

    worth_challenging = np.flatnonzero(benefit > 0)
    if worth_challenging.size and budget_rows > 0:
        ranked = worth_challenging[np.argsort(-benefit[worth_challenging])][:budget_rows]
        chosen[ranked] = 1

    fraud = y_true == 1
    legit = ~fraud

    # Realised cost, given what the row actually was.
    cost = np.zeros_like(amounts)
    fn_cost = econ.false_negative_cost(amounts)

    cost[(chosen == 0) & fraud] = fn_cost[(chosen == 0) & fraud]
    # A challenged fraud leaks only when the scammer clears the challenge.
    cost[(chosen == 1) & fraud] = (1 - econ.step_up_catch_rate) * fn_cost[(chosen == 1) & fraud]
    cost[(chosen == 1) & legit] = econ.step_up_cost(amounts)[(chosen == 1) & legit]
    cost[(chosen == 2) & fraud] = econ.manual_review
    cost[(chosen == 2) & legit] = econ.manual_review + econ.false_positive_cost(amounts)[(chosen == 2) & legit]

    # Disputes are the frauds that reached the merchant: accepted outright, or
    # challenged and cleared anyway.
    expected_disputes = float(
        ((chosen == 0) & fraud).sum()
        + (1 - econ.step_up_catch_rate) * ((chosen == 1) & fraud).sum()
    )

    return {
        "total_cost_inr": float(cost.sum()),
        "cost_per_txn_inr": float(cost.sum() / n) if n else 0.0,
        "accepted": int((chosen == 0).sum()),
        "stepped_up": int((chosen == 1).sum()),
        "held": int((chosen == 2).sum()),
        "hold_rate": float((chosen == 2).mean()),
        "step_up_rate": float((chosen == 1).mean()),
        "step_up_budget": econ.step_up_budget,
        "step_up_budget_exhausted": bool(
            worth_challenging.size > budget_rows and budget_rows > 0
        ),
        "fraud_accepted": int(((chosen == 0) & fraud).sum()),
        "fraud_value_leaked_inr": float(amounts[(chosen == 0) & fraud].sum()),
        "good_orders_held": int(((chosen == 2) & legit).sum()),
        "expected_disputes": expected_disputes,
        "dispute_ratio": expected_disputes / n if n else 0.0,
        "dispute_ceiling": econ.dispute_ratio_ceiling,
        "within_covenant": (expected_disputes / n if n else 0.0) <= econ.dispute_ratio_ceiling,
    }


def binary_portfolio_cost(y_true, y_prob, amounts, threshold: float,
                          econ: MerchantEconomics = DEFAULT) -> dict:
    """The same book scored by a single block/allow threshold, for comparison.

    Exists so the three-action policy has to earn its complexity against the simpler
    rule rather than being assumed better.
    """
    y_true = np.asarray(y_true, dtype=int)
    amounts = np.asarray(amounts, dtype=float)
    blocked = np.asarray(y_prob, dtype=float) >= threshold

    fraud = y_true == 1
    missed = ~blocked & fraud
    wrong_hold = blocked & ~fraud

    cost = (
        econ.false_negative_cost(amounts)[missed].sum()
        + econ.manual_review * blocked.sum()
        + econ.false_positive_cost(amounts)[wrong_hold].sum()
    )
    n = len(y_true)
    return {
        "total_cost_inr": float(cost),
        "cost_per_txn_inr": float(cost / n) if n else 0.0,
        "held": int(blocked.sum()),
        "fraud_accepted": int(missed.sum()),
        "good_orders_held": int(wrong_hold.sum()),
        "dispute_ratio": float(missed.sum() / n) if n else 0.0,
    }


def prevalence_at_which_covenant_binds(recall: float,
                                       econ: MerchantEconomics = DEFAULT) -> float | None:
    """Fraud prevalence at which the dispute ceiling starts to constrain the model.

    disputes/txns = prevalence x (1 - recall), so the covenant binds once
    prevalence > ceiling / (1 - recall). Reported because on this dataset it does
    *not* bind, and saying so is more useful than implying a constraint is doing work
    it is not.
    """
    if recall >= 1.0:
        return None
    return econ.dispute_ratio_ceiling / (1.0 - recall)


# --------------------------------------------------------------------------- #
# Sensitivity
# --------------------------------------------------------------------------- #
def _sensitivity_table() -> list[str]:
    """How the accept boundary moves with order value and with margin.

    The headline: a merchant should be far more willing to accept risk on a small
    basket than a large one, and a low-margin merchant should be more willing to
    challenge. A single global threshold cannot express either.
    """
    lines = [
        "Accept boundary - lowest fraud probability at which accepting stops being cheapest",
        "",
        f"  {'Order value':>12}  " + "".join(f"{f'margin {m:.0%}':>14}" for m in (0.04, 0.18, 0.60)),
        "  " + "-" * 56,
    ]
    for amount in (200, 2_000, 15_000, 50_000, 90_000):
        cells = []
        for margin in (0.04, 0.18, 0.60):
            econ = replace(DEFAULT, contribution_margin=margin)
            cells.append(f"{econ.accept_boundary(amount):>14.4f}")
        lines.append(f"  Rs.{amount:>9,}  " + "".join(cells))

    lines += [
        "",
        "Read the first column: a 4%-margin reseller should challenge a Rs.50,000 order",
        "at a far lower fraud probability than a 60%-margin software seller, because a",
        "cleared fraud costs it the same money while a declined order costs it much less.",
        "The model is identical in both cases. Only the policy over it changes.",
    ]
    return lines


if __name__ == "__main__":
    print("\n".join(_sensitivity_table()))
    print()
    print("Unit costs at Rs.25,000, p(fraud) = 0.30")
    print(f"  false negative : Rs.{float(DEFAULT.false_negative_cost(25_000)):>10,.2f}")
    print(f"  false positive : Rs.{float(DEFAULT.false_positive_cost(25_000)):>10,.2f}")
    print(f"  step-up        : Rs.{float(DEFAULT.step_up_cost(25_000)):>10,.2f}")
    for action, cost in DEFAULT.action_costs(0.30, 25_000).items():
        print(f"  E[cost | {action:<8}] Rs.{cost:>10,.2f}")
    print(f"  -> {DEFAULT.decide(0.30, 25_000)}")
