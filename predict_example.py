"""Serving contract check for the Module 2 artifacts.

Loads the saved pipeline and config, scores raw transactions through the exact path
Module 3 will use, and verifies the reloaded model reproduces training-time scores.

Usage:
    python predict_example.py
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from train_model import engineer_features

BASE_DIR = Path(__file__).resolve().parent
MODEL_DIR = BASE_DIR / "models"


def load_service():
    """Everything the scoring service needs: a fitted pipeline and its threshold."""
    pipeline = joblib.load(MODEL_DIR / "finguard_best_model.joblib")
    config = json.loads((MODEL_DIR / "model_config.json").read_text(encoding="utf-8"))
    return pipeline, config


def score(pipeline, config, transactions: pd.DataFrame) -> pd.DataFrame:
    """Raw UPI rows in, fraud probability and decision out."""
    features = engineer_features(transactions)
    probability = pipeline.predict_proba(features)[:, 1]
    threshold = config["optimal_threshold"]

    return pd.DataFrame(
        {
            "transaction_id": transactions["transaction_id"].to_numpy(),
            "amount": transactions["amount"].to_numpy(),
            "fraud_probability": probability.round(4),
            "decision": ["BLOCK" if p >= threshold else "ALLOW" for p in probability],
        }
    )


def main() -> None:
    pipeline, config = load_service()
    print(f"Model     : {config['best_model']}")
    print(f"Threshold : {config['optimal_threshold']:.4f} ({config['threshold_policy']['active_policy']})")
    print(f"Trained   : {config['created_at']}\n")

    df = pd.read_csv(BASE_DIR / "upi_synthetic_data.csv", parse_dates=["timestamp"])
    df = df.sort_values("timestamp", kind="mergesort").reset_index(drop=True)

    # A handful of each class so the output shows both decisions.
    sample = pd.concat([df[df["is_fraud"] == 1].head(5), df[df["is_fraud"] == 0].head(5)])
    result = score(pipeline, config, sample)
    result["actual"] = sample["is_fraud"].to_numpy()
    result["pattern"] = sample["fraud_pattern"].to_numpy()
    print(result.to_string(index=False))

    # Regression check: the reloaded artifact must agree with the metrics that were
    # recorded at training time, or the saved pipeline is not what was evaluated.
    full = score(pipeline, config, df)
    flagged = (full["decision"] == "BLOCK").to_numpy()
    actual = df["is_fraud"].to_numpy() == 1
    recall = (flagged & actual).sum() / actual.sum()
    print(f"\nWhole-dataset recall at the shipped threshold: {recall:.4f} "
          f"({(flagged & actual).sum()}/{actual.sum()} fraud caught, "
          f"{(flagged & ~actual).sum()} false alarms)")
    print("Note: this covers train+test, so it is a smoke test of the artifact, not an")
    print("unbiased score - see reports/evaluation_report.txt for held-out numbers.")


if __name__ == "__main__":
    main()
