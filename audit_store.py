"""FinGuard Module 5 - the decision ledger.

Every score the engine produces is written here before the response leaves the
process, together with the model version that produced it and the full SHAP vector
behind it. That is what turns "the model said 0.98" into something a risk team can
defend three months later, when the model has been retrained twice and the customer
has raised a complaint about a payment that was held.

Three properties this file exists to guarantee:

**The decision record is immutable.** `decisions` is written once and never updated.
Analyst feedback lands in a separate `dispositions` table with its own rows and its
own timestamps, so "what the model decided" and "what a human later concluded" stay
distinguishable. An audit trail you can edit is not an audit trail.

**The explanation is stored whole, not summarised.** The API response carries the
concepts that mattered; the ledger carries every concept with its signed value. A
stored top-3 would be a rendering of the explanation rather than the explanation, and
could not be re-derived into a different view later.

**A ledger failure must never become a scoring failure.** Blocking a payment is the
product; recording it is bookkeeping. If the disk is full or the file is locked, the
write is logged and dropped and the caller still gets a verdict - the alternative is
a fraud engine that stops detecting fraud because a log file broke. `/api/v1/health`
reports the degradation so it is visible rather than silent.

Storage is SQLite in WAL mode: single file, no daemon, concurrent readers alongside
a writer, and `sqlite3` is in the standard library. At Razorpay-scale volume this is
the component you would swap for Postgres plus an object store for the SHAP blobs;
the interface below is deliberately five methods wide so that swap stays cheap.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("finguard.audit")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = Path(os.environ.get("FINGUARD_AUDIT_DB", BASE_DIR / "data" / "finguard_audit.db"))

SCHEMA_VERSION = 2

# `decision_id` is generated here rather than reusing `transaction_id`: a caller may
# resubmit the same transaction id (a retry, a replayed webhook) and each scoring
# event is its own auditable fact. One transaction can therefore own several
# decisions, which is exactly what you want to see when investigating a dispute.
_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id           TEXT PRIMARY KEY,
    transaction_id        TEXT NOT NULL,
    scored_at             TEXT NOT NULL,
    sender_vpa            TEXT NOT NULL,
    receiver_vpa          TEXT NOT NULL,
    amount                REAL NOT NULL,
    receiver_vpa_age_days INTEGER,
    txn_timestamp         TEXT,
    sender_city           TEXT,
    fraud_probability     REAL NOT NULL,
    threshold             REAL NOT NULL,
    decision              TEXT NOT NULL,
    model_name            TEXT NOT NULL,
    model_trained_at      TEXT,
    threshold_policy      TEXT,
    latency_ms            INTEGER NOT NULL,
    reasons_json          TEXT NOT NULL,
    shap_concepts_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_scored_at   ON decisions (scored_at DESC);
CREATE INDEX IF NOT EXISTS idx_decisions_receiver    ON decisions (receiver_vpa);
CREATE INDEX IF NOT EXISTS idx_decisions_transaction ON decisions (transaction_id);

-- Analyst outcomes live apart from the model's decision, and are themselves
-- append-only: a reviewer who changes their mind adds a row, and the sequence of
-- judgements is preserved. `latest_disposition` below reads the most recent one.
CREATE TABLE IF NOT EXISTS dispositions (
    disposition_id TEXT PRIMARY KEY,
    decision_id    TEXT NOT NULL REFERENCES decisions (decision_id),
    recorded_at    TEXT NOT NULL,
    outcome        TEXT NOT NULL,
    reviewer       TEXT,
    note           TEXT
);

CREATE INDEX IF NOT EXISTS idx_dispositions_decision ON dispositions (decision_id, recorded_at DESC);

-- Chargebacks raised against a decision, and the representment packet drafted for
-- each. Append-only for the same reason as everything else here: what was submitted
-- to an acquirer, and on what evidence, has to stay answerable afterwards. The
-- `generated_by` column records whether the language model or the deterministic
-- fallback produced the draft, so a degraded packet is never mistaken for a full one.
CREATE TABLE IF NOT EXISTS disputes (
    dispute_id     TEXT PRIMARY KEY,
    decision_id    TEXT NOT NULL REFERENCES decisions (decision_id),
    raised_at      TEXT NOT NULL,
    dispute_reason TEXT NOT NULL,
    reason_code    TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    confidence     REAL NOT NULL,
    generated_by   TEXT NOT NULL,
    degraded       INTEGER NOT NULL,
    packet_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_disputes_decision ON disputes (decision_id, raised_at DESC);
"""

# What a human reviewer can conclude about an alert. Constrained because these feed
# the precision numbers on the stats endpoint, and a free-text outcome column turns
# that arithmetic into guesswork.
VALID_OUTCOMES = ("confirmed_fraud", "false_positive", "unclear")


def _utc_now() -> str:
    # Microseconds, not seconds: two dispositions on the same alert land inside the
    # same second routinely (a reviewer correcting themselves), and a second-resolution
    # timestamp makes "which came last" unanswerable from the value alone. Ordering
    # still breaks the tie on rowid, but the stored value should not be misleading.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class AuditStore:
    """Append-only ledger of scoring decisions and the human outcomes attached to them."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        # Set when a write raises. Surfaced through /api/v1/health so a broken ledger
        # is visible in the dashboard rather than discovered during an audit.
        self.last_error: str | None = None
        self.degraded = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Open the database and apply the schema. Safe to call more than once."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False because FastAPI runs sync handlers across a thread
        # pool; every access is serialised behind `self._lock` instead.
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        self._conn = conn
        self.degraded = False
        self.last_error = None
        log.info("Audit ledger ready at %s (schema v%d)", self.path, SCHEMA_VERSION)

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def ready(self) -> bool:
        return self._conn is not None

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        if self._conn is None:
            raise RuntimeError("Audit ledger is not connected. Call connect() first.")
        with self._lock:
            cursor = self._conn.cursor()
            try:
                yield cursor
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def record_decision(
        self,
        *,
        transaction_id: str,
        sender_vpa: str,
        receiver_vpa: str,
        amount: float,
        receiver_vpa_age_days: int | None,
        txn_timestamp: str | None,
        sender_city: str | None,
        fraud_probability: float,
        threshold: float,
        decision: str,
        model_name: str,
        model_trained_at: str | None,
        threshold_policy: str | None,
        latency_ms: int,
        reasons: list[str],
        shap_concepts: dict[str, float],
    ) -> str | None:
        """Append one scoring event. Returns its id, or None if the write failed.

        Never raises. A ledger that is down must not take the fraud engine down with
        it, so the failure is recorded on the instance, surfaced through /health, and
        the caller carries on and returns the verdict it already computed.
        """
        decision_id = f"dec-{uuid.uuid4().hex[:16]}"
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO decisions (
                        decision_id, transaction_id, scored_at, sender_vpa, receiver_vpa,
                        amount, receiver_vpa_age_days, txn_timestamp, sender_city,
                        fraud_probability, threshold, decision, model_name,
                        model_trained_at, threshold_policy, latency_ms,
                        reasons_json, shap_concepts_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        decision_id, transaction_id, _utc_now(), sender_vpa, receiver_vpa,
                        float(amount), receiver_vpa_age_days, txn_timestamp, sender_city,
                        float(fraud_probability), float(threshold), decision, model_name,
                        model_trained_at, threshold_policy, int(latency_ms),
                        json.dumps(reasons), json.dumps(shap_concepts),
                    ),
                )
            return decision_id
        except Exception as exc:                      # noqa: BLE001 - deliberate catch-all
            self.degraded = True
            self.last_error = f"{type(exc).__name__}: {exc}"
            log.error("Audit write failed for %s (scoring unaffected): %s", transaction_id, exc)
            return None

    def record_disposition(
        self, decision_id: str, outcome: str, reviewer: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Attach a reviewer's conclusion to a decision. Raises on bad input."""
        if outcome not in VALID_OUTCOMES:
            raise ValueError(f"outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")

        with self._cursor() as cur:
            exists = cur.execute(
                "SELECT 1 FROM decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(decision_id)

            disposition_id = f"dsp-{uuid.uuid4().hex[:12]}"
            recorded_at = _utc_now()
            cur.execute(
                "INSERT INTO dispositions (disposition_id, decision_id, recorded_at, "
                "outcome, reviewer, note) VALUES (?,?,?,?,?,?)",
                (disposition_id, decision_id, recorded_at, outcome, reviewer, note),
            )

        return {
            "disposition_id": disposition_id,
            "decision_id": decision_id,
            "recorded_at": recorded_at,
            "outcome": outcome,
            "reviewer": reviewer,
            "note": note,
        }

    def record_dispute(
        self, decision_id: str, dispute_reason: str, packet: dict[str, Any],
    ) -> dict[str, Any]:
        """Store a chargeback and the packet drafted for it. Raises on an unknown decision.

        Unlike `record_decision`, this one does raise. A scoring decision has already
        been made by the time the ledger is touched, so losing the row is survivable.
        A dispute response that silently vanished would leave a filing deadline
        unmet with nobody aware of it.
        """
        with self._cursor() as cur:
            exists = cur.execute(
                "SELECT 1 FROM decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            if exists is None:
                raise KeyError(decision_id)

            dispute_id = f"dsp-cb-{uuid.uuid4().hex[:12]}"
            raised_at = _utc_now()
            cur.execute(
                "INSERT INTO disputes (dispute_id, decision_id, raised_at, dispute_reason, "
                "reason_code, recommendation, confidence, generated_by, degraded, packet_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    dispute_id, decision_id, raised_at, dispute_reason,
                    str(packet.get("reason_code", "")), str(packet.get("recommendation", "")),
                    float(packet.get("confidence", 0.0)), str(packet.get("generated_by", "")),
                    int(bool(packet.get("degraded", False))), json.dumps(packet),
                ),
            )

        return {"dispute_id": dispute_id, "decision_id": decision_id, "raised_at": raised_at}

    def get_dispute(self, dispute_id: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM disputes WHERE dispute_id = ?", (dispute_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["packet"] = json.loads(record.pop("packet_json"))
        record["degraded"] = bool(record["degraded"])
        return record

    def disputes_for(self, decision_id: str) -> list[dict[str, Any]]:
        """Every dispute raised against one decision, newest first."""
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT dispute_id, raised_at, dispute_reason, reason_code, recommendation, "
                "confidence, generated_by, degraded FROM disputes WHERE decision_id = ? "
                "ORDER BY raised_at DESC, rowid DESC",
                (decision_id,),
            ).fetchall()
        return [dict(r) | {"degraded": bool(r["degraded"])} for r in rows]

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hydrate(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["reasons"] = json.loads(record.pop("reasons_json"))
        record["shap_concepts"] = json.loads(record.pop("shap_concepts_json"))
        return record

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        """One decision with its full explanation and every disposition recorded on it."""
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
            if row is None:
                return None

            record = self._hydrate(row)
            record["dispositions"] = [
                dict(d) for d in cur.execute(
                    "SELECT disposition_id, recorded_at, outcome, reviewer, note "
                    "FROM dispositions WHERE decision_id = ? "
                    "ORDER BY recorded_at DESC, rowid DESC",
                    (decision_id,),
                ).fetchall()
            ]
        return record

    # Anything that is not a clean acceptance belongs on someone's queue. Both
    # vocabularies are listed because the ledger predates the merchant reframe: rows
    # written before it recorded APPROVED/BLOCKED, and an append-only store cannot
    # rewrite its own history to match a later schema.
    ACCEPTED_DECISIONS = ("ACCEPT", "APPROVED")

    def recent_decisions(
        self, limit: int = 50, offset: int = 0, only_actioned: bool = False,
    ) -> list[dict[str, Any]]:
        """Newest decisions first, each carrying its latest disposition if one exists.

        `only_actioned` returns the work queue - held and challenged payments - rather
        than filtering on a single literal. A hardcoded `decision = 'BLOCKED'` silently
        returned nothing the moment the API began emitting three actions instead of
        two, which is exactly the kind of failure a queue endpoint hides: an empty list
        reads as a quiet day.

        The disposition is joined in rather than fetched per row: an alert queue that
        issued one extra query per entry would be the classic N+1, and this endpoint
        exists to be polled.
        """
        placeholders = ",".join("?" * len(self.ACCEPTED_DECISIONS))
        clause = f"WHERE d.decision NOT IN ({placeholders})" if only_actioned else ""
        params: tuple[Any, ...] = self.ACCEPTED_DECISIONS if only_actioned else ()
        with self._cursor() as cur:
            rows = cur.execute(
                f"""
                SELECT d.*, (
                    SELECT p.outcome FROM dispositions p
                    WHERE p.decision_id = d.decision_id
                    ORDER BY p.recorded_at DESC, p.rowid DESC LIMIT 1
                ) AS latest_disposition
                FROM decisions d
                {clause}
                ORDER BY d.scored_at DESC, d.rowid DESC
                LIMIT ? OFFSET ?
                """,
                (*params, max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return [self._hydrate(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        """Live operating summary: volume, block rate, exposure, and reviewed precision.

        `precision_reviewed` is computed only over alerts a human has actually
        dispositioned, and `unclear` outcomes are excluded from both sides rather than
        silently counted as correct. Reporting precision over unreviewed alerts would
        be assuming the answer.
        """
        with self._cursor() as cur:
            totals = cur.execute(
                """
                SELECT
                    COUNT(*)                                                AS total,
                    SUM(CASE WHEN decision NOT IN ('ACCEPT','APPROVED')
                             THEN 1 ELSE 0 END)                             AS actioned,
                    SUM(CASE WHEN decision NOT IN ('ACCEPT','APPROVED')
                             THEN amount ELSE 0 END)                        AS value_blocked,
                    SUM(CASE WHEN decision = 'STEP_UP' THEN 1 ELSE 0 END)   AS stepped_up,
                    SUM(CASE WHEN decision = 'HOLD'    THEN 1 ELSE 0 END)   AS held,
                    AVG(latency_ms)                                         AS avg_latency_ms
                FROM decisions
                """
            ).fetchone()

            reviewed = cur.execute(
                """
                SELECT p.outcome, COUNT(*) AS n
                FROM dispositions p
                JOIN (
                    -- rowid, not MAX(recorded_at): timestamps tie when a reviewer
                    -- revises within the same instant, and a tie there would join
                    -- both rows and count one decision twice.
                    SELECT decision_id, MAX(rowid) AS latest_row
                    FROM dispositions GROUP BY decision_id
                ) newest
                  ON newest.decision_id = p.decision_id AND newest.latest_row = p.rowid
                GROUP BY p.outcome
                """
            ).fetchall()

            disputes = cur.execute(
                "SELECT COUNT(*) AS n, "
                "SUM(CASE WHEN recommendation = 'represent' THEN 1 ELSE 0 END) AS represented, "
                "SUM(degraded) AS degraded_drafts FROM disputes"
            ).fetchone()

        counts = {row["outcome"]: row["n"] for row in reviewed}
        confirmed = counts.get("confirmed_fraud", 0)
        false_pos = counts.get("false_positive", 0)
        judged = confirmed + false_pos

        total = totals["total"] or 0
        blocked = totals["actioned"] or 0
        return {
            "decisions_recorded": total,
            "blocked": blocked,
            "stepped_up": totals["stepped_up"] or 0,
            "held": totals["held"] or 0,
            "approved": total - blocked,
            "block_rate": (blocked / total) if total else 0.0,
            "value_blocked_inr": float(totals["value_blocked"] or 0.0),
            "avg_latency_ms": float(totals["avg_latency_ms"] or 0.0),
            "reviewed": judged,
            "confirmed_fraud": confirmed,
            "false_positives": false_pos,
            "unclear": counts.get("unclear", 0),
            "precision_reviewed": (confirmed / judged) if judged else None,
            "disputes_raised": disputes["n"] or 0,
            "disputes_represented": disputes["represented"] or 0,
            "packets_drafted_degraded": disputes["degraded_drafts"] or 0,
        }


# Module-level instance, mirroring how `main.py` holds one FraudEngine.
store = AuditStore()
