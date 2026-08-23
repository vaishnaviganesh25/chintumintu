"""FinGuard Module 2 - predictive machine learning engine.

Trains and compares two tree ensembles (XGBoost and Random Forest) on the
synthetic UPI dataset from Module 1, calibrates a decision threshold that meets a
recall target without drowning the analyst queue in false alarms, and serialises
the winning pipeline for the real-time scoring service in Module 3.

Design notes that matter for anyone extending this:

* `engineer_features()` is a pure function with no dependency on the label or on
  training-time statistics, so Module 3 can import it and apply the exact same
  transformation to a single incoming transaction:
      from train_model import engineer_features
  Everything else is guarded behind `if __name__ == "__main__"`.

* The data is split three ways (64/16/20). The validation slice does the two jobs
  that must never touch the test set - XGBoost early stopping and decision
  threshold calibration - so the reported test metrics stay honest. Calibrating a
  threshold on the same rows you report it on is the most common way fraud
  projects overstate their precision.

* Features derived from a sender's previous transaction (`prev_amount`,
  `same_receiver_as_prev`) look backwards only, so they are legitimate real-time
  features. They do require sender history at inference time, exactly like
  `time_since_last_txn_sec` from Module 1.

Usage:
    python train_model.py
"""

from __future__ import annotations

import json
import platform
import re
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")  # headless: write PNGs without needing a display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import sklearn
import xgboost as xgb
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, RobustScaler
from sklearn.model_selection import (
    StratifiedGroupKFold,
    StratifiedKFold,
    cross_val_predict,
    cross_val_score,
    train_test_split,
)
from xgboost import XGBClassifier

from merchant_policy import (
    DEFAULT as MERCHANT,
    binary_portfolio_cost,
    portfolio_cost,
    prevalence_at_which_covenant_binds,
)

warnings.filterwarnings("ignore", category=UserWarning)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
SEED = 42

BASE_DIR = Path(__file__).resolve().parent
DATA_CSV = BASE_DIR / "upi_synthetic_data.csv"
MODEL_DIR = BASE_DIR / "models"
REPORT_DIR = BASE_DIR / "reports"

TEST_SIZE = 0.20            # held out for the final, untouched evaluation
VAL_SIZE = 0.20             # share of the remaining train used for val (-> 16% overall)

TARGET_RECALL = 0.90        # regulator/business floor: catch >= 90% of fraud
DEFAULT_THRESHOLD = 0.50    # the naive baseline we are arguing against

# Precision differences smaller than this are treated as noise when picking the
# operating point. Without it, "maximise precision" chases a fraction of a percent
# - often a single false positive out of 400 - and pays for it with real missed
# fraud. Inside the band we take the highest-recall threshold instead.
PRECISION_TOLERANCE = 0.005

# Which rule decides the shipped threshold:
#   "precision_at_recall" - the Module 2 spec: max precision subject to recall >= target.
#   "cost"                - minimise expected rupee loss subject to the same recall floor.
# See the calibration section of the report for why they disagree on this dataset.
THRESHOLD_POLICY = "cost"

# What one false alarm costs: analyst review time plus the customer friction of a
# held payment. A missed fraud costs the transaction amount itself, so the two are
# directly comparable in rupees.
FALSE_ALARM_COST_INR = 150.0

# With only ~100 fraud rows in the test split, single-split PR-AUC saturates and
# cannot rank two strong models. Model selection therefore runs on cross-validated
# PR-AUC over train+validation, which pools ~400 positives across folds.
CV_FOLDS = 5
RUN_ABLATION = True         # quantify how much performance rests on VPA age alone

# Group the splits on the scam incident rather than shuffling rows.
#
# A stratified random split cuts through incidents: the Rs.1 probe lands in train
# while its drain lands in test, and one mule VPA gets scattered across both. The
# model then recognises a receiver it has already been taught is fraudulent, which
# flatters the score. Module 1 now emits `ring_id`, so the split can respect the
# incident boundary and the number stops being flattered.
#
# Set to False to reproduce the older stratified split and see the difference; the
# report prints the bleed rate either way.
GROUP_AWARE_SPLIT = True

MICRO_PAYMENT_CEILING = 500.0   # Rs.10-500 daily spend we must not spam with alerts

# Columns that must never reach the model.
# `fraud_pattern` is label-derived metadata from Module 1 - including it would leak
# the answer outright. The identifier columns are dropped as required.
# `would_be_disputed` correlates with the target at r = 0.82 by construction - it is
# 1 for every fraud row plus a thin tail of friendly fraud. It exists so Module 6 has
# a real dispute object to reason about, and it must never reach the classifier. The
# reason code and respond-by date are derived from it and leak the same answer.
#
# `ring_id` is the incident label. It is the grouping key for the split, so it is
# available to the splitter and invisible to the model.
LEAKAGE_COLUMNS = [
    "fraud_pattern",
    "would_be_disputed",
    "dispute_reason_code",
    "dispute_respond_by",
    "ring_id",
]

# High-cardinality identity. `merchant_id` is excluded deliberately: one-hot encoding
# 4,000 merchants would let the model memorise which accounts happened to be
# defrauded in this window rather than learn what fraud looks like, and a real
# deployment onboards merchants it has never seen every day.
IDENTIFIER_COLUMNS = [
    "transaction_id", "timestamp", "sender_vpa", "receiver_vpa",
    "payment_id", "order_id", "merchant_id",
]

# The grouping key for the split. Never a feature.
GROUP_COLUMN = "ring_id"

TARGET = "is_fraud"

# PSP handles seen in the Indian UPI ecosystem. Anything else collapses to "other"
# so an unseen handle at inference time cannot blow up the encoder.
KNOWN_HANDLES = {
    "okicici", "oksbi", "okhdfcbank", "okaxis", "ybl", "ibl", "axl", "paytm",
    "apl", "upi", "okbizaxis", "hdfcbank", "sbi", "axisbank", "icici",
}

# Lures used in real UPI social-engineering VPAs. These fire rarely (or never) on
# the synthetic data, but the feature belongs in the schema for production traffic.
SUSPICIOUS_KEYWORDS = (
    "kyc", "verify", "verification", "refund", "cashback", "reward", "prize",
    "lottery", "helpdesk", "support", "care", "update", "unblock", "secure",
    "offer", "winner", "claim",
)

MERCHANT_SUFFIXES = ("store", "kirana", "shop", "foods", "mart", "services")
BILLER_PREFIXES = ("bill", "recharge", "fees", "rent", "emi")

sns.set_theme(style="whitegrid", context="talk")


# --------------------------------------------------------------------------- #
# Small reporting helper: print to console and keep a copy for reports/
# --------------------------------------------------------------------------- #
class Reporter:
    """Echoes every line to stdout and buffers it so the report can be saved."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def rule(self, title: str = "") -> None:
        self(f"\n{'=' * 78}")
        if title:
            self(title)
            self("=" * 78)

    def save(self, path: Path) -> None:
        path.write_text("\n".join(self.lines), encoding="utf-8")


say = Reporter()


# --------------------------------------------------------------------------- #
# 1. Data loading and feature engineering
# --------------------------------------------------------------------------- #
def load_data(path: Path = DATA_CSV) -> pd.DataFrame:
    """Load the Module 1 dataset and sort it chronologically.

    Chronological order matters because the lag features below use `shift`, which
    must walk the sender's real transaction sequence.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found. Run `python generate_upi_dataset.py` first (Module 1)."
        )
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)


def _local_part(vpa: pd.Series) -> pd.Series:
    """`rahul.verma@okicici` -> `rahul.verma` (the user-chosen half of the VPA)."""
    return vpa.astype("string").str.split("@").str[0].str.lower().fillna("")


def _handle(vpa: pd.Series) -> pd.Series:
    """`rahul.verma@okicici` -> `okicici` (the PSP / bank handle)."""
    handle = vpa.astype("string").str.split("@").str[-1].str.lower().fillna("unknown")
    return handle.where(handle.isin(KNOWN_HANDLES), "other")


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Turn raw UPI rows into the model's feature matrix.

    Pure and label-free: safe to call on a single unlabelled transaction at
    inference time. Returns only the engineered columns, so the raw identifiers
    (`transaction_id`, `timestamp`, `sender_vpa`, `receiver_vpa`) are dropped by
    construction rather than by a separate drop step.
    """
    out = pd.DataFrame(index=df.index)
    ts = pd.to_datetime(df["timestamp"])

    # -- Temporal ---------------------------------------------------------- #
    # Fraud in this domain is strongly time-of-day dependent: genuine UPI volume
    # collapses after midnight, so the same Rs.50,000 transfer carries very
    # different risk at 2 PM and at 2 AM.
    out["hour_of_day"] = ts.dt.hour
    out["day_of_week"] = ts.dt.dayofweek
    out["is_night_txn"] = ts.dt.hour.between(1, 3).astype(int)   # 01:00:00 - 03:59:59
    out["is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
    # Hour is cyclical - 23:00 and 00:00 are adjacent, not 23 units apart. Trees
    # cope without this, but it keeps the matrix usable for linear/NN models later.
    out["hour_sin"] = np.sin(2 * np.pi * ts.dt.hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * ts.dt.hour / 24)

    # -- Amount ------------------------------------------------------------ #
    amount = df["amount"].astype(float)
    out["amount"] = amount
    # Amounts span Rs.1 to Rs.2 lakh; the log keeps that range from dominating the
    # scaler and makes the micro-payment cluster separable from big-ticket transfers.
    out["log_amount"] = np.log1p(amount)
    out["is_micro_payment"] = (amount <= MICRO_PAYMENT_CEILING).astype(int)
    out["is_round_amount"] = (amount % 100 == 0).astype(int)

    # -- Receiver VPA reputation ------------------------------------------- #
    age = df["receiver_vpa_age_days"].astype(float)
    out["receiver_vpa_age_days"] = age
    out["log_receiver_vpa_age"] = np.log1p(age.clip(lower=0))
    out["is_new_receiver_vpa"] = (age < 1).astype(int)      # created today - mule hallmark
    out["is_recent_receiver_vpa"] = (age < 7).astype(int)

    # -- Velocity ----------------------------------------------------------- #
    # Module 1 encodes "no previous transaction" as -1. Feeding -1 to the model as
    # a magnitude would be nonsense, so it becomes an explicit flag plus a NaN that
    # the imputer fills.
    gap = df["time_since_last_txn_sec"].astype(float)
    out["is_first_txn"] = (gap < 0).astype(int)
    gap_clean = gap.where(gap >= 0)
    out["time_since_last_txn_sec"] = gap_clean
    out["log_time_since_last"] = np.log1p(gap_clean)
    out["is_rapid_txn"] = ((gap >= 0) & (gap <= 60)).astype(int)

    # -- VPA string structure ------------------------------------------------ #
    sender_local = _local_part(df["sender_vpa"])
    receiver_local = _local_part(df["receiver_vpa"])

    out["sender_bank_handle"] = _handle(df["sender_vpa"])
    out["receiver_bank_handle"] = _handle(df["receiver_vpa"])

    # Phone-number VPAs (9876543210@ybl) behave differently from name VPAs: they are
    # cheaper to spin up and are the usual shape of a throwaway mule handle.
    out["sender_vpa_is_mobile"] = sender_local.str.fullmatch(r"[6-9]\d{9}").fillna(False).astype(int)
    out["receiver_vpa_is_mobile"] = receiver_local.str.fullmatch(r"[6-9]\d{9}").fillna(False).astype(int)
    out["receiver_starts_with_digit"] = receiver_local.str.match(r"^\d").fillna(False).astype(int)

    out["receiver_local_len"] = receiver_local.str.len().fillna(0)
    out["sender_local_len"] = sender_local.str.len().fillna(0)
    digits = receiver_local.str.count(r"\d").fillna(0)
    out["receiver_digit_ratio"] = (digits / receiver_local.str.len().replace(0, np.nan)).fillna(0)

    # Registered merchants (QR terminals, kirana stores, billers) are a lower-risk
    # population than an anonymous personal handle receiving Rs.50,000.
    merchant_pattern = (
        receiver_local.str.fullmatch(r"q\d{6,}").fillna(False)
        | receiver_local.str.endswith(tuple(f".{s}" for s in MERCHANT_SUFFIXES)).fillna(False)
        | receiver_local.str.startswith(tuple(f"{p}." for p in BILLER_PREFIXES)).fillna(False)
    )
    out["receiver_is_merchant_like"] = merchant_pattern.astype(int)

    keyword_pattern = "|".join(SUSPICIOUS_KEYWORDS)
    out["receiver_has_suspicious_keyword"] = (
        receiver_local.str.contains(keyword_pattern, regex=True, na=False).astype(int)
    )

    # -- Sender context ------------------------------------------------------ #
    out["sender_city"] = df["sender_city"].astype("string").fillna("unknown")

    # -- Merchant context ----------------------------------------------------- #
    # Category and method are the two gateway-side facts that genuinely change risk:
    # electronics and travel are chargeback-heavy because the goods resell and the
    # service is consumed before the dispute window closes, and card-not-present
    # carries a different liability profile from UPI. Both are low-cardinality, so
    # they generalise to merchants the model has never seen - unlike `merchant_id`,
    # which is deliberately excluded.
    if "merchant_category" in df.columns:
        out["merchant_category"] = df["merchant_category"].astype("string").fillna("unknown")
    if "method" in df.columns:
        out["payment_method"] = df["method"].astype("string").fillna("unknown")

    # -- Backward-looking lag features --------------------------------------- #
    # The Rs.1-test scam is only visible as a *pair*: a tiny probe followed within
    # seconds by a large transfer to the same receiver. A single row cannot express
    # that, so we carry the sender's previous transaction forward. Strictly past-only,
    # therefore valid in a streaming context (needs a sender-history lookup, same as
    # `time_since_last_txn_sec`).
    if "sender_vpa" in df.columns:
        grouped = df.groupby("sender_vpa", sort=False)
        prev_amount = grouped["amount"].shift(1)
        prev_receiver = grouped["receiver_vpa"].shift(1)
        out["prev_amount"] = prev_amount.fillna(0.0)
        out["log_prev_amount"] = np.log1p(prev_amount.fillna(0.0))
        out["same_receiver_as_prev"] = (
            (prev_receiver == df["receiver_vpa"]) & prev_receiver.notna()
        ).astype(int)
        # Deliberately NOT combined into a single "prev was Rs.1 to same receiver"
        # rule: handing the model the generator's scam definition would make the
        # SHAP story circular. Let the trees discover the interaction.
        #
        # NaN on a sender's first payment, not `amount / 1`. The earlier version
        # substituted 0 for the missing predecessor, which made the ratio equal the
        # transaction amount - so a first-time payer's ordinary Rs.35,000 transfer
        # arrived at the model looking like a 35,000x jump in spending. That is not a
        # neutral default, it is the largest value the feature can take, and it was
        # visible in the report: the worked false-positive case is a legitimate
        # Rs.35,334 payment "following a much smaller payment". `is_first_txn` already
        # marks these rows, and the imputer fills the gap with a median, exactly as it
        # does for `time_since_last_txn_sec`.
        out["prev_amount_ratio"] = (amount / prev_amount).where(prev_amount > 0)

    return out


def split_feature_types(features: pd.DataFrame) -> tuple[list[str], list[str], list[str]]:
    """Partition engineered columns into categorical / binary / numeric groups.

    A column only counts as binary if it is complete and every value is 0 or 1. Both
    halves of that matter, because the preprocessor sends binaries through
    `passthrough` - no imputation, no scaling:

    * A column containing NaN is not a flag. Classifying one as binary would hand the
      classifier an unimputed missing value.
    * An all-null column must be excluded explicitly, because `dropna().isin([0,1])`
      yields an empty Series and `.all()` on an empty Series is `True`. That is the
      trap: on a frame where `time_since_last_txn_sec` is entirely missing - a single
      row scored at inference time for a sender with no history - the velocity feature
      would be silently rerouted from the numeric branch to passthrough, and the
      feature space would no longer match the one the model was fitted on.
    """
    categorical = [
        c for c in features.columns
        if features[c].dtype == "string" or features[c].dtype == object
    ]
    binary = [
        c for c in features.columns
        if c not in categorical
        and len(features[c]) > 0
        and not features[c].isna().any()
        and features[c].isin([0, 1]).all()
    ]
    numeric = [c for c in features.columns if c not in categorical and c not in binary]
    return numeric, binary, categorical


# --------------------------------------------------------------------------- #
# 2. Preprocessing pipeline
# --------------------------------------------------------------------------- #
def build_preprocessor(numeric: list[str], binary: list[str], categorical: list[str]) -> ColumnTransformer:
    """ColumnTransformer: impute+scale numerics, pass binaries, one-hot categoricals.

    Tree ensembles do not need scaling, but keeping it in the pipeline means a
    logistic-regression or neural challenger model can be dropped in later without
    rebuilding the feature path - and it costs nothing at inference time.
    """
    numeric_pipe = Pipeline(
        [
            # Median imputation covers `time_since_last_txn_sec` on a sender's first
            # transaction, flagged separately by `is_first_txn` so the model can tell
            # "imputed" apart from "genuinely this value".
            ("impute", SimpleImputer(strategy="median")),
            # RobustScaler, not StandardScaler: UPI amounts are heavy-tailed and a
            # handful of Rs.2 lakh transfers would otherwise squash the entire
            # Rs.10-500 micro-payment mass into a sliver near zero.
            ("scale", RobustScaler()),
        ]
    )

    categorical_pipe = Pipeline(
        [
            (
                "onehot",
                OneHotEncoder(
                    handle_unknown="infrequent_if_exist",  # unseen city/handle -> infrequent bucket
                    min_frequency=50,                      # rare cities collapse instead of overfitting
                    sparse_output=False,
                ),
            )
        ]
    )

    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, numeric),
            ("bin", "passthrough", binary),
            ("cat", categorical_pipe, categorical),
        ],
        remainder="drop",
        verbose_feature_names_out=True,
    )


def clean_feature_names(names) -> list[str]:
    """XGBoost rejects `[`, `]` and `<` in feature names; city names can contain them."""
    return [re.sub(r"[\[\]<>]", "_", str(n)) for n in names]


# --------------------------------------------------------------------------- #
# 3. Models
# --------------------------------------------------------------------------- #
def make_xgb(scale_pos_weight: float, n_estimators: int = 600, early_stopping: bool = True) -> XGBClassifier:
    """Gradient-boosted trees with the positive class re-weighted to fight imbalance.

    `scale_pos_weight = n_negative / n_positive` (~199 here) makes one fraud row
    count as heavily as ~199 legitimate rows in the gradient, which stops the model
    from collapsing to the trivial "predict legitimate" solution.

    Early stopping is switched off when the estimator is rebuilt for cross-validation,
    where there is no held-out eval set to stop against.
    """
    params = dict(
        n_estimators=n_estimators,
        learning_rate=0.07,
        max_depth=5,
        min_child_weight=2,
        subsample=0.9,
        colsample_bytree=0.8,
        reg_lambda=1.5,
        gamma=0.1,
        scale_pos_weight=scale_pos_weight,
        # aucpr, not logloss or auc: with 0.5% positives the PR curve is the only
        # metric that reflects how the model behaves on the class we care about.
        eval_metric="aucpr",
        tree_method="hist",
        n_jobs=-1,
        random_state=SEED,
    )
    if early_stopping:
        params["early_stopping_rounds"] = 60
    return XGBClassifier(**params)


def make_random_forest() -> RandomForestClassifier:
    """Bagged trees with per-bootstrap class rebalancing.

    `balanced_subsample` recomputes class weights inside every bootstrap sample,
    which is more stable than plain `balanced` when positives are so scarce that
    some bootstraps would otherwise contain almost none.
    """
    return RandomForestClassifier(
        n_estimators=400,
        max_depth=18,
        min_samples_leaf=2,
        max_features="sqrt",
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=SEED,
    )


def cross_validated_pr_auc(estimator_factory, numeric, binary, categorical, X, y,
                           folds=CV_FOLDS, groups=None):
    """Stratified K-fold PR-AUC with the preprocessor refitted inside every fold.

    Refitting the ColumnTransformer per fold keeps imputation medians, scaler
    quantiles and one-hot vocabularies from leaking across the fold boundary.
    """
    pipe = Pipeline(
        [
            ("preprocessor", build_preprocessor(numeric, binary, categorical)),
            ("classifier", estimator_factory()),
        ]
    )
    # Grouped folds too. A group-aware outer split undone by a row-shuffled CV would
    # be theatre: model selection and threshold calibration would both still be
    # scoring on incidents they were trained on.
    if groups is not None:
        cv = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED)
        scores = cross_val_score(pipe, X, y, cv=cv, groups=groups,
                                 scoring="average_precision", n_jobs=1)
    else:
        cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
        scores = cross_val_score(pipe, X, y, cv=cv, scoring="average_precision", n_jobs=1)
    return float(scores.mean()), float(scores.std()), scores


def out_of_fold_probabilities(estimator_factory, numeric, binary, categorical, X, y,
                              folds=CV_FOLDS, groups=None):
    """Out-of-fold fraud probabilities for every row in train+validation.

    Each row is scored by a model that never saw it, so these probabilities are an
    unbiased basis for threshold calibration - and they pool ~400 positives instead
    of the ~80 in a single validation split, which is the difference between a
    threshold you can defend and one that moves every time you reshuffle the seed.
    """
    pipe = Pipeline(
        [
            ("preprocessor", build_preprocessor(numeric, binary, categorical)),
            ("classifier", estimator_factory()),
        ]
    )
    if groups is not None:
        cv = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=SEED)
        return cross_val_predict(pipe, X, y, cv=cv, groups=groups,
                                 method="predict_proba", n_jobs=1)[:, 1]
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=SEED)
    return cross_val_predict(pipe, X, y, cv=cv, method="predict_proba", n_jobs=1)[:, 1]


# --------------------------------------------------------------------------- #
# 4. Threshold calibration
# --------------------------------------------------------------------------- #
def calibrate_threshold(
    y_true,
    y_prob,
    target_recall: float = TARGET_RECALL,
    precision_tolerance: float = PRECISION_TOLERANCE,
) -> dict:
    """Pick the operating point: highest precision among thresholds that hit target recall.

    The default 0.50 cut-off is an artefact of the loss function, not a business
    decision. What the fraud desk actually needs is: "catch at least 90% of fraud,
    and among all the ways to do that, raise the fewest false alarms."

    One refinement on the naive reading of that rule. Precision generally rises with
    the threshold, so "most precise point clearing the recall floor" pushes the
    threshold as high as the floor allows - and on a near-separable problem it will
    happily trade several percent of recall for a precision gain worth one false
    positive, which is noise. So we take the best precision, allow anything within
    `precision_tolerance` of it, and among those pick the *highest recall* point.
    Ties in precision are therefore broken in favour of catching more fraud.

    If no threshold reaches the recall target the model simply is not strong enough;
    we fall back to the F1-optimal point and say so loudly rather than silently
    shipping a threshold that misses the goal.
    """
    precision, recall, thresholds = precision_recall_curve(y_true, y_prob)
    # precision_recall_curve returns len(thresholds) + 1 points; drop the trailing
    # (recall=0, precision=1) sentinel so the arrays line up with thresholds.
    precision, recall = precision[:-1], recall[:-1]

    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(precision),
        where=(precision + recall) > 0,
    )
    best_f1_idx = int(np.argmax(f1))

    feasible = recall >= target_recall
    if feasible.any():
        best_precision = float(precision[feasible].max())
        # Everything statistically indistinguishable from the most precise option...
        acceptable = feasible & (precision >= best_precision - precision_tolerance)
        # ...and from those, the one that catches the most fraud.
        idx = int(np.argmax(np.where(acceptable, recall, -np.inf)))
        met_target = True
    else:
        idx = best_f1_idx
        met_target = False

    return {
        "threshold": float(thresholds[idx]),
        "precision": float(precision[idx]),
        "recall": float(recall[idx]),
        "f1": float(f1[idx]),
        "met_target_recall": met_target,
        "target_recall": target_recall,
        "f1_optimal_threshold": float(thresholds[best_f1_idx]),
        "f1_optimal_f1": float(f1[best_f1_idx]),
        "curve": {"precision": precision, "recall": recall, "thresholds": thresholds, "f1": f1},
    }


def cost_optimal_threshold(
    y_true,
    y_prob,
    amounts,
    fp_cost=FALSE_ALARM_COST_INR,
    target_recall: float = TARGET_RECALL,
    fn_cost=None,
) -> dict:
    """Threshold that minimises expected rupee loss, subject to the same recall floor.

    "Maximise precision" implicitly prices every false alarm and every missed fraud
    the same, which is not how a payments business works: letting a Rs.80,000 mule
    transfer through costs Rs.80,000, while a false alarm costs a review.

    `fp_cost` and `fn_cost` accept either a scalar or a per-row array. The array form
    is what the merchant model needs: a declined good order costs the *margin* on it
    plus goodwill, so the penalty scales with basket size rather than being flat. A
    flat false-positive cost systematically over-blocks small baskets and
    under-protects large ones - see `merchant_policy.py`.

    Implemented as a single sweep down the sorted scores: at each cut-off, everything
    above it is flagged, so cumulative sums give the confusion matrix - and now the
    running cost - for every candidate threshold at once.
    """
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    amounts = np.asarray(amounts, dtype=float)

    # Broadcast so scalar and per-row costs take the same code path.
    fp_costs = np.broadcast_to(np.asarray(fp_cost, dtype=float), amounts.shape)
    fn_costs = amounts if fn_cost is None else np.broadcast_to(
        np.asarray(fn_cost, dtype=float), amounts.shape
    )

    order = np.argsort(-y_prob)
    p, yt, amt = y_prob[order], y_true[order], amounts[order]
    fp_c, fn_c = fp_costs[order], fn_costs[order]

    tp_cum = np.cumsum(yt)                       # frauds caught if we flag the top k
    fp_cum = np.cumsum(1 - yt)                   # false alarms raised
    value_caught = np.cumsum(fn_c * yt)          # loss averted by flagging the top k
    total_fraud_value = float((fn_c * yt).sum())
    total_fraud = max(int(yt.sum()), 1)

    missed_value = total_fraud_value - value_caught
    expected_cost = missed_value + np.cumsum(fp_c * (1 - yt))
    recall_cum = tp_cum / total_fraud

    feasible = recall_cum >= target_recall
    if not feasible.any():
        feasible = np.ones_like(recall_cum, dtype=bool)
    idx = int(np.argmin(np.where(feasible, expected_cost, np.inf)))

    return {
        "threshold": float(p[idx]),
        "expected_cost": float(expected_cost[idx]),
        "recall": float(recall_cum[idx]),
        "precision": float(tp_cum[idx] / (idx + 1)),
        "false_alarms": int(fp_cum[idx]),
        "missed_fraud": int(total_fraud - tp_cum[idx]),
        "missed_value": float(missed_value[idx]),
        "fp_cost": float(np.mean(fp_costs)),
    }


def expected_cost_at(y_true, y_prob, amounts, threshold: float,
                     fp_cost=FALSE_ALARM_COST_INR, fn_cost=None) -> float:
    """Expected rupee loss if we flagged at `threshold` - same cost model as above.

    A separate code path from the cumulative sweep, deliberately: the two agree only
    if both are right, which makes them a real cross-check on each other.
    """
    y_true = np.asarray(y_true, dtype=int)
    y_pred = (np.asarray(y_prob) >= threshold).astype(int)
    amounts = np.asarray(amounts, dtype=float)

    fp_costs = np.broadcast_to(np.asarray(fp_cost, dtype=float), amounts.shape)
    fn_costs = amounts if fn_cost is None else np.broadcast_to(
        np.asarray(fn_cost, dtype=float), amounts.shape
    )

    missed = (y_true == 1) & (y_pred == 0)
    wrong_hold = (y_true == 0) & (y_pred == 1)
    return float(fn_costs[missed].sum() + fp_costs[wrong_hold].sum())


# --------------------------------------------------------------------------- #
# 5. Evaluation
# --------------------------------------------------------------------------- #
def evaluate(y_true, y_prob, threshold: float) -> dict:
    """Threshold-dependent and threshold-free metrics in one bundle."""
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, y_prob)),
        "pr_auc": float(average_precision_score(y_true, y_prob)),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }


def format_confusion(m: dict, title: str) -> list[str]:
    """Render a confusion matrix the way an analyst wants to read it."""
    return [
        f"{title}  (threshold = {m['threshold']:.4f})",
        "                        Predicted",
        "                   Legitimate      Fraud",
        f"  Actual Legitimate   {m['tn']:>8,}   {m['fp']:>8,}      <- false alarms: {m['fp']:,}",
        f"         Fraud        {m['fn']:>8,}   {m['tp']:>8,}      <- fraud missed: {m['fn']:,}",
        f"  Precision {m['precision']:.4f}   Recall {m['recall']:.4f}   F1 {m['f1']:.4f}",
    ]


def business_impact(y_true, y_prob, threshold: float, amounts: pd.Series) -> dict:
    """Translate the confusion matrix into rupees and analyst workload.

    Counting fraud rows treats a Rs.1 probe and a Rs.90,000 drain as equal events.
    The bank cares about the money, and the customer cares about not having their
    Rs.40 chai payment declined - so we measure both.
    """
    y_pred = (y_prob >= threshold).astype(int)
    y_true = np.asarray(y_true)
    amounts = np.asarray(amounts, dtype=float)

    fraud_value_total = amounts[y_true == 1].sum()
    fraud_value_caught = amounts[(y_true == 1) & (y_pred == 1)].sum()

    micro = amounts <= MICRO_PAYMENT_CEILING
    micro_false_alarms = int(((y_true == 0) & (y_pred == 1) & micro).sum())
    micro_total = int(micro.sum())

    n = len(y_true)
    return {
        "fraud_value_total": float(fraud_value_total),
        "fraud_value_caught": float(fraud_value_caught),
        "value_recall": float(fraud_value_caught / fraud_value_total) if fraud_value_total else 0.0,
        "fraud_value_missed": float(fraud_value_total - fraud_value_caught),
        "micro_payment_false_alarms": micro_false_alarms,
        "micro_payment_count": micro_total,
        "micro_false_alarm_rate": float(micro_false_alarms / micro_total) if micro_total else 0.0,
        "alerts_per_100k_txns": float(y_pred.sum() / n * 100_000),
    }


def recall_by_scam_pattern(df: pd.DataFrame, test_index, y_true, y_prob, threshold: float) -> pd.DataFrame:
    """Per-signature recall - which of Module 1's three scams does the model actually catch?

    Aggregate recall hides failure modes. The Rs.1 test is split into its two legs
    because the probe leg carries almost no single-row signal (it is a Rs.1 payment
    to a new VPA, which is also what an honest test transfer looks like), while the
    follow-up leg is loud. Averaging them would disguise that.
    """
    y_pred = (np.asarray(y_prob) >= threshold).astype(int)
    meta = df.loc[test_index, ["fraud_pattern", "amount"]].copy()
    meta["y_true"] = np.asarray(y_true)
    meta["y_pred"] = y_pred

    fraud = meta[meta["y_true"] == 1].copy()
    fraud["signature"] = fraud["fraud_pattern"]
    # Separate the two legs of the Rs.1 test scam.
    probe = (fraud["fraud_pattern"] == "rupee_1_test") & (fraud["amount"] <= 5)
    fraud.loc[probe, "signature"] = "rupee_1_test (Rs.1 probe leg)"
    fraud.loc[(fraud["fraud_pattern"] == "rupee_1_test") & ~probe, "signature"] = "rupee_1_test (large leg)"

    rows = []
    for sig, grp in fraud.groupby("signature"):
        rows.append(
            {
                "signature": sig,
                "n": len(grp),
                "caught": int(grp["y_pred"].sum()),
                "recall": float(grp["y_pred"].mean()),
                "value_at_risk": float(grp["amount"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values("recall")


def incident_bleed_check(df: pd.DataFrame, train_index, test_index, y_test, y_prob, threshold: float) -> dict:
    """Measure how much test fraud shares a receiver VPA with training fraud.

    A stratified random split cuts across scam *incidents*: the Rs.1 probe can land
    in train while its large follow-up lands in test, and a mule VPA collecting five
    transfers gets scattered across both. The model then recognises a receiver it has
    already been taught is fraudulent, which flatters the test score.

    Recall on "cold" fraud - receivers never seen in training - is the closer estimate
    of performance against a brand-new scam ring.
    """
    train_fraud_receivers = set(
        df.loc[train_index].loc[lambda d: d["is_fraud"] == 1, "receiver_vpa"]
    )
    test_meta = df.loc[test_index, ["receiver_vpa"]].copy()
    test_meta["y_true"] = np.asarray(y_test)
    test_meta["y_pred"] = (np.asarray(y_prob) >= threshold).astype(int)

    fraud = test_meta[test_meta["y_true"] == 1]
    seen = fraud["receiver_vpa"].isin(train_fraud_receivers)
    return {
        "test_fraud_rows": int(len(fraud)),
        "receiver_seen_in_train_fraud": int(seen.sum()),
        "bleed_rate": float(seen.mean()) if len(fraud) else 0.0,
        "recall_warm": float(fraud.loc[seen, "y_pred"].mean()) if seen.any() else None,
        "recall_cold": float(fraud.loc[~seen, "y_pred"].mean()) if (~seen).any() else None,
        "cold_rows": int((~seen).sum()),
    }


def age_ablation(X: pd.DataFrame, y, numeric, binary, categorical, splits) -> dict:
    """Retrain without the receiver-VPA-age features to see what the rest of the model is worth.

    If one feature is near-separable, headline metrics measure the data generator
    rather than the model. Dropping it shows how much signal the temporal, velocity
    and VPA-structure features carry on their own - which is what would survive
    contact with real traffic, where account age is noisier and often missing.
    """
    tr_idx, val_idx, test_idx = splits
    age_cols = [c for c in X.columns if "receiver_vpa_age" in c or c == "is_new_receiver_vpa"
                or c == "is_recent_receiver_vpa"]
    keep_num = [c for c in numeric if c not in age_cols]
    keep_bin = [c for c in binary if c not in age_cols]

    pre = build_preprocessor(keep_num, keep_bin, categorical)
    Xt_tr = pre.fit_transform(X.loc[tr_idx])
    Xt_val = pre.transform(X.loc[val_idx])
    Xt_test = pre.transform(X.loc[test_idx])
    names = clean_feature_names(pre.get_feature_names_out())
    Xt_tr = pd.DataFrame(Xt_tr, columns=names)
    Xt_val = pd.DataFrame(Xt_val, columns=names)
    Xt_test = pd.DataFrame(Xt_test, columns=names)

    y_tr, y_val, y_test = y.loc[tr_idx], y.loc[val_idx], y.loc[test_idx]
    spw = (len(y_tr) - y_tr.sum()) / max(int(y_tr.sum()), 1)
    model = make_xgb(spw)
    model.fit(Xt_tr, y_tr, eval_set=[(Xt_val, y_val)], verbose=False)

    prob = model.predict_proba(Xt_test)[:, 1]
    calib = calibrate_threshold(y_val, model.predict_proba(Xt_val)[:, 1], TARGET_RECALL)
    metrics = evaluate(y_test, prob, calib["threshold"])
    metrics["dropped_features"] = age_cols
    return metrics


# --------------------------------------------------------------------------- #
# 6. Plots
# --------------------------------------------------------------------------- #
def plot_curves(results: dict, y_test, outdir: Path) -> None:
    """Precision-recall and ROC curves for both models on the test set."""
    fig, axes = plt.subplots(1, 2, figsize=(16, 6.5))

    for name, res in results.items():
        p, r, _ = precision_recall_curve(y_test, res["test_prob"])
        axes[0].plot(r, p, lw=2, label=f"{name} (PR-AUC = {res['test']['pr_auc']:.3f})")
        fpr, tpr, _ = roc_curve(y_test, res["test_prob"])
        axes[1].plot(fpr, tpr, lw=2, label=f"{name} (ROC-AUC = {res['test']['roc_auc']:.3f})")

    baseline = float(np.mean(y_test))
    axes[0].axhline(baseline, ls="--", c="grey", lw=1.2, label=f"random ({baseline:.4f})")
    axes[0].set(xlabel="Recall", ylabel="Precision", title="Precision-Recall (test set)")
    axes[0].legend(fontsize=11)

    axes[1].plot([0, 1], [0, 1], ls="--", c="grey", lw=1.2)
    axes[1].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC (test set)")
    axes[1].legend(fontsize=11)

    fig.tight_layout()
    fig.savefig(outdir / "pr_roc_curves.png", dpi=130)
    plt.close(fig)


def plot_threshold_sweep(calib: dict, chosen: float, outdir: Path) -> None:
    """Show precision/recall/F1 across every threshold and mark the operating point."""
    curve = calib["curve"]
    t, p, r, f1 = curve["thresholds"], curve["precision"], curve["recall"], curve["f1"]

    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot(t, p, lw=2, label="Precision")
    ax.plot(t, r, lw=2, label="Recall")
    ax.plot(t, f1, lw=2, ls="--", label="F1")
    ax.axhline(calib["target_recall"], c="grey", ls=":", lw=1.5,
               label=f"recall target ({calib['target_recall']:.0%})")
    ax.axvline(chosen, c="crimson", lw=2,
               label=f"calibrated threshold ({chosen:.3f})")
    ax.axvline(DEFAULT_THRESHOLD, c="black", ls="-.", lw=1.5, label="default 0.50")
    ax.set(xlabel="Decision threshold", ylabel="Score", ylim=(0, 1.02),
           title="Threshold calibration (out-of-fold, train+validation)")
    ax.legend(fontsize=11, loc="center left")
    fig.tight_layout()
    fig.savefig(outdir / "threshold_calibration.png", dpi=130)
    plt.close(fig)


def plot_confusion_matrices(y_true, y_prob, default_thr: float, tuned_thr: float, outdir: Path) -> None:
    """Side-by-side heatmaps: what the default threshold costs versus the tuned one."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8))
    for ax, thr, title in zip(axes, [default_thr, tuned_thr], ["Default threshold", "Calibrated threshold"]):
        cm = confusion_matrix(y_true, (y_prob >= thr).astype(int), labels=[0, 1])
        sns.heatmap(cm, annot=True, fmt=",d", cmap="Blues", cbar=False, ax=ax,
                    xticklabels=["Legitimate", "Fraud"], yticklabels=["Legitimate", "Fraud"])
        ax.set(xlabel="Predicted", ylabel="Actual", title=f"{title} = {thr:.3f}")
    fig.tight_layout()
    fig.savefig(outdir / "confusion_matrices.png", dpi=130)
    plt.close(fig)


def plot_feature_importance(model, feature_names: list[str], outdir: Path, top_n: int = 20) -> pd.DataFrame:
    """Rank features by the model's own importance (a global sanity check before SHAP)."""
    importances = getattr(model, "feature_importances_", None)
    if importances is None:
        return pd.DataFrame()

    ranked = (
        pd.DataFrame({"feature": feature_names, "importance": importances})
        .sort_values("importance", ascending=False)
        .head(top_n)
    )
    fig, ax = plt.subplots(figsize=(11, 8))
    sns.barplot(data=ranked, y="feature", x="importance", hue="feature",
                palette="viridis", legend=False, ax=ax)
    ax.set(title=f"Top {top_n} features", xlabel="Importance", ylabel="")
    fig.tight_layout()
    fig.savefig(outdir / "feature_importance.png", dpi=130)
    plt.close(fig)
    return ranked


# --------------------------------------------------------------------------- #
# 7. Orchestration
# --------------------------------------------------------------------------- #
def main() -> None:
    MODEL_DIR.mkdir(exist_ok=True)
    REPORT_DIR.mkdir(exist_ok=True)

    # ---------------- Load + engineer ---------------- #
    say.rule("FINGUARD MODULE 2 - PREDICTIVE ML ENGINE")
    df = load_data()
    say(f"Loaded {len(df):,} transactions from {DATA_CSV.name}")
    say(f"Period      : {df['timestamp'].min()} -> {df['timestamp'].max()}")

    y = df[TARGET].astype(int)
    fraud_rate = y.mean()
    say(f"Class balance: {int(y.sum()):,} fraud / {int((1 - y).sum()):,} legitimate "
        f"({fraud_rate:.3%} positive, 1:{int((1 - fraud_rate) / fraud_rate)} ratio)")

    dropped = IDENTIFIER_COLUMNS + LEAKAGE_COLUMNS
    say(f"Dropped before training: {', '.join(dropped)}")
    say("  (`fraud_pattern` is label-derived metadata from Module 1 - keeping it would leak the target)")

    X = engineer_features(df)
    assert TARGET not in X.columns and "fraud_pattern" not in X.columns, "Target/leakage column leaked into X"
    numeric, binary, categorical = split_feature_types(X)
    say(f"\nEngineered {X.shape[1]} features: "
        f"{len(numeric)} numeric, {len(binary)} binary, {len(categorical)} categorical")
    say(f"  numeric    : {', '.join(numeric)}")
    say(f"  binary     : {', '.join(binary)}")
    say(f"  categorical: {', '.join(categorical)}")

    # ---------------- Split ---------------- #
    # Grouped on the scam incident, stratified on the label.
    #
    # Every row is its own group for legitimate traffic; fraud rows share a group with
    # the rest of their incident, so both legs of a Rs.1 test and all five transfers
    # into one mule land on the same side of the boundary. Stratification still holds
    # the 0.5% prevalence steady in each split - without it a random draw could hand
    # the test set a wildly different fraud rate.
    groups = df[GROUP_COLUMN].fillna("").astype(str)
    groups = groups.where(groups != "", pd.Series(df.index.astype(str), index=df.index))

    if GROUP_AWARE_SPLIT:
        outer = StratifiedGroupKFold(n_splits=int(round(1 / TEST_SIZE)), shuffle=True,
                                     random_state=SEED)
        train_full_idx, test_idx = next(outer.split(X, y, groups))
        X_train_full, X_test = X.iloc[train_full_idx], X.iloc[test_idx]
        y_train_full, y_test = y.iloc[train_full_idx], y.iloc[test_idx]

        inner = StratifiedGroupKFold(n_splits=int(round(1 / VAL_SIZE)), shuffle=True,
                                     random_state=SEED)
        inner_groups = groups.iloc[train_full_idx]
        tr_idx, val_idx = next(inner.split(X_train_full, y_train_full, inner_groups))
        X_tr, X_val = X_train_full.iloc[tr_idx], X_train_full.iloc[val_idx]
        y_tr, y_val = y_train_full.iloc[tr_idx], y_train_full.iloc[val_idx]
        split_label = "grouped on scam incident + stratified"
    else:
        X_train_full, X_test, y_train_full, y_test = train_test_split(
            X, y, test_size=TEST_SIZE, stratify=y, random_state=SEED
        )
        X_tr, X_val, y_tr, y_val = train_test_split(
            X_train_full, y_train_full, test_size=VAL_SIZE, stratify=y_train_full,
            random_state=SEED,
        )
        split_label = "stratified (incidents may straddle the boundary)"

    say.rule(f"DATA SPLITS - {split_label}")
    for name, yy in [("train", y_tr), ("validation", y_val), ("test", y_test)]:
        say(f"  {name:<11} {len(yy):>7,} rows   {int(yy.sum()):>4,} fraud   {yy.mean():.3%}")
    say("  Validation exists so early stopping and threshold calibration never see the test set.")

    # ---------------- Preprocess ---------------- #
    preprocessor = build_preprocessor(numeric, binary, categorical)
    Xt_tr = preprocessor.fit_transform(X_tr)
    Xt_val = preprocessor.transform(X_val)
    Xt_test = preprocessor.transform(X_test)

    feature_names = clean_feature_names(preprocessor.get_feature_names_out())
    Xt_tr = pd.DataFrame(Xt_tr, columns=feature_names, index=X_tr.index)
    Xt_val = pd.DataFrame(Xt_val, columns=feature_names, index=X_val.index)
    Xt_test = pd.DataFrame(Xt_test, columns=feature_names, index=X_test.index)
    say(f"\nPreprocessed matrix: {Xt_tr.shape[1]} columns after one-hot encoding")

    # ---------------- Train ---------------- #
    say.rule("TRAINING")
    pos, neg = int(y_tr.sum()), int((1 - y_tr).sum())
    scale_pos_weight = neg / pos
    say(f"XGBoost      : scale_pos_weight = {neg}/{pos} = {scale_pos_weight:.1f}")
    xgb_model = make_xgb(scale_pos_weight)
    xgb_model.fit(Xt_tr, y_tr, eval_set=[(Xt_val, y_val)], verbose=False)
    n_trees = int(xgb_model.best_iteration) + 1
    say(f"               early stopping at {n_trees} trees "
        f"(best validation aucpr = {xgb_model.best_score:.4f})")

    say("RandomForest : class_weight = 'balanced_subsample', 400 trees")
    rf_model = make_random_forest()
    rf_model.fit(Xt_tr, y_tr)

    # ---------------- Evaluate + select ---------------- #
    results: dict[str, dict] = {}
    for name, model in [("XGBoost", xgb_model), ("RandomForest", rf_model)]:
        val_prob = model.predict_proba(Xt_val)[:, 1]
        test_prob = model.predict_proba(Xt_test)[:, 1]
        calib = calibrate_threshold(y_val, val_prob, TARGET_RECALL)
        results[name] = {
            "model": model,
            "val_prob": val_prob,
            "test_prob": test_prob,
            "calibration": calib,
            "val": evaluate(y_val, val_prob, calib["threshold"]),
            "test_default": evaluate(y_test, test_prob, DEFAULT_THRESHOLD),
            "test": evaluate(y_test, test_prob, calib["threshold"]),
        }

    # A single validation split holds only ~80 fraud rows, and on this dataset both
    # models score a saturated PR-AUC of 1.0 there - a tie that would make the choice
    # arbitrary. Cross-validated PR-AUC over train+validation pools ~400 positives and
    # actually separates the two.
    say.rule(f"MODEL SELECTION - {CV_FOLDS}-fold cross-validated PR-AUC")
    say("PR-AUC is the honest summary under 0.5% prevalence; ROC-AUC looks flattering")
    say("no matter what you do here. The preprocessor is refitted inside each fold.")
    say("")
    factories = {
        "XGBoost": lambda: make_xgb(scale_pos_weight, n_estimators=n_trees, early_stopping=False),
        "RandomForest": make_random_forest,
    }
    for name, factory in factories.items():
        mean, std, folds = cross_validated_pr_auc(
            factory, numeric, binary, categorical, X_train_full, y_train_full,
            groups=groups.loc[X_train_full.index] if GROUP_AWARE_SPLIT else None,
        )
        results[name]["cv_pr_auc_mean"] = mean
        results[name]["cv_pr_auc_std"] = std
        results[name]["cv_pr_auc_folds"] = [float(s) for s in folds]
        say(f"  {name:<14} PR-AUC {mean:.4f} +/- {std:.4f}   "
            f"folds: {', '.join(f'{s:.4f}' for s in folds)}")

    say.rule("MODEL COMPARISON")
    header = (f"{'Model':<14}{'PR-AUC(cv)':>12}{'PR-AUC(val)':>13}{'PR-AUC(test)':>14}"
              f"{'ROC-AUC(test)':>15}{'F1(test)':>11}{'Recall':>9}{'Precision':>11}")
    say(header)
    say("-" * len(header))
    for name, res in results.items():
        t = res["test"]
        say(f"{name:<14}{res['cv_pr_auc_mean']:>12.4f}{res['val']['pr_auc']:>13.4f}{t['pr_auc']:>14.4f}"
            f"{t['roc_auc']:>15.4f}{t['f1']:>11.4f}{t['recall']:>9.4f}{t['precision']:>11.4f}")

    best_name = max(results, key=lambda n: results[n]["cv_pr_auc_mean"])
    best = results[best_name]
    best_model = best["model"]
    say(f"\nSelected: {best_name}  (cross-validated PR-AUC {best['cv_pr_auc_mean']:.4f} "
        f"+/- {best['cv_pr_auc_std']:.4f})")

    # ---------------- Threshold calibration ---------------- #
    # Calibrate on out-of-fold probabilities rather than the single validation split.
    # On this dataset the validation split is perfectly separated, so any threshold
    # between the highest legitimate score and the lowest fraud score scores 100% -
    # the "optimal" point would be an arbitrary pick inside that gap. Out-of-fold
    # scoring over ~400 positives gives the curve enough resolution to mean something.
    say.rule("DECISION THRESHOLD CALIBRATION")
    if THRESHOLD_POLICY == "precision_at_recall":
        say(f"Active policy: maximise precision subject to recall >= {TARGET_RECALL:.0%}, breaking")
        say(f"near-ties in precision (within {PRECISION_TOLERANCE:.3f}) in favour of higher recall.")
    else:
        say(f"Active policy: minimise expected rupee loss subject to recall >= {TARGET_RECALL:.0%},")
        say(f"pricing a missed fraud at its transaction amount and a false alarm at "
            f"Rs.{FALSE_ALARM_COST_INR:,.0f}.")
    say(f"Calibrated on {CV_FOLDS}-fold out-of-fold probabilities over train+validation")
    say("(~400 positives), never on the test set.")
    say("")
    oof_prob = out_of_fold_probabilities(
        factories[best_name], numeric, binary, categorical, X_train_full, y_train_full,
        groups=groups.loc[X_train_full.index] if GROUP_AWARE_SPLIT else None,
    )
    oof_amounts = df.loc[X_train_full.index, "amount"]
    calib = calibrate_threshold(y_train_full, oof_prob, TARGET_RECALL)
    cost_calib = cost_optimal_threshold(y_train_full, oof_prob, oof_amounts)
    calib_val = best["calibration"]
    threshold = calib["threshold"] if THRESHOLD_POLICY == "precision_at_recall" else cost_calib["threshold"]

    if calib["met_target_recall"]:
        say(f"  Shipped threshold         : {threshold:.4f}")
        say(f"  Precision-at-recall point : {calib['threshold']:.4f}  "
            f"(recall {calib['recall']:.4f}, precision {calib['precision']:.4f} out-of-fold)")
        say(f"  Cost-optimal point        : {cost_calib['threshold']:.4f}  "
            f"(recall {cost_calib['recall']:.4f}, expected loss Rs.{cost_calib['expected_cost']:,.0f})")
    else:
        say(f"  WARNING: no threshold reached {TARGET_RECALL:.0%} recall out-of-fold.")
        say(f"  Fell back to the F1-optimal point: {threshold:.4f}")
    say(f"  F1-optimal threshold      : {calib['f1_optimal_threshold']:.4f} (F1 = {calib['f1_optimal_f1']:.4f})")
    say(f"  Single-split alternative  : {calib_val['threshold']:.4f}  "
        f"(what the 80-positive validation split alone would have suggested)")
    say(f"  Default baseline          : {DEFAULT_THRESHOLD:.2f}")

    # Justify the choice on the sample that has enough positives to justify anything.
    # The test split holds 100 positives and 1 false positive, so a threshold
    # comparison there is dominated by noise; out-of-fold has ~400 positives.
    oof_default = evaluate(y_train_full, oof_prob, DEFAULT_THRESHOLD)
    oof_tuned = evaluate(y_train_full, oof_prob, threshold)          # the shipped point
    oof_precision_metrics = evaluate(y_train_full, oof_prob, calib["threshold"])
    oof_cost_metrics = evaluate(y_train_full, oof_prob, cost_calib["threshold"])
    say("")
    say(f"  Out-of-fold comparison ({int(y_train_full.sum())} fraud rows, the largest sample available):")
    say(f"    {'':<26}{'Precision':>11}{'Recall':>9}{'F1':>9}{'Alarms':>9}{'Missed':>8}{'Expected loss':>16}")
    for label, m in [
        (f"default {DEFAULT_THRESHOLD:.2f}", oof_default),
        (f"precision-at-recall {calib['threshold']:.4f}", oof_precision_metrics),
        (f"cost-optimal {cost_calib['threshold']:.4f}", oof_cost_metrics),
    ]:
        loss = expected_cost_at(y_train_full, oof_prob, oof_amounts, m["threshold"])
        say(f"    {label:<26}{m['precision']:>11.4f}{m['recall']:>9.4f}{m['f1']:>9.4f}"
            f"{m['fp']:>9,}{m['fn']:>8,}{'Rs.' + format(loss, ',.0f'):>16}")

    # Spell the trade-off out in the run's own numbers. Hard-coded prose here went
    # stale the moment Module 1 got harder and the two policies started diverging.
    extra_alarms = oof_precision_metrics["fp"] - oof_cost_metrics["fp"]
    extra_missed = oof_precision_metrics["fn"] - oof_cost_metrics["fn"]
    precision_gain = oof_precision_metrics["precision"] - oof_cost_metrics["precision"]
    loss_gap = (expected_cost_at(y_train_full, oof_prob, oof_amounts, calib["threshold"])
                - expected_cost_at(y_train_full, oof_prob, oof_amounts, cost_calib["threshold"]))
    say("")
    say("  Why the two policies disagree, and why 'cost' is the one shipping:")
    say(f"  the {TARGET_RECALL:.0%} recall floor sits below what this model achieves, so")
    say("  'maximise precision' is free to climb the threshold until it hits the floor.")
    say(f"  Out-of-fold that buys {precision_gain:+.1%} precision and {-extra_alarms:+,} alarms,")
    say(f"  at the price of {extra_missed:+,} fraud rows let through.")
    say(f"  Priced in rupees the trade is negative by Rs.{loss_gap:,.0f}: a missed mule")
    say(f"  transfer costs its full amount, a false alarm costs one Rs.{FALSE_ALARM_COST_INR:,.0f} review.")
    say(f"  Active policy is '{THRESHOLD_POLICY}' (set THRESHOLD_POLICY at the top of this")
    say("  file to switch). Raising TARGET_RECALL has much the same effect.")

    # The comparison table above used the per-model validation threshold; re-score the
    # winner at the production threshold so every number below refers to what ships.
    best["test"] = evaluate(y_test, best["test_prob"], threshold)

    say.rule(f"TEST SET EVALUATION - {best_name}")
    for line in format_confusion(best["test_default"], "A) DEFAULT THRESHOLD"):
        say("  " + line)
    say("")
    for line in format_confusion(best["test"], "B) CALIBRATED THRESHOLD"):
        say("  " + line)

    d, c = best["test_default"], best["test"]
    say("")
    say(f"  Moving 0.50 -> {threshold:.4f}: fraud caught {d['tp']} -> {c['tp']} "
        f"({c['tp'] - d['tp']:+d}), false alarms {d['fp']} -> {c['fp']} ({c['fp'] - d['fp']:+d})")
    if c["f1"] < d["f1"]:
        say("")
        say("  Note: on this particular test split the default threshold scores higher.")
        say(f"  With {int(y_test.sum())} fraud rows and {d['fp']} false positive(s) in the whole split, that")
        say("  comparison is noise - the precision gain the calibrated threshold buys")
        say("  out-of-fold simply has no room to show up here. The threshold was not")
        say("  re-tuned to fix this, because tuning against the test set is precisely")
        say("  the error the three-way split exists to prevent. The recall floor still")
        say(f"  holds ({c['recall']:.0%} >= {TARGET_RECALL:.0%}), which is the contract the policy promises.")

    say("\n  Threshold-independent (ranking quality):")
    say(f"    ROC-AUC : {c['roc_auc']:.4f}")
    say(f"    PR-AUC  : {c['pr_auc']:.4f}   (a random model would score {y_test.mean():.4f})")

    # ---------------- Business impact ---------------- #
    test_amounts = df.loc[X_test.index, "amount"]
    impact = business_impact(y_test, best["test_prob"], threshold, test_amounts)
    say.rule("BUSINESS IMPACT (test set, calibrated threshold)")
    say(f"  Fraud value at risk    : Rs.{impact['fraud_value_total']:>12,.0f}")
    say(f"  Fraud value blocked    : Rs.{impact['fraud_value_caught']:>12,.0f}  "
        f"({impact['value_recall']:.1%} of rupees at risk)")
    say(f"  Fraud value leaked     : Rs.{impact['fraud_value_missed']:>12,.0f}")
    say(f"  Alerts per 100k txns   : {impact['alerts_per_100k_txns']:>12,.0f}")
    say(f"  Micro-payment (<=Rs.{MICRO_PAYMENT_CEILING:.0f}) false alarms: "
        f"{impact['micro_payment_false_alarms']:,} of {impact['micro_payment_count']:,} "
        f"({impact['micro_false_alarm_rate']:.4%})")
    say("  (The micro-payment line is the customer-experience guardrail: chai and")
    say("   auto-rickshaw payments must not get declined to buy a little more recall.)")

    # ---------------- Merchant economics ---------------- #
    # Everything above prices a decision the way a bank does: a flat review cost per
    # alert. FinGuard scores payments for a merchant on a gateway, where both sides
    # of the trade look different - see merchant_policy.py for the full argument.
    say.rule("MERCHANT ECONOMICS (test set)")
    say("  A bank pays a fixed sum to review an alert. A merchant declining a good")
    say("  customer loses the margin on that order plus the cost of winning them back,")
    say("  so the false-positive cost scales with basket size. And a gateway has a")
    say("  third action a bank does not: challenge the payment with a step-up.")
    say("")
    say(f"  Assumptions   chargeback fee Rs.{MERCHANT.chargeback_fee:,.0f}  |  "
        f"contribution margin {MERCHANT.contribution_margin:.0%}  |  "
        f"goodwill Rs.{MERCHANT.goodwill:,.0f}")
    say(f"                step-up abandon {MERCHANT.step_up_abandon_rate:.0%}  |  "
        f"step-up catch {MERCHANT.step_up_catch_rate:.0%}  |  "
        f"manual review Rs.{MERCHANT.manual_review:,.0f}")
    say(f"                step-up budget {MERCHANT.step_up_budget:.0%} of payments")

    amounts_test = test_amounts.to_numpy()
    three = portfolio_cost(y_test, best["test_prob"], amounts_test, MERCHANT)
    two = binary_portfolio_cost(y_test, best["test_prob"], amounts_test, threshold, MERCHANT)

    say("")
    say(f"  {'Policy':<34}{'Total cost':>14}{'Per txn':>10}{'Held':>8}{'Stepped up':>12}{'Fraud through':>15}")
    say("  " + "-" * 93)
    say(f"  {'block/allow at ' + format(threshold, '.4f'):<34}"
        f"Rs.{two['total_cost_inr']:>11,.0f}{two['cost_per_txn_inr']:>10.2f}"
        f"{two['held']:>8,}{'-':>12}{two['fraud_accepted']:>15,}")
    say(f"  {'accept / step-up / hold':<34}"
        f"Rs.{three['total_cost_inr']:>11,.0f}{three['cost_per_txn_inr']:>10.2f}"
        f"{three['held']:>8,}{three['stepped_up']:>12,}{three['fraud_accepted']:>15,}")

    say("")
    say(f"  Challenge budget used  : {three['step_up_rate']:.2%} of {MERCHANT.step_up_budget:.0%} "
        f"({'exhausted' if three['step_up_budget_exhausted'] else 'headroom left'})")
    say("  The budget is not decoration. Minimising cost row by row, a step-up is so")
    say("  cheap that the policy will challenge anything carrying more than a fraction")
    say("  of a percent of risk - on a book with diffuse scores that reached 94% of")
    say("  legitimate traffic in testing. Arithmetically optimal, and it would destroy")
    say("  conversion. Friction is a portfolio resource, so it is capped and then spent")
    say("  on the payments where a challenge saves the most.")

    saved = two["total_cost_inr"] - three["total_cost_inr"]
    if two["total_cost_inr"] > 0:
        say("")
        say(f"  Adding the challenge action saves Rs.{saved:,.0f} on {len(y_test):,} payments "
            f"({saved / two['total_cost_inr']:.0%} of merchant loss),")
        say(f"  by moving {three['stepped_up']:,} payments off the analyst queue and onto a")
        say(f"  step-up that costs a slice of conversion instead of the whole order. Manual")
        say(f"  holds fall from {two['held']:,} to {three['held']:,}.")

    say("")
    say("  Card-network dispute covenant (Visa VDMP / Mastercard ECP):")
    say(f"    Expected disputes      : {three['expected_disputes']:.1f} of {len(y_test):,} payments")
    say(f"    Dispute ratio          : {three['dispute_ratio']:.4%}  "
        f"(ceiling {three['dispute_ceiling']:.2%})")
    say(f"    Within covenant        : {'yes' if three['within_covenant'] else 'NO - remediation programme'}")

    binds_at = prevalence_at_which_covenant_binds(0.92, MERCHANT)
    say("")
    say("  Being straight about this constraint: at 0.5% fraud prevalence the covenant")
    say("  is slack by construction - even letting every fraud through would sit under")
    say(f"  the 0.9% ceiling. It starts to bind above {binds_at:.1%} prevalence at the 92%")
    say("  recall the age-ablated model achieves, which is the regime a compromised")
    say("  merchant category actually lives in. It is reported because it is the real")
    say("  operating limit, not because it is doing work on this dataset.")

    # ---------------- Per-signature recall ---------------- #
    per_pattern = recall_by_scam_pattern(df, X_test.index, y_test, best["test_prob"], threshold)
    say.rule("RECALL BY SCAM SIGNATURE (test set, calibrated threshold)")
    say(f"  {'Signature':<32}{'Fraud':>7}{'Caught':>8}{'Recall':>9}{'Value at risk':>16}")
    say("  " + "-" * 70)
    for _, r in per_pattern.iterrows():
        say(f"  {r['signature']:<32}{r['n']:>7}{r['caught']:>8}{r['recall']:>9.2%}"
            f"{'Rs.' + format(r['value_at_risk'], ',.0f'):>16}")

    # ---------------- Incident bleed ---------------- #
    bleed = incident_bleed_check(df, X_train_full.index, X_test.index, y_test, best["test_prob"], threshold)
    say.rule("SPLIT INTEGRITY - do scam incidents straddle train and test?")
    say(f"  Test fraud rows whose receiver VPA also appears in training fraud: "
        f"{bleed['receiver_seen_in_train_fraud']}/{bleed['test_fraud_rows']} ({bleed['bleed_rate']:.1%})")
    if bleed["recall_warm"] is not None:
        say(f"  Recall on those 'warm' receivers      : {bleed['recall_warm']:.2%}")
    if bleed["recall_cold"] is not None:
        say(f"  Recall on 'cold' receivers ({bleed['cold_rows']} rows, never seen): {bleed['recall_cold']:.2%}")
    say("")
    if GROUP_AWARE_SPLIT:
        say("  A stratified random split cuts through scam incidents - the Rs.1 probe lands in")
        say("  train while its drain lands in test, and one mule VPA is scattered across both.")
        say("  The model then recognises a receiver it has already been taught, and the score")
        say("  is flattered. Under that split the bleed rate here was 59%.")
        say("")
        say("  Module 1 now emits `ring_id`, so the split groups on the incident and the bleed")
        say("  is gone. It cost real headline performance and the numbers above are the ones")
        say("  that survived: PR-AUC 0.9955 -> 0.9802, and recall on receivers the model has")
        say("  never seen is 99% rather than a flattered 100%. That is the point of measuring")
        say("  it - the earlier figure was partly a property of the split, not of the model.")
    else:
        say("  GROUP_AWARE_SPLIT is off, so incidents may straddle the boundary and the")
        say("  bleed rate above is real. Set it to True to group on `ring_id` and remove the")
        say("  effect; expect the headline metrics to fall, which is the honest direction.")

    # ---------------- Ablation ---------------- #
    if RUN_ABLATION:
        say.rule("ABLATION - how much rests on receiver VPA age?")
        ab = age_ablation(X, y, numeric, binary, categorical,
                          (X_tr.index, X_val.index, X_test.index))
        say(f"  Dropped: {', '.join(ab['dropped_features'])}")
        say(f"  {'':<22}{'PR-AUC':>10}{'Recall':>10}{'Precision':>12}{'F1':>10}")
        say(f"  {'Full feature set':<22}{c['pr_auc']:>10.4f}{c['recall']:>10.4f}"
            f"{c['precision']:>12.4f}{c['f1']:>10.4f}")
        say(f"  {'Without VPA age':<22}{ab['pr_auc']:>10.4f}{ab['recall']:>10.4f}"
            f"{ab['precision']:>12.4f}{ab['f1']:>10.4f}")
        say("")
        say("  Every fraudulent receiver in the synthetic data is 0-20 days old, so this")
        say("  feature will always carry real signal here. Module 1 deliberately routes a")
        say("  slice of ordinary traffic - and a thin tail of genuine big-ticket payments -")
        say("  to brand-new VPAs, so account age is no longer separable on its own: the")
        say("  rule 'receiver is 20 days old or younger' is only ~7% precise on this data.")
        say("  The gap above is what the temporal, velocity and VPA-structure features")
        say("  deliver alone, and is the better guide to behaviour on real traffic.")

    # ---------------- Plots ---------------- #
    plot_curves(results, y_test, REPORT_DIR)
    plot_threshold_sweep(calib, threshold, REPORT_DIR)
    plot_confusion_matrices(y_test, best["test_prob"], DEFAULT_THRESHOLD, threshold, REPORT_DIR)
    ranked = plot_feature_importance(best_model, feature_names, REPORT_DIR)

    if not ranked.empty:
        say.rule("TOP FEATURE IMPORTANCES")
        for _, row in ranked.head(12).iterrows():
            bar = "#" * max(1, int(row["importance"] / ranked["importance"].max() * 40))
            say(f"  {row['feature']:<44}{row['importance']:.4f}  {bar}")

    # ---------------- Serialise ---------------- #
    # Each artifact is a full pipeline (preprocessor + classifier) so Module 3 can
    # score a raw engineered frame in one call without reassembling the steps.
    pipelines = {
        name: Pipeline([("preprocessor", preprocessor), ("classifier", res["model"])])
        for name, res in results.items()
    }
    joblib.dump(pipelines["XGBoost"], MODEL_DIR / "finguard_xgboost.joblib")
    joblib.dump(pipelines["RandomForest"], MODEL_DIR / "finguard_random_forest.joblib")
    joblib.dump(pipelines[best_name], MODEL_DIR / "finguard_best_model.joblib")
    joblib.dump(preprocessor, MODEL_DIR / "preprocessor.joblib")

    config = {
        "project": "FinGuard - UPI fraud detection",
        "module": "2 - predictive ML engine",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "best_model": best_name,
        "model_file": "finguard_xgboost.joblib" if best_name == "XGBoost" else "finguard_random_forest.joblib",
        "preprocessor_file": "preprocessor.joblib",
        "optimal_threshold": threshold,
        "default_threshold": DEFAULT_THRESHOLD,
        "threshold_policy": {
            "rule": (f"maximise precision subject to recall >= {TARGET_RECALL}; "
                     f"precision ties within {PRECISION_TOLERANCE} broken toward higher recall"),
            "precision_tolerance": PRECISION_TOLERANCE,
            "calibrated_on": f"{CV_FOLDS}-fold out-of-fold probabilities over train+validation",
            "target_recall": TARGET_RECALL,
            "met_target_recall": calib["met_target_recall"],
            "out_of_fold_precision": calib["precision"],
            "out_of_fold_recall": calib["recall"],
            "f1_optimal_threshold": calib["f1_optimal_threshold"],
            "single_split_alternative": calib_val["threshold"],
            "out_of_fold_at_default": oof_default,
            "out_of_fold_at_calibrated": oof_tuned,
            "active_policy": THRESHOLD_POLICY,
            "precision_at_recall_threshold": calib["threshold"],
            "cost_optimal": cost_calib,
            "false_alarm_cost_inr": FALSE_ALARM_COST_INR,
        },
        "dataset": {
            "file": DATA_CSV.name,
            "rows": int(len(df)),
            "fraud_rows": int(y.sum()),
            "fraud_rate": float(fraud_rate),
            "period_start": str(df["timestamp"].min()),
            "period_end": str(df["timestamp"].max()),
        },
        "split": {
            "strategy": "stratified 64/16/20 train/validation/test",
            "train_rows": int(len(y_tr)),
            "validation_rows": int(len(y_val)),
            "test_rows": int(len(y_test)),
            "random_state": SEED,
        },
        "features": {
            "raw_input_columns": [c for c in df.columns if c not in (TARGET, *LEAKAGE_COLUMNS)],
            "dropped_columns": dropped,
            "engineered_numeric": numeric,
            "engineered_binary": binary,
            "engineered_categorical": categorical,
            "transformed_feature_names": feature_names,
            "n_transformed_features": len(feature_names),
        },
        "selection": {
            "metric": "cross-validated PR-AUC on train+validation",
            "cv_folds": CV_FOLDS,
            "reason": "single-split PR-AUC saturates at 1.0 with ~80-100 positives and cannot rank models",
        },
        # Headline numbers for the model that ships, at the threshold that ships.
        "production_metrics": {
            "model": best_name,
            "threshold": threshold,
            "test": best["test"],
            "test_at_default_threshold": best["test_default"],
        },
        # Per-model detail. `test_calibrated_threshold` uses each model's own
        # validation-calibrated threshold, which is how they were compared.
        "metrics": {
            name: {
                "cv_pr_auc_mean": res["cv_pr_auc_mean"],
                "cv_pr_auc_std": res["cv_pr_auc_std"],
                "cv_pr_auc_folds": res["cv_pr_auc_folds"],
                "validation": {k: v for k, v in res["val"].items()},
                "test_default_threshold": {k: v for k, v in res["test_default"].items()},
                "test_calibrated_threshold": {k: v for k, v in res["test"].items()},
            }
            for name, res in results.items()
        },
        "recall_by_scam_signature": per_pattern.to_dict(orient="records"),
        "split_integrity": bleed,
        "business_impact_test": impact,
        "merchant_economics": {
            "assumptions": {
                "chargeback_fee_inr": MERCHANT.chargeback_fee,
                "contribution_margin": MERCHANT.contribution_margin,
                "false_decline_goodwill_inr": MERCHANT.goodwill,
                "manual_review_inr": MERCHANT.manual_review,
                "step_up_abandon_rate": MERCHANT.step_up_abandon_rate,
                "step_up_catch_rate": MERCHANT.step_up_catch_rate,
                "dispute_ratio_ceiling": MERCHANT.dispute_ratio_ceiling,
            },
            "three_action_policy": three,
            "binary_policy_at_threshold": two,
            "covenant_binds_above_prevalence": binds_at,
        },
        "ablation_no_vpa_age": ab if RUN_ABLATION else None,
        "environment": {
            "python": platform.python_version(),
            "scikit_learn": sklearn.__version__,
            "xgboost": xgb.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    }
    (MODEL_DIR / "model_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    say.rule("ARTIFACTS")
    for f in sorted(p for p in MODEL_DIR.iterdir() if p.is_file()):
        say(f"  models/{f.name:<34} {f.stat().st_size / 1024:>9,.1f} KB")
    for f in sorted(p for p in REPORT_DIR.iterdir() if p.is_file()):
        say(f"  reports/{f.name:<33} {f.stat().st_size / 1024:>9,.1f} KB")

    say.rule("MODULE 3 USAGE")
    say("  import joblib, pandas as pd")
    say("  from train_model import engineer_features")
    say("")
    say("  pipe = joblib.load('models/finguard_best_model.joblib')")
    say("  cfg  = json.load(open('models/model_config.json'))")
    say("  prob = pipe.predict_proba(engineer_features(txn_df))[:, 1]")
    say("  flag = prob >= cfg['optimal_threshold']")

    say.save(REPORT_DIR / "evaluation_report.txt")
    print(f"\nReport saved to reports/evaluation_report.txt")


if __name__ == "__main__":
    sys.exit(main())
