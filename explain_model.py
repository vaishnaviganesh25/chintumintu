"""FinGuard Module 3 - explainable AI layer.

Turns the Module 2 classifier from a score into a defensible decision. Produces
three things a fraud operation actually needs:

1. Global explanations - which features drive the model overall, and do they agree
   with how the Indian scam patterns are supposed to work.
2. Local explanations - for one flagged transaction, exactly which attributes pushed
   it over the line and by how much.
3. Plain-English reason codes - the same local explanation rendered as text an
   analyst or a customer-facing notification can use. A SHAP waterfall is not
   something you put in front of a customer whose payment was held.

Why SHAP: it is additive and locally accurate, so the per-feature contributions for
a single transaction sum exactly to the model's score. That property is what makes
the output usable as an audit trail under RBI-style explainability expectations -
you can show precisely why this payment was held.

One thing this module does that a textbook SHAP script does not: it aggregates
contributions by *concept* before showing them to anyone. The feature matrix
contains `amount` and `log_amount`, and `receiver_vpa_age_days` and
`log_receiver_vpa_age` - correlated encodings of one underlying fact. Raw SHAP
splits credit between them, which both understates the concept's true importance
and produces nonsense like "flagged because of the amount, and the amount".
Summing within a concept is valid precisely because SHAP is additive.

Usage:
    python explain_model.py
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import shap

from train_model import Reporter, engineer_features

BASE_DIR = Path(__file__).resolve().parent
DATA_CSV = BASE_DIR / "upi_synthetic_data.csv"
MODEL_DIR = BASE_DIR / "models"
REPORT_DIR = BASE_DIR / "reports"
EXPLAIN_DIR = REPORT_DIR / "explanations"

SEED = 42

# SHAP on a 400-tree forest is expensive per row, so global plots use a stratified
# sample rather than all 100k transactions. Fraud is oversampled because 0.5%
# prevalence would otherwise leave almost no positives to characterise.
GLOBAL_SAMPLE_LEGIT = 3_000
GLOBAL_SAMPLE_FRAUD = 400

sns.set_theme(style="whitegrid", context="talk")
say = Reporter()


# --------------------------------------------------------------------------- #
# Concept mapping: transformed column -> the real-world fact it encodes
# --------------------------------------------------------------------------- #
# Several engineered columns describe the same underlying fact. Mapping them to a
# shared concept lets us sum their SHAP contributions and speak about the fact once.
FEATURE_CONCEPTS: dict[str, str] = {
    "receiver_vpa_age_days": "age of the receiving UPI ID",
    "log_receiver_vpa_age": "age of the receiving UPI ID",
    "is_new_receiver_vpa": "age of the receiving UPI ID",
    "is_recent_receiver_vpa": "age of the receiving UPI ID",
    "amount": "transaction amount",
    "log_amount": "transaction amount",
    "is_micro_payment": "transaction amount",
    "is_round_amount": "round-figure amount",
    "hour_of_day": "time of day",
    "hour_sin": "time of day",
    "hour_cos": "time of day",
    "is_night_txn": "sent between 1 AM and 4 AM",
    "is_weekend": "weekend transaction",
    "day_of_week": "day of week",
    "time_since_last_txn_sec": "gap since the sender's previous payment",
    "log_time_since_last": "gap since the sender's previous payment",
    "is_rapid_txn": "gap since the sender's previous payment",
    "is_first_txn": "sender's first recorded payment",
    "prev_amount": "size of the sender's previous payment",
    "log_prev_amount": "size of the sender's previous payment",
    "prev_amount_ratio": "jump in size versus the previous payment",
    "same_receiver_as_prev": "repeat payment to the same receiver",
    "receiver_is_merchant_like": "receiver looks like a registered merchant",
    "receiver_vpa_is_mobile": "receiver UPI ID is a mobile number",
    "sender_vpa_is_mobile": "sender UPI ID is a mobile number",
    "receiver_starts_with_digit": "receiver UPI ID starts with a digit",
    "receiver_has_suspicious_keyword": "receiver UPI ID contains a scam keyword",
    "receiver_digit_ratio": "shape of the receiver UPI ID",
    "receiver_local_len": "shape of the receiver UPI ID",
    "sender_local_len": "shape of the sender UPI ID",
    "sender_bank_handle": "sender's bank handle",
    "receiver_bank_handle": "receiver's bank handle",
    "sender_city": "sender's city",
}

# Longest first so `prev_amount_ratio` never gets matched by `prev_amount`.
_CONCEPT_KEYS = sorted(FEATURE_CONCEPTS, key=len, reverse=True)


def base_feature(name: str) -> str:
    """`num__log_amount` -> `log_amount`; `cat__sender_city_Mumbai` -> `sender_city`."""
    stripped = name.split("__", 1)[-1]
    if stripped in FEATURE_CONCEPTS:
        return stripped
    for key in _CONCEPT_KEYS:                       # one-hot columns carry a value suffix
        if stripped.startswith(f"{key}_"):
            return key
    return stripped


def concept_of(name: str) -> str:
    """Plain-English concept for a transformed column."""
    return FEATURE_CONCEPTS.get(base_feature(name), base_feature(name).replace("_", " "))


def to_concepts(values: np.ndarray, names: list[str]) -> pd.DataFrame:
    """Sum SHAP contributions across every column describing the same concept.

    Valid because SHAP contributions are additive: the sum over a group of features
    is that group's joint contribution to the score.
    """
    frame = pd.DataFrame(values, columns=[concept_of(n) for n in names])
    return frame.T.groupby(level=0).sum().T


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_model_and_config():
    """Just the pipeline and its config - no dataset.

    Split out from `load_artifacts` for the Module 4 API, which scores one incoming
    transaction and has no business reading 100,000 training rows into memory to do it.
    """
    model_path = MODEL_DIR / "finguard_best_model.joblib"
    config_path = MODEL_DIR / "model_config.json"
    for path in (model_path, config_path):
        if not path.exists():
            raise FileNotFoundError(
                f"{path.name} not found in {MODEL_DIR}. Run `python train_model.py` first (Module 2)."
            )
    pipeline = joblib.load(model_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return pipeline, config


def load_artifacts():
    """Model pipeline, config, and the raw dataset Module 1 produced."""
    pipeline, config = load_model_and_config()
    df = pd.read_csv(DATA_CSV, parse_dates=["timestamp"])
    df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    return pipeline, config, df


def build_explainer(pipeline, background: pd.DataFrame):
    """TreeExplainer over the classifier, with the preprocessor applied up front.

    SHAP explains the estimator, not the pipeline, so features are transformed first.
    `tree_path_dependent` avoids needing a background distribution and is far cheaper
    on a 400-tree forest.
    """
    preprocessor = pipeline.named_steps["preprocessor"]
    classifier = pipeline.named_steps["classifier"]
    names = [c.replace("[", "_").replace("]", "_").replace("<", "_")
             for c in preprocessor.get_feature_names_out()]
    transformed = pd.DataFrame(preprocessor.transform(background), columns=names,
                               index=background.index)
    explainer = shap.TreeExplainer(classifier, feature_perturbation="tree_path_dependent")
    return explainer, transformed, names


def fraud_class_values(shap_values) -> np.ndarray:
    """Reduce SHAP output to the fraud-class contribution matrix.

    Tree models for binary classification return either (n, features) or
    (n, features, 2) depending on estimator and SHAP version; fraud is the last index.
    """
    values = np.asarray(shap_values)
    return values[:, :, -1] if values.ndim == 3 else values


def fraud_base_value(explainer) -> float:
    """The model's average output - the starting point every explanation builds from."""
    expected = explainer.expected_value
    if isinstance(expected, (list, tuple, np.ndarray)):
        return float(np.asarray(expected).ravel()[-1])
    return float(expected)


# --------------------------------------------------------------------------- #
# Global explanations
# --------------------------------------------------------------------------- #
def global_explanations(explainer, transformed: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """Beeswarm and bar plots at feature level, plus a ranked concept-level table."""
    values = fraud_class_values(explainer.shap_values(transformed, check_additivity=False))

    # The plots stay at feature level: a beeswarm needs one feature value per dot,
    # which a summed concept does not have.
    plt.figure()
    shap.summary_plot(values, transformed, feature_names=[concept_of(n) for n in names],
                      max_display=16, show=False)
    plt.title("What drives fraud predictions", fontsize=14)
    plt.tight_layout()
    plt.savefig(EXPLAIN_DIR / "shap_beeswarm.png", dpi=130, bbox_inches="tight")
    plt.close()

    concepts = to_concepts(values, names)
    ranked = pd.DataFrame({
        "concept": concepts.columns,
        "mean_abs_shap": concepts.abs().mean(axis=0).to_numpy(),
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    # Direction: correlate each concept's dominant column with its own contribution.
    # "Does a higher value push this transaction towards fraud?" - the same question
    # the colour axis of a beeswarm answers.
    per_feature_abs = pd.Series(np.abs(values).mean(axis=0), index=names)
    directions = []
    for concept in ranked["concept"]:
        members = [n for n in names if concept_of(n) == concept]
        dominant = per_feature_abs[members].idxmax()
        col = transformed[dominant].to_numpy()
        shap_col = values[:, names.index(dominant)]
        if col.std() == 0 or shap_col.std() == 0:
            directions.append("no effect")
        else:
            r = float(np.corrcoef(col, shap_col)[0, 1])
            directions.append("higher -> riskier" if r > 0 else "higher -> safer")
    ranked["direction"] = directions

    plt.figure(figsize=(11, 8))
    top = ranked.head(14).iloc[::-1]
    sns.barplot(data=top, y="concept", x="mean_abs_shap", hue="concept",
                palette="rocket_r", legend=False)
    plt.xlabel("Mean |SHAP| (summed within concept)")
    plt.ylabel("")
    plt.title("Fraud drivers, aggregated by concept", fontsize=14)
    plt.tight_layout()
    plt.savefig(EXPLAIN_DIR / "shap_importance_bar.png", dpi=130, bbox_inches="tight")
    plt.close()

    return ranked


def per_pattern_explanations(explainer, transformed, names, meta: pd.DataFrame) -> pd.DataFrame:
    """Average concept contribution per scam signature.

    This is the check that matters most for the project: does the model catch each
    Indian scam pattern *for the intended reason*? A model that flags odd-hour
    phishing on amount alone, never the hour, has learned something shallower than it
    appears and will break on the first scam that changes its amount profile.
    """
    values = fraud_class_values(explainer.shap_values(transformed, check_additivity=False))
    concepts = to_concepts(values, names).set_index(transformed.index)

    rows = []
    for signature, idx in meta.groupby("signature").groups.items():
        mean_contribution = concepts.loc[idx].mean(axis=0).sort_values(ascending=False)
        rows.append({
            "signature": signature,
            "n": len(idx),
            "top_drivers": [(c, float(v)) for c, v in mean_contribution.head(4).items()],
        })
    return pd.DataFrame(rows).sort_values("signature").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Local explanations and reason codes
# --------------------------------------------------------------------------- #
def describe(concept: str, raw: pd.Series, feat: pd.Series) -> str:
    """Render this transaction's actual value for a concept, in human terms."""
    if concept == "transaction amount":
        return f"Rs.{raw['amount']:,.0f}"
    if concept == "age of the receiving UPI ID":
        age = int(raw["receiver_vpa_age_days"])
        return "created today" if age == 0 else f"{age} day{'s' if age != 1 else ''} old"
    if concept in ("time of day", "sent between 1 AM and 4 AM"):
        return raw["timestamp"].strftime("%H:%M")
    if concept == "gap since the sender's previous payment":
        gap = raw["time_since_last_txn_sec"]
        if gap < 0:
            return "first payment on record"
        if gap < 120:
            return f"{int(gap)} seconds after the previous one"
        return f"{gap / 3600:.1f} hours after the previous one"
    if concept == "size of the sender's previous payment":
        return f"Rs.{feat['prev_amount']:,.0f}"
    if concept == "jump in size versus the previous payment":
        return f"{feat['prev_amount_ratio']:,.0f}x the previous payment"
    if concept == "repeat payment to the same receiver":
        return "yes" if feat["same_receiver_as_prev"] else "no"
    if concept == "receiver looks like a registered merchant":
        return "no" if not feat["receiver_is_merchant_like"] else "yes"
    if concept == "receiver's bank handle":
        return str(raw["receiver_vpa"]).split("@")[-1]
    if concept == "sender's bank handle":
        return str(raw["sender_vpa"]).split("@")[-1]
    if concept == "sender's city":
        return str(raw["sender_city"])
    if concept == "round-figure amount":
        return "yes" if feat["is_round_amount"] else "no"
    return ""


def reason_codes(concepts: pd.Series, raw: pd.Series, feat: pd.Series, top_n: int = 3) -> list[str]:
    """Narrate the largest risk-increasing concepts as analyst-readable sentences.

    Only positive contributions are narrated. A customer told their payment was held
    "because the amount was small" would rightly be baffled - mitigating factors are
    reported separately.
    """
    risky = concepts[concepts > 0].sort_values(ascending=False).head(top_n)
    lines = []
    for concept, _ in risky.items():
        detail = describe(concept, raw, feat)
        lines.append(f"{concept}{f' ({detail})' if detail else ''}")
    return lines


def customer_notification(amount: float, reasons: list[str], blocked: bool = True) -> str:
    """Render reason codes as a message you could send to the account holder.

    Kept here rather than in the caller so the batch report and the Module 4 API
    speak with one voice - the whole point of generating the audit trail and the
    customer message from a single explanation is that they cannot drift apart.
    """
    if not blocked:
        return (f"This payment of Rs.{amount:,.0f} looks consistent with normal activity "
                "on your account and was approved.")
    if not reasons:
        return (f"We have paused a payment of Rs.{amount:,.0f} from your account for your "
                "safety. Please confirm it in the app.")
    joined = reasons[0] if len(reasons) == 1 else " and ".join(reasons[:2])
    return (
        f"We have paused a payment of Rs.{amount:,.0f} from your account for your safety. "
        f"It looked unusual because of the {joined}. If you recognise this payment, approve "
        "it in the app. If you do not, report it and we will block the receiver."
    )


def explain_transaction(explainer, pipeline, names, features: pd.DataFrame,
                        raw: pd.Series, threshold: float) -> dict:
    """Full local explanation for a single transaction."""
    preprocessor = pipeline.named_steps["preprocessor"]
    row = features.loc[[raw.name]]
    transformed = pd.DataFrame(preprocessor.transform(row), columns=names, index=row.index)

    values = fraud_class_values(explainer.shap_values(transformed, check_additivity=False))[0]
    concepts = to_concepts(values.reshape(1, -1), names).iloc[0]
    probability = float(pipeline.predict_proba(row)[:, 1][0])
    feat = features.loc[raw.name]

    return {
        "probability": probability,
        "decision": "BLOCK" if probability >= threshold else "ALLOW",
        "concepts": concepts.sort_values(key=lambda s: -s.abs()),
        "shap_values": values,
        "reasons": reason_codes(concepts, raw, feat),
        "mitigating": [
            f"{c} ({describe(c, raw, feat)})".replace(" ()", "")
            for c in concepts[concepts < 0].sort_values().head(2).index
        ],
    }


def plot_waterfall(explainer, result: dict, names: list[str], features: pd.DataFrame,
                   idx, title: str, path: Path) -> None:
    """Per-transaction waterfall from the base rate to the final score.

    Aggregated to concepts so one fact produces one bar. `data` is the engineered
    (pre-scaling) value where a concept maps to a single readable number, so the
    chart reads "transaction amount = 79000" rather than a RobustScaler output.
    """
    concepts = result["concepts"]
    feat = features.loc[idx]
    display = []
    for concept in concepts.index:
        members = [b for b, c in FEATURE_CONCEPTS.items() if c == concept and b in feat.index]
        if not members:
            display.append("")
            continue
        value = feat[members[0]]
        numeric = pd.to_numeric(value, errors="coerce")
        # Categorical concepts (bank handle, city) have no numeric value to show.
        # SHAP's value formatter passes strings through untouched, so the chart can
        # read "ybl = receiver's bank handle" instead of "nan = ...".
        display.append(float(numeric) if pd.notna(numeric) else str(value))

    exp = shap.Explanation(
        values=concepts.to_numpy(),
        base_values=fraud_base_value(explainer),
        data=np.array(display, dtype=object),
        feature_names=list(concepts.index),
    )
    plt.figure()
    shap.plots.waterfall(exp, max_display=10, show=False)
    plt.title(title, fontsize=13)
    plt.tight_layout()
    plt.savefig(path, dpi=130, bbox_inches="tight")
    plt.close()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def main() -> None:
    EXPLAIN_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    say.rule("FINGUARD MODULE 3 - EXPLAINABLE AI")
    pipeline, config, df = load_artifacts()
    threshold = config["optimal_threshold"]
    say(f"Model     : {config['best_model']}  (trained {config['created_at']})")
    say(f"Threshold : {threshold:.4f}  [{config['threshold_policy']['active_policy']} policy]")

    features = engineer_features(df)

    fraud_idx = df.index[df["is_fraud"] == 1]
    legit_idx = df.index[df["is_fraud"] == 0]
    sample_idx = np.concatenate([
        rng.choice(fraud_idx, size=min(GLOBAL_SAMPLE_FRAUD, len(fraud_idx)), replace=False),
        rng.choice(legit_idx, size=GLOBAL_SAMPLE_LEGIT, replace=False),
    ])
    sample = features.loc[sample_idx]

    say(f"\nExplaining a stratified sample of {len(sample):,} transactions "
        f"({GLOBAL_SAMPLE_FRAUD} fraud, {GLOBAL_SAMPLE_LEGIT:,} legitimate).")
    say("Fraud is oversampled deliberately - at 0.5% prevalence a random sample would")
    say("contain too few positives to characterise what drives a fraud prediction.")
    say("Contributions are summed within a concept, so the two amount columns and the")
    say("four VPA-age columns each speak once instead of splitting credit.")

    explainer, transformed, names = build_explainer(pipeline, sample)
    ranked = global_explanations(explainer, transformed, names)

    say.rule("GLOBAL DRIVERS (mean |SHAP| per concept)")
    say(f"  {'Concept':<46}{'Mean |SHAP|':>13}   Direction")
    say("  " + "-" * 82)
    for _, r in ranked.head(14).iterrows():
        say(f"  {r['concept']:<46}{r['mean_abs_shap']:>13.4f}   {r['direction']}")

    # ---------------- Per scam signature ---------------- #
    meta = df.loc[sample_idx, ["fraud_pattern", "amount", "is_fraud"]].copy()
    meta["signature"] = np.where(meta["is_fraud"] == 1, meta["fraud_pattern"], "legitimate")
    probe = (meta["fraud_pattern"] == "rupee_1_test") & (meta["amount"] <= 5)
    meta.loc[probe, "signature"] = "rupee_1_test (probe leg)"
    meta.loc[(meta["fraud_pattern"] == "rupee_1_test") & ~probe, "signature"] = "rupee_1_test (large leg)"

    per_pattern = per_pattern_explanations(explainer, transformed, names, meta)
    say.rule("WHAT DRIVES EACH SCAM SIGNATURE")
    say("  Average concept contribution within each pattern. The question this answers:")
    say("  is the model catching each scam for the reason it is supposed to?")
    for _, r in per_pattern.iterrows():
        say(f"\n  {r['signature']}  (n={r['n']})")
        for concept, value in r["top_drivers"]:
            say(f"      {value:+.4f}  {concept}")

    # ---------------- Local: one worked example per signature ---------------- #
    say.rule("CASE FILES - individual flagged transactions")
    case_records = []
    for signature in ["rupee_1_test (probe leg)", "rupee_1_test (large leg)",
                      "new_vpa_velocity", "odd_hour_phishing"]:
        candidates = meta.index[meta["signature"] == signature]
        if len(candidates) == 0:
            continue
        idx = candidates[0]
        raw = df.loc[idx]
        result = explain_transaction(explainer, pipeline, names, features, raw, threshold)

        say(f"\n  {signature}")
        say(f"    {raw['sender_vpa']}  ->  {raw['receiver_vpa']}")
        say(f"    Rs.{raw['amount']:,.2f} at {raw['timestamp']:%d %b %Y, %H:%M}  "
            f"| receiver VPA {int(raw['receiver_vpa_age_days'])} days old")
        say(f"    Fraud probability {result['probability']:.4f}  ->  {result['decision']}")
        say("    Flagged because:")
        for reason in result["reasons"]:
            say(f"      + {reason}")
        if result["mitigating"]:
            say("    Argued against by:")
            for m in result["mitigating"]:
                say(f"      - {m}")

        slug = signature.replace(" ", "_").replace("(", "").replace(")", "")
        plot_waterfall(explainer, result, names, features, idx,
                       f"{signature} - p(fraud) = {result['probability']:.3f}",
                       EXPLAIN_DIR / f"waterfall_{slug}.png")
        case_records.append({
            "signature": signature,
            "transaction_id": raw["transaction_id"],
            "amount": float(raw["amount"]),
            "timestamp": str(raw["timestamp"]),
            "receiver_vpa_age_days": int(raw["receiver_vpa_age_days"]),
            "probability": result["probability"],
            "decision": result["decision"],
            "reasons": result["reasons"],
        })

    # ---------------- A false positive, explained ---------------- #
    # The alerts an analyst distrusts most are the wrong ones. Showing why the model
    # erred is what makes an override defensible instead of arbitrary.
    probabilities = pipeline.predict_proba(features)[:, 1]
    false_positives = df.index[(df["is_fraud"] == 0) & (probabilities >= threshold)]
    if len(false_positives):
        say.rule("FALSE POSITIVE REVIEW")
        say(f"  {len(false_positives)} legitimate transaction(s) flagged across all 100,000 rows.")
        idx = false_positives[0]
        raw = df.loc[idx]
        result = explain_transaction(explainer, pipeline, names, features, raw, threshold)
        say(f"\n    {raw['sender_vpa']}  ->  {raw['receiver_vpa']}")
        say(f"    Rs.{raw['amount']:,.2f} at {raw['timestamp']:%d %b %Y, %H:%M}  "
            f"| receiver VPA {int(raw['receiver_vpa_age_days'])} days old")
        say(f"    Fraud probability {result['probability']:.4f}  (actually legitimate)")
        say("    The model's stated reasoning:")
        for reason in result["reasons"]:
            say(f"      + {reason}")
        say("")
        say("    Reading this as an analyst: the pattern genuinely does resemble a mule")
        say("    payment, and a human reviewing it would reach for the same evidence.")
        say("    That is the point - a wrong alert you can interrogate is cleared in")
        say("    seconds, while an unexplained score has to be taken on faith.")
        plot_waterfall(explainer, result, names, features, idx,
                       f"False positive - p(fraud) = {result['probability']:.3f}",
                       EXPLAIN_DIR / "waterfall_false_positive.png")
        case_records.append({
            "signature": "false_positive",
            "transaction_id": raw["transaction_id"],
            "amount": float(raw["amount"]),
            "timestamp": str(raw["timestamp"]),
            "receiver_vpa_age_days": int(raw["receiver_vpa_age_days"]),
            "probability": result["probability"],
            "decision": result["decision"],
            "reasons": result["reasons"],
        })

    # ---------------- Customer-facing notification ---------------- #
    say.rule("CUSTOMER NOTIFICATION (generated from the same SHAP output)")
    case = next((c for c in case_records if c["signature"] == "odd_hour_phishing"), None)
    if case:
        body = customer_notification(case["amount"], case["reasons"],
                                     blocked=case["decision"] == "BLOCK")
        for line in textwrap.wrap(body, 74):
            say(f"  {line}")
        say("")
        say("  Same numbers as the waterfall chart, phrased for someone who has never")
        say("  heard of SHAP. The audit trail and the customer message stay in sync")
        say("  because both are generated from one explanation, not written separately.")

    # ---------------- Persist ---------------- #
    ranked.to_csv(EXPLAIN_DIR / "global_shap_ranking.csv", index=False)
    (EXPLAIN_DIR / "case_files.json").write_text(json.dumps(case_records, indent=2), encoding="utf-8")

    say.rule("ARTIFACTS")
    for f in sorted(EXPLAIN_DIR.iterdir()):
        say(f"  reports/explanations/{f.name:<42}{f.stat().st_size / 1024:>9,.1f} KB")

    say.save(REPORT_DIR / "explainability_report.txt")
    print("\nReport saved to reports/explainability_report.txt")


if __name__ == "__main__":
    main()
