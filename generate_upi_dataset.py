"""FinGuard - synthetic Indian UPI transaction generator.

Produces `upi_synthetic_data.csv`: 100,000 UPI transactions over a 30-day window
with 0.5% fraud injected as three India-specific scam signatures (the "Rs.1 test",
new-VPA mule velocity, and odd-hour phishing).

The generator is seeded, so re-running it reproduces the same dataset.

Usage:
    python generate_upi_dataset.py
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
SEED = 42

N_TRANSACTIONS = 100_000
FRAUD_RATE = 0.005                      # 0.5% -> 500 fraudulent rows
N_FRAUD = int(round(N_TRANSACTIONS * FRAUD_RATE))
N_LEGIT = N_TRANSACTIONS - N_FRAUD

N_SENDERS = 5_000                       # customer population
N_LEGIT_RECEIVERS = 3_000               # established merchants + P2P counterparties

# Newly onboarded receivers: friends who just installed a UPI app, street vendors
# who registered a QR code this week. India adds millions of UPI users a month, so a
# meaningful slice of genuine volume goes to accounts only days old.
#
# This population exists to stop `receiver_vpa_age_days` being a giveaway. Without
# it, every fraudulent receiver is 0-20 days old and almost every legitimate one is
# 150+, so a single split on account age separates the classes and the model never
# has to learn the behavioural patterns underneath. These transactions are entirely
# legitimate and behave like it: micro-payment amounts, daytime hours, unhurried
# spacing. The only thing they share with fraud is a brand-new receiver.
N_NEW_ADOPTER_RECEIVERS = 1_000
NEW_ADOPTER_TXN_SHARE = 0.06            # share of legitimate traffic they receive
NEW_ADOPTER_AGE_SCALE = 2.5             # mean days between VPA creation and payment

# Genuine large payments to a brand-new counterparty: a deposit to a landlord who
# just opened a VPA, a second-hand bike bought off a classifieds listing, a wedding
# gift. Small in number but load-bearing - without them, "new receiver AND large
# amount" is still a perfectly clean fraud rule and the model learns that instead
# of the velocity and sequence structure that actually generalises.
NEW_ADOPTER_BIG_TICKET_SHARE = 0.035

WINDOW_DAYS = 30
END_DATE = datetime(2026, 8, 10, 0, 0, 0)
START_DATE = END_DATE - timedelta(days=WINDOW_DAYS)

MAX_VPA_AGE_DAYS = 1_000                # feature is capped at 1000 as specified

# Two deliberate slices of "awkward but genuine" behaviour. Without them the
# labels are perfectly separable on `amount` alone (every Rs.1 and every amount
# above Rs.15,000 would be fraud), which would make the classifier and its SHAP
# explanations useless. Set either to 0.0 for a strictly clean two-tier split.
LEGIT_TINY_PROBE_SHARE = 0.004          # honest Rs.1-5 test transfers, no follow-up
LEGIT_BIG_TICKET_SHARE = 0.012          # rare genuine Rs.15k-2L deposits/fees/gold

# Fraud budget, expressed as incidents; the row counts must sum to N_FRAUD.
N_RUPEE1_PAIRS = 100                    # 2 rows per incident -> 200 rows
N_VELOCITY_BURSTS = 30                  # 5 rows per burst     -> 150 rows
TRANSFERS_PER_VICTIM = (2, 2, 1)        # how one burst's victims split the transfers
ROWS_PER_VELOCITY_BURST = sum(TRANSFERS_PER_VICTIM)
N_ODD_HOUR = N_FRAUD - (2 * N_RUPEE1_PAIRS) - (N_VELOCITY_BURSTS * ROWS_PER_VELOCITY_BURST)

OUTPUT_CSV = Path(__file__).with_name("upi_synthetic_data.csv")

# Real UPI PSP handles. Bank-app handles (@okicici, @oksbi) dominate P2P,
# while @ybl / @paytm / @apl are the third-party apps (PhonePe, Paytm, Amazon Pay).
PERSONAL_HANDLES = ["okicici", "oksbi", "okhdfcbank", "okaxis", "ybl", "ibl", "axl", "paytm", "apl"]
PERSONAL_HANDLE_P = [0.16, 0.15, 0.13, 0.09, 0.18, 0.06, 0.06, 0.10, 0.07]
MERCHANT_HANDLES = ["paytm", "ybl", "okbizaxis", "hdfcbank", "sbi", "axisbank", "icici", "upi"]

# Metros carry most UPI volume; the rest of the pool comes from Faker's en_IN cities.
METRO_CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Surat", "Kochi",
]

# Chai, autos, kirana stores: real UPI micro-payments cluster on round numbers.
COMMON_SMALL_AMOUNTS = np.array(
    [10, 20, 20, 25, 30, 40, 50, 50, 60, 70, 75, 80, 99, 100, 100, 120, 150,
     180, 199, 200, 200, 250, 299, 300, 350, 399, 400, 450, 499, 500],
    dtype=float,
)

# Hour-of-day intensity for legitimate traffic: busy 09:00-21:00, near-dead 01:00-04:00.
# This is what makes the odd-hour fraud signature stand out.
HOUR_WEIGHTS = np.array(
    [0.8, 0.4, 0.3, 0.3, 0.5, 1.0, 1.8, 2.8, 4.0, 5.5, 6.5, 6.8,
     7.0, 6.5, 5.8, 5.5, 5.8, 6.2, 6.8, 7.2, 6.8, 5.5, 3.5, 1.9],
    dtype=float,
)
HOUR_P = HOUR_WEIGHTS / HOUR_WEIGHTS.sum()

COLUMNS = [
    "transaction_id",
    "timestamp",
    "sender_vpa",
    "receiver_vpa",
    "sender_city",
    "amount",
    "receiver_vpa_age_days",
    "time_since_last_txn_sec",
    "is_fraud",
    "fraud_pattern",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def slugify(text: str) -> str:
    """Reduce a name to the lowercase alphabetic form used inside a VPA."""
    return re.sub(r"[^a-z]", "", text.lower())


def random_mobile(rng: np.random.Generator) -> str:
    """Indian mobile numbers start with 6-9 and are 10 digits long."""
    return f"{rng.integers(6, 10)}{rng.integers(0, 10 ** 9):09d}"


def gamma_weights(size: int, rng: np.random.Generator, shape: float = 1.6) -> np.ndarray:
    """Skewed sampling weights so a few accounts are far more active than the rest."""
    w = rng.gamma(shape=shape, scale=1.0, size=size)
    return w / w.sum()


def make_personal_vpa(fake: Faker, rng: np.random.Generator, used: set[str]) -> str:
    """`firstname.lastname@okicici` (60%) or `9876543210@ybl` (40%), guaranteed unique."""
    while True:
        handle = rng.choice(PERSONAL_HANDLES, p=PERSONAL_HANDLE_P)
        if rng.random() < 0.60:
            first = slugify(fake.first_name()) or "user"
            last = slugify(fake.last_name()) or "kumar"
            local = f"{first}.{last}"
            if rng.random() < 0.35:                      # birth year / lucky number suffix
                local += str(rng.integers(1, 100)) if rng.random() < 0.5 else str(rng.integers(1970, 2006))
        else:
            local = random_mobile(rng)
        vpa = f"{local}@{handle}"
        if vpa not in used:
            used.add(vpa)
            return vpa


def make_merchant_vpa(fake: Faker, rng: np.random.Generator, used: set[str]) -> str:
    """Merchant-style VPAs: QR terminal IDs, business names, or utility billers."""
    while True:
        handle = str(rng.choice(MERCHANT_HANDLES))
        roll = rng.random()
        if roll < 0.40:                                  # static-QR terminal, e.g. q62839104@ybl
            local = f"q{rng.integers(10 ** 7, 10 ** 9)}"
        elif roll < 0.80:
            base = slugify(fake.company().split()[0]) or "store"
            local = f"{base[:14]}.{rng.choice(['store', 'kirana', 'shop', 'foods', 'mart', 'services'])}"
        else:
            local = f"{rng.choice(['bill', 'recharge', 'fees', 'rent', 'emi'])}.{slugify(fake.last_name()) or 'pay'}"
        vpa = f"{local}@{handle}"
        if vpa not in used:
            used.add(vpa)
            return vpa


# --------------------------------------------------------------------------- #
# Account population
# --------------------------------------------------------------------------- #
def build_sender_pool(fake: Faker, rng: np.random.Generator, used: set[str]) -> pd.DataFrame:
    """Senders are ordinary retail customers with a home city and an activity weight."""
    faker_cities = list({fake.city() for _ in range(60)})
    cities = METRO_CITIES + faker_cities
    city_p = np.array([8.0] * len(METRO_CITIES) + [1.0] * len(faker_cities))
    city_p /= city_p.sum()

    return pd.DataFrame(
        {
            "vpa": [make_personal_vpa(fake, rng, used) for _ in range(N_SENDERS)],
            "city": rng.choice(cities, size=N_SENDERS, p=city_p),
            "weight": gamma_weights(N_SENDERS, rng),
        }
    )


def build_receiver_pool(fake: Faker, rng: np.random.Generator, used: set[str]) -> pd.DataFrame:
    """Established receivers: 75% merchants, 25% peers, each with a VPA creation date.

    `receiver_vpa_age_days` is later derived from this creation date, so the feature
    is internally consistent: the same VPA ages as the 30-day window progresses.

    Everything here predates the window by at least two days. Genuinely new accounts
    are a separate population (see `build_new_adopter_pool`), which keeps the two
    behaviours cleanly separated in the code rather than blurred into one prior.
    """
    vpas = [
        make_merchant_vpa(fake, rng, used) if rng.random() < 0.75 else make_personal_vpa(fake, rng, used)
        for _ in range(N_LEGIT_RECEIVERS)
    ]

    roll = rng.random(N_LEGIT_RECEIVERS)
    days_before_start = np.where(
        roll < 0.80,
        rng.integers(150, 960, size=N_LEGIT_RECEIVERS),
        np.where(roll < 0.97, rng.integers(30, 150, size=N_LEGIT_RECEIVERS),
                 rng.integers(2, 30, size=N_LEGIT_RECEIVERS)),
    )
    created_at = np.datetime64(START_DATE, "s") - days_before_start.astype("timedelta64[D]").astype("timedelta64[s]")

    return pd.DataFrame(
        {
            "vpa": vpas,
            "created_at": created_at,
            "weight": gamma_weights(N_LEGIT_RECEIVERS, rng, shape=1.1),
        }
    )


def build_new_adopter_pool(fake: Faker, rng: np.random.Generator, used: set[str]) -> pd.DataFrame:
    """Receivers whose VPA is created *during* the 30-day window.

    Mostly individuals (a friend who just installed the app and gets paid back for
    dinner), plus a minority of small merchants registering a QR code. Creation dates
    are spread uniformly across the window, and each account is cut off a day before
    the end so it has time to actually receive something.
    """
    vpas = [
        make_merchant_vpa(fake, rng, used) if rng.random() < 0.25 else make_personal_vpa(fake, rng, used)
        for _ in range(N_NEW_ADOPTER_RECEIVERS)
    ]

    max_offset = (WINDOW_DAYS - 1) * 86_400
    offsets = rng.integers(0, max_offset, size=N_NEW_ADOPTER_RECEIVERS).astype("int64")
    created_at = np.datetime64(START_DATE, "s") + offsets.astype("timedelta64[s]")

    return pd.DataFrame(
        {
            "vpa": vpas,
            "created_at": created_at,
            "weight": gamma_weights(N_NEW_ADOPTER_RECEIVERS, rng, shape=1.4),
        }
    )


# --------------------------------------------------------------------------- #
# Class 0: legitimate traffic
# --------------------------------------------------------------------------- #
def sample_legit_amounts(n: int, rng: np.random.Generator) -> np.ndarray:
    """70% micro-payments (Rs.10-500), 30% higher-value bills/rent (Rs.1,000-15,000)."""
    amounts = np.empty(n)
    small = rng.random(n) < 0.70

    n_small = int(small.sum())
    round_small = rng.random(n_small) < 0.55
    small_vals = np.where(
        round_small,
        rng.choice(COMMON_SMALL_AMOUNTS, size=n_small),
        rng.integers(10, 501, size=n_small).astype(float),
    )
    # Honest test transfers: people really do send Rs.1 to check a new VPA. These
    # have no large follow-up, so only the *pair* identifies the Rs.1 test scam.
    probe = rng.random(n_small) < LEGIT_TINY_PROBE_SHARE
    small_vals[probe] = rng.integers(1, 6, size=int(probe.sum())).astype(float)
    amounts[small] = small_vals

    n_high = n - n_small
    round_high = rng.random(n_high) < 0.45
    high_vals = np.clip(
        np.where(
            round_high,
            rng.integers(2, 31, size=n_high) * 500.0,                   # rent/EMI style round figures
            np.exp(rng.normal(8.2, 0.55, size=n_high)),
        ),
        1_000,
        15_000,
    )
    # Genuine big-ticket payments (security deposit, college fees, jewellery) that
    # overlap the fraud amount range and force the model to use context, not a threshold.
    # Offset from the Rs.15,000 floor rather than clipped to it, so no mass piles up
    # on the boundary and gives the model an artificial landmark.
    big_ticket = rng.random(n_high) < LEGIT_BIG_TICKET_SHARE
    high_vals[big_ticket] = np.minimum(
        15_000 + np.exp(rng.normal(9.5, 0.85, size=int(big_ticket.sum()))), 200_000
    )
    amounts[~small] = high_vals

    return np.round(amounts, 2)


def sample_legit_timestamps(n: int, rng: np.random.Generator) -> np.ndarray:
    """Uniform across the 30 days (weekends slightly busier), shaped by hour-of-day."""
    weekday = np.array([(START_DATE + timedelta(days=int(d))).weekday() for d in range(WINDOW_DAYS)])
    day_p = np.where(weekday >= 5, 1.15, 1.0)
    day_p /= day_p.sum()

    day = rng.choice(WINDOW_DAYS, size=n, p=day_p)
    hour = rng.choice(24, size=n, p=HOUR_P)
    minute = rng.integers(0, 60, size=n)
    second = rng.integers(0, 60, size=n)

    offsets = (day * 86_400 + hour * 3_600 + minute * 60 + second).astype("int64")
    return np.datetime64(START_DATE, "s") + offsets.astype("timedelta64[s]")


def sample_new_adopter_amounts(n: int, rng: np.random.Generator) -> np.ndarray:
    """Amounts sent to a brand-new VPA: overwhelmingly small, everyday sums.

    Splitting a dinner bill, repaying a cab fare, a first payment to a vendor who
    just put up a QR code. The distribution then thins out through the ordinary
    higher-value band into a genuine big-ticket tail, so there is no amount at which
    "new receiver" flips cleanly from safe to fraudulent. What separates these from
    the mule transfers is not size but shape: one unhurried daytime payment rather
    than a burst, and no Rs.1 probe in front of it.
    """
    amounts = np.empty(n)
    roll = rng.random(n)
    big_cut = 1.0 - NEW_ADOPTER_BIG_TICKET_SHARE

    micro = roll < 0.82
    n_micro = int(micro.sum())
    round_micro = rng.random(n_micro) < 0.55
    amounts[micro] = np.where(
        round_micro,
        rng.choice(COMMON_SMALL_AMOUNTS, size=n_micro),
        rng.integers(10, 501, size=n_micro).astype(float),
    )

    mid = (roll >= 0.82) & (roll < 0.94)
    amounts[mid] = rng.integers(500, 3_001, size=int(mid.sum())).astype(float)

    high = (roll >= 0.94) & (roll < big_cut)
    amounts[high] = np.clip(
        np.exp(rng.normal(8.2, 0.55, size=int(high.sum()))), 1_000, 15_000
    )

    # Offset from the Rs.15,000 mark rather than clipped to it, so the tail flows
    # into the fraud amount range instead of piling up on a boundary.
    big = roll >= big_cut
    amounts[big] = np.minimum(
        15_000 + np.exp(rng.normal(9.7, 0.9, size=int(big.sum()))), 250_000
    )
    return np.round(amounts, 2)


def generate_new_adopter_traffic(
    senders: pd.DataFrame, adopters: pd.DataFrame, n: int, rng: np.random.Generator
) -> pd.DataFrame:
    """Legitimate payments to accounts that are only days old.

    Timing is the crux: payments cluster in the first few days after the VPA is
    created (an exponential with a ~2.5 day mean), which is how real onboarding
    looks - friends pay you back right after you install the app. That produces a
    thick band of genuine transactions at `receiver_vpa_age_days` of 0, 1 and 2,
    which is exactly the region fraud used to own outright.

    Everything else about these rows is ordinary: normal hour-of-day distribution,
    no rapid-fire bursts, micro-payment amounts.
    """
    sender_idx = rng.choice(N_SENDERS, size=n, p=senders["weight"].to_numpy())
    receiver_idx = rng.choice(N_NEW_ADOPTER_RECEIVERS, size=n, p=adopters["weight"].to_numpy())
    created_at = adopters["created_at"].to_numpy()[receiver_idx]

    # Days between account creation and this payment, capped so the timestamp stays
    # inside the window.
    age_days = rng.exponential(NEW_ADOPTER_AGE_SCALE, size=n).astype("int64")
    window_end = np.datetime64(END_DATE, "s")
    max_age = ((window_end - created_at) / np.timedelta64(1, "D")).astype("int64")
    age_days = np.clip(age_days, 0, np.maximum(max_age, 0))

    # Land on the target day, then draw a normal time of day for it.
    day = created_at.astype("datetime64[D]").astype("datetime64[s]") + (
        age_days.astype("timedelta64[D]").astype("timedelta64[s]")
    )
    hour = rng.choice(24, size=n, p=HOUR_P)
    minute = rng.integers(0, 60, size=n)
    second = rng.integers(0, 60, size=n)
    timestamps = day + (hour * 3_600 + minute * 60 + second).astype("int64").astype("timedelta64[s]")

    # A payment cannot land before the account exists: on creation day, push it a
    # little after the account was opened instead.
    too_early = timestamps < created_at
    if too_early.any():
        nudge = rng.integers(300, 7_200, size=int(too_early.sum())).astype("int64")
        timestamps[too_early] = created_at[too_early] + nudge.astype("timedelta64[s]")
    timestamps = np.minimum(timestamps, window_end - np.timedelta64(1, "s"))

    actual_age = ((timestamps - created_at) / np.timedelta64(1, "D")).astype("int64")

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "sender_vpa": senders["vpa"].to_numpy()[sender_idx],
            "receiver_vpa": adopters["vpa"].to_numpy()[receiver_idx],
            "sender_city": senders["city"].to_numpy()[sender_idx],
            "amount": sample_new_adopter_amounts(n, rng),
            "receiver_vpa_age_days": np.clip(actual_age, 0, MAX_VPA_AGE_DAYS),
            "is_fraud": 0,
            "fraud_pattern": "none",
        }
    )


def generate_legitimate(
    senders: pd.DataFrame, receivers: pd.DataFrame, adopters: pd.DataFrame, rng: np.random.Generator
) -> pd.DataFrame:
    """All 99,500 non-fraud rows: established-receiver traffic plus new-adopter traffic."""
    n_adopter = int(round(N_LEGIT * NEW_ADOPTER_TXN_SHARE))
    n_established = N_LEGIT - n_adopter

    established = _generate_established_traffic(senders, receivers, n_established, rng)
    new_adopter = generate_new_adopter_traffic(senders, adopters, n_adopter, rng)
    return pd.concat([established, new_adopter], ignore_index=True)


def _generate_established_traffic(
    senders: pd.DataFrame, receivers: pd.DataFrame, n: int, rng: np.random.Generator
) -> pd.DataFrame:
    """Vectorised generation of ordinary traffic to long-standing receivers."""
    sender_idx = rng.choice(N_SENDERS, size=n, p=senders["weight"].to_numpy())
    receiver_idx = rng.choice(N_LEGIT_RECEIVERS, size=n, p=receivers["weight"].to_numpy())

    timestamps = sample_legit_timestamps(n, rng)
    created_at = receivers["created_at"].to_numpy()[receiver_idx]

    # A transaction cannot predate its receiver's VPA: reschedule those rows into
    # the remaining part of the window so ages stay non-negative and truthful.
    impossible = timestamps < created_at
    if impossible.any():
        window_end = np.datetime64(END_DATE, "s")
        span = (window_end - created_at[impossible]) / np.timedelta64(1, "s")
        shift = (rng.random(int(impossible.sum())) * span).astype("int64")
        timestamps[impossible] = created_at[impossible] + shift.astype("timedelta64[s]")

    age_days = ((timestamps - created_at) / np.timedelta64(1, "D")).astype("int64")
    age_days = np.clip(age_days, 0, MAX_VPA_AGE_DAYS)

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "sender_vpa": senders["vpa"].to_numpy()[sender_idx],
            "receiver_vpa": receivers["vpa"].to_numpy()[receiver_idx],
            "sender_city": senders["city"].to_numpy()[sender_idx],
            "amount": sample_legit_amounts(n, rng),
            "receiver_vpa_age_days": age_days,
            "is_fraud": 0,
            "fraud_pattern": "none",
        }
    )


# --------------------------------------------------------------------------- #
# Class 1: localized scam signatures
# --------------------------------------------------------------------------- #
def random_fraud_timestamp(rng: np.random.Generator, hours: range | None = None) -> datetime:
    """Pick a timestamp in the window; `hours` restricts the hour-of-day if given."""
    day = int(rng.integers(0, WINDOW_DAYS))
    hour = int(rng.choice(list(hours))) if hours is not None else int(rng.choice(24, p=HOUR_P))
    return START_DATE + timedelta(
        days=day, hours=hour, minutes=int(rng.integers(0, 60)), seconds=int(rng.integers(0, 60))
    )


def _row(ts, sender, city, receiver, amount, age, pattern) -> dict:
    return {
        "timestamp": ts,
        "sender_vpa": sender,
        "receiver_vpa": receiver,
        "sender_city": city,
        "amount": round(float(amount), 2),
        "receiver_vpa_age_days": int(age),
        "is_fraud": 1,
        "fraud_pattern": pattern,
    }


def generate_rupee_one_test(
    senders: pd.DataFrame, fake: Faker, rng: np.random.Generator, used: set[str]
) -> list[dict]:
    """Signature 1 - the "Rs.1 test" scam.

    The fraudster talks the victim into sending Rs.1 to "verify" the account, then
    immediately pushes a large transfer to the *same* receiver. Both legs are
    labelled fraud, and the giveaway is the pair itself: amount == 1 followed by
    a 10,000+ transfer to the same receiver within 60 seconds
    (visible downstream as a tiny `time_since_last_txn_sec` on the second leg).
    """
    rows: list[dict] = []
    victims = rng.choice(N_SENDERS, size=N_RUPEE1_PAIRS, replace=False)

    for victim_idx in victims:
        sender = senders.at[int(victim_idx), "vpa"]
        city = senders.at[int(victim_idx), "city"]
        receiver = make_personal_vpa(fake, rng, used)     # freshly opened mule account

        # Mule VPAs are days old at most; keep it away from the window edge so the
        # follow-up leg still lands inside the 30-day period.
        age = int(rng.integers(0, 4))
        t_probe = random_fraud_timestamp(rng)
        if t_probe > END_DATE - timedelta(minutes=5):
            t_probe -= timedelta(hours=1)

        # The "massive" leg: Rs.10,000+, skewed towards the round figures a victim
        # would be instructed to send, and capped by the Rs.1 lakh UPI P2P limit.
        if rng.random() < 0.65:
            big = float(rng.integers(20, 200) * 500)      # Rs.10,000 - Rs.99,500
        else:
            big = float(rng.integers(10_000, 100_000))
        big = float(np.clip(big, 10_000, 99_999))
        t_big = t_probe + timedelta(seconds=int(rng.integers(12, 61)))

        rows.append(_row(t_probe, sender, city, receiver, 1.0, age, "rupee_1_test"))
        rows.append(_row(t_big, sender, city, receiver, big, age, "rupee_1_test"))

    return rows


def generate_new_vpa_velocity(
    senders: pd.DataFrame, fake: Faker, rng: np.random.Generator, used: set[str]
) -> list[dict]:
    """Signature 2 - new-VPA velocity (mule account collection).

    A VPA created the same day (`receiver_vpa_age_days == 0`) collects several
    high-value transfers inside a few minutes. Each burst mixes victims, and two of
    them send twice in quick succession - the classic "the refund failed, send it
    again" pressure tactic - so the burst is visible both on the receiver side
    (age 0 + many large credits) and on the sender side (tiny inter-txn gap).
    """
    rows: list[dict] = []

    for _ in range(N_VELOCITY_BURSTS):
        mule = make_merchant_vpa(fake, rng, used) if rng.random() < 0.35 else make_personal_vpa(fake, rng, used)
        burst_start = random_fraud_timestamp(rng)
        if burst_start > END_DATE - timedelta(minutes=20):
            burst_start -= timedelta(hours=1)

        victims = rng.choice(N_SENDERS, size=len(TRANSFERS_PER_VICTIM), replace=False)
        # Shuffled so it is not always the first victim who sends twice.
        transfers_per_victim = list(TRANSFERS_PER_VICTIM)
        random.shuffle(transfers_per_victim)
        offset = 0

        for victim_idx, n_transfers in zip(victims, transfers_per_victim):
            sender = senders.at[int(victim_idx), "vpa"]
            city = senders.at[int(victim_idx), "city"]
            offset += int(rng.integers(20, 150))          # next victim joins the burst

            for _ in range(n_transfers):
                amount = float(np.clip(rng.integers(15_000, 90_000), 15_000, 99_999))
                rows.append(
                    _row(
                        burst_start + timedelta(seconds=offset),
                        sender, city, mule, amount, 0, "new_vpa_velocity",
                    )
                )
                offset += int(rng.integers(30, 210))      # repeat transfer, seconds apart

    return rows


def generate_odd_hour_phishing(
    senders: pd.DataFrame, fake: Faker, rng: np.random.Generator, used: set[str]
) -> list[dict]:
    """Signature 3 - odd-hour phishing.

    Large transfers (Rs.20,000+) between 01:00 and 04:00, when genuine UPI volume
    is minimal (see HOUR_WEIGHTS). Typically a compromised credential or a
    screen-sharing scam draining the account while the victim is asleep; the
    receiver is a recently registered VPA.
    """
    rows: list[dict] = []
    victims = rng.choice(N_SENDERS, size=N_ODD_HOUR, replace=False)

    for victim_idx in victims:
        sender = senders.at[int(victim_idx), "vpa"]
        city = senders.at[int(victim_idx), "city"]
        receiver = make_personal_vpa(fake, rng, used)

        # Hours 1-3 inclusive covers 01:00:00 - 03:59:59.
        ts = random_fraud_timestamp(rng, hours=range(1, 4))
        # Offset above the Rs.20,000 floor instead of clipped to it, so amounts do
        # not bunch up on the threshold.
        amount = float(min(20_000 + np.exp(rng.normal(9.4, 0.8)), 99_999))
        rows.append(_row(ts, sender, city, receiver, amount, int(rng.integers(0, 21)), "odd_hour_phishing"))

    return rows


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Add UUIDs, derive `time_since_last_txn_sec` per sender, order as a stream."""
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Recency is computed per sender across the merged legit + fraud stream, so the
    # Rs.1-test and velocity bursts naturally show near-zero gaps.
    df = df.sort_values(["sender_vpa", "timestamp"], kind="mergesort")
    gap = df.groupby("sender_vpa", sort=False)["timestamp"].diff().dt.total_seconds()
    df["time_since_last_txn_sec"] = gap.fillna(-1).round().astype("int64")  # -1 = first txn seen

    df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    df["transaction_id"] = [str(uuid.uuid4()) for _ in range(len(df))]
    return df[COLUMNS]


def report(df: pd.DataFrame) -> None:
    """Print sanity checks so the dataset can be trusted before modelling."""
    fraud = df[df["is_fraud"] == 1]
    print(f"\nRows: {len(df):,}   unique ids: {df['transaction_id'].nunique():,}")
    print(f"Window: {df['timestamp'].min()} -> {df['timestamp'].max()}")
    print(f"Fraud: {len(fraud):,} ({len(fraud) / len(df):.3%})")

    print("\nFraud pattern breakdown:")
    print(df.loc[df["is_fraud"] == 1, "fraud_pattern"].value_counts().to_string())

    print("\nAmount profile by class:")
    print(df.groupby("is_fraud")["amount"].describe()[["mean", "50%", "min", "max"]].round(2).to_string())

    legit = df[df["is_fraud"] == 0]
    small_share = legit["amount"].between(10, 500).mean()
    print(f"\nLegit micro-payments (Rs.10-500): {small_share:.1%}")

    # The Rs.1 test must always come with a 10,000+ follow-up within 60 seconds.
    pairs = df[df["fraud_pattern"] == "rupee_1_test"].sort_values(["sender_vpa", "timestamp"])
    follow_up = pairs[pairs["amount"] > 1]
    print(f"Rs.1 probes: {(pairs['amount'] == 1).sum()} | "
          f"follow-ups >= Rs.10,000 within 60s: "
          f"{((follow_up['amount'] >= 10_000) & follow_up['time_since_last_txn_sec'].between(0, 60)).sum()}")

    velocity = df[df["fraud_pattern"] == "new_vpa_velocity"]
    print(f"Velocity rows on age-0 VPAs: {(velocity['receiver_vpa_age_days'] == 0).sum()}/{len(velocity)} "
          f"across {velocity['receiver_vpa'].nunique()} mule accounts")

    odd = df[df["fraud_pattern"] == "odd_hour_phishing"]
    print(f"Odd-hour rows in 01:00-04:00 and >= Rs.20,000: "
          f"{(odd['timestamp'].dt.hour.between(1, 3) & (odd['amount'] >= 20_000)).sum()}/{len(odd)}")

    night_legit = legit[legit["timestamp"].dt.hour.between(1, 3)]
    print(f"Legit 01:00-04:00 traffic: {len(night_legit):,} rows "
          f"({len(night_legit) / len(legit):.2%}), {(night_legit['amount'] >= 20_000).sum()} of them >= Rs.20,000")

    # Class overlap: none of these should be zero, or the labels leak through a
    # single threshold and the model has nothing interesting to learn.
    print("\nDeliberate class overlap (legitimate rows that mimic fraud features):")
    print(f"  amount <= Rs.5           : {(legit['amount'] <= 5).sum():,}")
    print(f"  amount >= Rs.15,000      : {(legit['amount'] >= 15_000).sum():,}")
    print(f"  receiver_vpa_age_days = 0: {(legit['receiver_vpa_age_days'] == 0).sum():,}")
    print(f"  time_since_last < 60s    : {legit['time_since_last_txn_sec'].between(0, 60).sum():,}")

    # The point of the new-adopter population: a model that splits on account age
    # alone should end up with poor precision. `fraud share` is the precision a
    # classifier would get from the rule "receiver_vpa_age_days <= k, therefore
    # fraud". If it stays low, age is a hint and not an answer.
    print("\nReceiver-VPA age overlap (can account age alone separate the classes?):")
    print(f"  {'age <= k':>10} {'legit':>9} {'fraud':>7} {'fraud share':>13}")
    for k in (0, 1, 2, 7, 20):
        n_legit = int((legit["receiver_vpa_age_days"] <= k).sum())
        n_fraud = int((fraud["receiver_vpa_age_days"] <= k).sum())
        share = n_fraud / (n_legit + n_fraud) if (n_legit + n_fraud) else 0.0
        print(f"  {k:>10} {n_legit:>9,} {n_fraud:>7,} {share:>12.1%}")

    young_legit = legit[legit["receiver_vpa_age_days"] <= 2]
    print(f"\nLegit traffic to VPAs <= 2 days old: {len(young_legit):,} rows "
          f"({len(young_legit) / len(legit):.1%} of legitimate volume), "
          f"median Rs.{young_legit['amount'].median():,.0f}, "
          f"{young_legit['amount'].between(10, 500).mean():.0%} micro-payments, "
          f"{young_legit['timestamp'].dt.hour.between(1, 3).mean():.1%} at 01:00-04:00")

    # Closing the age gap alone just moves the shortcut to "new receiver AND large
    # amount", so that pair is worth measuring too.
    for label, age_cut, amt_cut in (("age <= 20 and amount >= Rs.15,000", 20, 15_000),
                                    ("age <=  2 and amount >= Rs.20,000", 2, 20_000)):
        n_legit = int(((legit["receiver_vpa_age_days"] <= age_cut) & (legit["amount"] >= amt_cut)).sum())
        n_fraud = int(((fraud["receiver_vpa_age_days"] <= age_cut) & (fraud["amount"] >= amt_cut)).sum())
        share = n_fraud / (n_legit + n_fraud) if (n_legit + n_fraud) else 0.0
        print(f"  {label}: {n_legit:,} legit vs {n_fraud:,} fraud -> fraud share {share:.1%}")


def main() -> None:
    assert N_ODD_HOUR > 0, "Fraud budget over-allocated: reduce the pair/burst counts."

    random.seed(SEED)
    Faker.seed(SEED)
    fake = Faker("en_IN")
    rng = np.random.default_rng(SEED)

    print("Building account population ...")
    used_vpas: set[str] = set()
    senders = build_sender_pool(fake, rng, used_vpas)
    receivers = build_receiver_pool(fake, rng, used_vpas)
    adopters = build_new_adopter_pool(fake, rng, used_vpas)

    print(f"Generating {N_LEGIT:,} legitimate transactions ...")
    legit_df = generate_legitimate(senders, receivers, adopters, rng)

    print(f"Injecting {N_FRAUD:,} fraudulent transactions ...")
    fraud_rows = (
        generate_rupee_one_test(senders, fake, rng, used_vpas)
        + generate_new_vpa_velocity(senders, fake, rng, used_vpas)
        + generate_odd_hour_phishing(senders, fake, rng, used_vpas)
    )
    fraud_df = pd.DataFrame(fraud_rows)

    df = finalize(pd.concat([legit_df, fraud_df], ignore_index=True))

    df.to_csv(OUTPUT_CSV, index=False)
    print(f"\nSaved {OUTPUT_CSV.name} ({OUTPUT_CSV.stat().st_size / 1e6:.1f} MB)")
    report(df)


if __name__ == "__main__":
    main()
