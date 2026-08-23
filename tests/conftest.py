"""Shared fixtures.

The model artifacts are gitignored and cost about two minutes to regenerate, so
tests that need them are marked `slow` and skipped rather than failed when they are
absent. Everything about feature engineering, threshold maths and the ledger runs
without them, which keeps the fast suite genuinely fast and CI green on a clean
checkout.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MODEL_DIR = REPO_ROOT / "models"
ARTIFACTS_PRESENT = (MODEL_DIR / "finguard_best_model.joblib").exists() and (
    MODEL_DIR / "model_config.json"
).exists()

requires_artifacts = pytest.mark.skipif(
    not ARTIFACTS_PRESENT,
    reason="models/ artifacts absent - run `python train_model.py` to enable these tests",
)


def raw_txn(
    *,
    sender: str = "rahul.verma@okicici",
    receiver: str = "raju.kirana@okbizaxis",
    amount: float = 240.0,
    age_days: int = 412,
    timestamp: datetime | None = None,
    gap_sec: float = 3600.0,
    city: str = "Pune",
) -> dict:
    """One raw row in the shape `engineer_features` expects."""
    return {
        "timestamp": pd.Timestamp(timestamp or datetime(2026, 7, 15, 13, 24)),
        "sender_vpa": sender,
        "receiver_vpa": receiver,
        "amount": amount,
        "receiver_vpa_age_days": age_days,
        "time_since_last_txn_sec": gap_sec,
        "sender_city": city,
    }


@pytest.fixture
def single_row() -> pd.DataFrame:
    return pd.DataFrame([raw_txn()])


@pytest.fixture
def rupee_one_pair() -> pd.DataFrame:
    """The Rs.1 probe followed 43 seconds later by the drain, same sender and receiver.

    This is the sequence the lag features exist for, and the fixture most likely to
    catch a regression in them: the scam is invisible in either row alone.
    """
    base = datetime(2026, 7, 20, 20, 15)
    return pd.DataFrame(
        [
            raw_txn(
                sender="victim.suresh@okhdfcbank",
                receiver="verify.acct@paytm",
                amount=1.0,
                age_days=0,
                timestamp=base,
                gap_sec=7200.0,
            ),
            raw_txn(
                sender="victim.suresh@okhdfcbank",
                receiver="verify.acct@paytm",
                amount=62000.0,
                age_days=0,
                timestamp=base + timedelta(seconds=43),
                gap_sec=43.0,
            ),
        ]
    )


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    """A fresh ledger per test, on disk, closed afterwards."""
    from audit_store import AuditStore

    monkeypatch.setenv("FINGUARD_AUDIT_DB", str(tmp_path / "audit.db"))
    store = AuditStore(tmp_path / "audit.db")
    store.connect()
    yield store
    store.close()
