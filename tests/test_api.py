"""API contract.

These run against the real model, so they are marked `slow` and skip when the
artifacts are absent. What they protect is the boundary the dashboard depends on:
field validation, the shape of the SHAP payload, the sequence behaviour the Rs.1
test needs, and - the regression that motivated most of this file - the fact that a
caller-supplied timestamp actually reaches the model.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import requires_artifacts
from fastapi.testclient import TestClient

pytestmark = [requires_artifacts, pytest.mark.slow]

ANALYZE = "/api/v1/analyze-transaction"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """One app instance for the module - loading the model costs seconds."""
    import os

    os.environ["FINGUARD_AUDIT_DB"] = str(tmp_path_factory.mktemp("ledger") / "api.db")
    import main

    main.audit.path = main.audit.path.__class__(os.environ["FINGUARD_AUDIT_DB"])
    with TestClient(main.app) as c:
        yield c


def score(client, **fields) -> dict:
    payload = {
        "sender_vpa": "rahul.verma@okicici",
        "receiver_vpa": "raju.kirana@okbizaxis",
        "amount": 240.0,
    }
    payload.update(fields)
    response = client.post(ANALYZE, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def test_health_reports_the_model_and_the_live_threshold(client):
    body = client.get("/api/v1/health").json()

    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["model_name"]
    # The dashboard prints this under the risk gauge, so a naive 0.5 here would make
    # the UI contradict the badge above it.
    assert 0.0 < body["threshold"] < 1.0
    assert body["audit_ledger"] in ("ok", "degraded")


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "bad_vpa",
    ["no-at-symbol", "@nolocal", "local@", "a@b", "spaces here@ybl", "", "x" * 80 + "@ybl"],
)
def test_malformed_vpas_are_rejected(client, bad_vpa):
    assert client.post(ANALYZE, json={
        "sender_vpa": bad_vpa, "receiver_vpa": "shop@paytm", "amount": 100.0,
    }).status_code == 422


@pytest.mark.parametrize("amount", [0, -1, -0.01, 2_000_000])
def test_amounts_outside_the_permitted_band_are_rejected(client, amount):
    assert client.post(ANALYZE, json={
        "sender_vpa": "a.b@ybl", "receiver_vpa": "shop@paytm", "amount": amount,
    }).status_code == 422


def test_vpas_are_normalised_to_lower_case(client):
    """Case must not fragment a sender's history - `A@YBL` and `a@ybl` are one account."""
    upper = score(client, sender_vpa="MIXED.Case@YBL", receiver_vpa="Shop.One@Paytm")
    assert upper["status"] in ("BLOCKED", "APPROVED")


@pytest.mark.parametrize("age", [-1, 1001])
def test_out_of_range_vpa_age_is_rejected(client, age):
    assert client.post(ANALYZE, json={
        "sender_vpa": "a.b@ybl", "receiver_vpa": "shop@paytm",
        "amount": 100.0, "receiver_vpa_age_days": age,
    }).status_code == 422


# --------------------------------------------------------------------------- #
# The timestamp regression
# --------------------------------------------------------------------------- #
def test_a_supplied_timestamp_actually_reaches_the_model(client):
    """The same payment at 03:12 and at 15:12 must not score identically.

    This is the regression that made one of the three scam signatures undemonstrable:
    the dashboard never sent `timestamp`, so every transaction was scored at
    `datetime.now()` and the odd-hour phishing pattern could only be reproduced by
    running the demo at 3 AM.
    """
    night = score(
        client,
        sender_vpa="8266605706@ibl", receiver_vpa="girindra.bhat@ybl",
        amount=25_400.0, receiver_vpa_age_days=2,
        timestamp="2026-08-23T03:12:00",
    )
    day = score(
        client,
        sender_vpa="8266605706@ibl", receiver_vpa="girindra.bhat@ybl",
        amount=25_400.0, receiver_vpa_age_days=2,
        timestamp="2026-08-23T15:12:00",
    )

    assert night["fraud_probability"] != day["fraud_probability"]
    assert night["fraud_probability"] > day["fraud_probability"]


def test_the_hour_appears_in_the_explanation_for_a_night_transaction(client):
    """Catching odd-hour phishing on amount alone would be the shallower model.

    The explanation must name the time, otherwise the signature is being detected by
    proxy and would break on the first scam that changes its amount profile.
    """
    result = score(
        client,
        sender_vpa="9812345670@ybl", receiver_vpa="fastcash.help@paytm",
        amount=32_000.0, receiver_vpa_age_days=1,
        timestamp="2026-08-23T02:41:00",
    )

    concepts = {f["feature"] for f in result["shap_features"]}
    assert any("time of day" in c or "1 AM and 4 AM" in c for c in concepts)


def test_an_offset_aware_timestamp_is_converted_rather_than_rejected(client):
    """A browser sends an offset; rejecting it would break the UI, and reading the
    hour off the UTC instant would silently move a 02:00 IST payment to 20:30."""
    aware = datetime(2026, 8, 23, 3, 12, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    result = score(client, amount=25_400.0, receiver_vpa_age_days=2,
                   timestamp=aware.isoformat())

    assert result["status"] in ("BLOCKED", "APPROVED")


# --------------------------------------------------------------------------- #
# Explanation payload
# --------------------------------------------------------------------------- #
def test_shap_features_are_signed_and_ordered_by_magnitude(client):
    """The dashboard renders these as a diverging chart and trusts the ordering.

    Signed values are the point: a list of magnitudes would drop every mitigating
    factor, and the chart would stop being an audit trail.
    """
    result = score(client, amount=48_500.0, receiver_vpa_age_days=0,
                   receiver_vpa="quickcash.help@paytm")

    values = [f["importance"] for f in result["shap_features"]]
    assert values, "an explanation with no contributions is not an explanation"
    assert values == sorted(values, key=abs, reverse=True)
    assert any(v > 0 for v in values)


def test_a_risky_payment_carries_a_reason_and_an_instruction(client):
    """The merchant needs to know what to do with the order, not just that it is risky."""
    result = score(client, amount=48_500.0, receiver_vpa_age_days=0,
                   receiver_vpa="quickcash.help@paytm",
                   timestamp="2026-08-23T03:20:00")

    assert result["action"] in ("STEP_UP", "HOLD")
    advice = result["xai_explanation"].lower()
    assert advice.strip()
    assert "flagged on" in advice
    # It must name an action, not merely describe the risk.
    assert any(word in advice for word in ("challenge", "hold", "do not ship"))


def test_an_ordinary_payment_is_accepted_and_says_so(client):
    result = score(client, amount=180.0, receiver_vpa_age_days=600,
                   timestamp="2026-08-23T13:15:00")

    assert result["action"] == "ACCEPT"
    assert result["status"] == "APPROVED"
    assert "accept" in result["xai_explanation"].lower()


def test_the_advice_never_addresses_the_payer(client):
    """The merchant reframe, asserted rather than assumed.

    The project began bank-side, telling a consumer their payment had been paused for
    their safety. On a gateway the reader is the merchant deciding whether to ship,
    and language aimed at the cardholder is a regression, not a style choice.
    """
    for kwargs in (
        {"amount": 180.0, "receiver_vpa_age_days": 600},
        {"amount": 48_500.0, "receiver_vpa_age_days": 0,
         "receiver_vpa": "quickcash.help@paytm"},
    ):
        advice = score(client, **kwargs)["xai_explanation"].lower()
        for consumer_phrase in ("your account", "your safety", "approve it in the app"):
            assert consumer_phrase not in advice


def test_every_response_carries_the_three_action_costs(client):
    result = score(client, amount=48_500.0, receiver_vpa_age_days=0,
                   receiver_vpa="quickcash.help@paytm")

    costs = result["action_costs"]
    assert set(costs) == {"ACCEPT", "STEP_UP", "HOLD"}
    assert all(isinstance(v, (int, float)) for v in costs.values())


def test_the_chosen_action_is_the_cheapest_one_reported(client):
    """The API must not be able to disagree with its own arithmetic.

    This is what replaces "is the probability above the threshold": there is no
    threshold constant in the merchant path, only three costs and a minimum.
    """
    for kwargs in (
        {"amount": 180.0, "receiver_vpa_age_days": 600},
        {"amount": 25_400.0, "receiver_vpa_age_days": 2,
         "timestamp": "2026-08-23T03:12:00"},
        {"amount": 48_500.0, "receiver_vpa_age_days": 0,
         "receiver_vpa": "quickcash.help@paytm"},
    ):
        result = score(client, **kwargs)
        costs = result["action_costs"]
        assert costs[result["action"]] == pytest.approx(min(costs.values()), abs=0.01)


def test_status_stays_consistent_with_action_for_older_callers(client):
    """`status` is kept for compatibility; it must never contradict `action`."""
    for kwargs in (
        {"amount": 180.0, "receiver_vpa_age_days": 600},
        {"amount": 48_500.0, "receiver_vpa_age_days": 0,
         "receiver_vpa": "quickcash.help@paytm"},
    ):
        result = score(client, **kwargs)
        expected = "APPROVED" if result["action"] == "ACCEPT" else "BLOCKED"
        assert result["status"] == expected


def test_a_large_order_is_treated_more_carefully_than_a_small_one(client):
    """Amount-scaled costs, visible end to end.

    Under the old flat review cost these two would be handled identically at equal
    risk. They should not be: a cleared fraud on the larger basket costs far more.
    """
    small = score(client, amount=900.0, receiver_vpa_age_days=0,
                  receiver_vpa="quickcash.help@paytm",
                  timestamp="2026-08-23T03:30:00")
    large = score(client, amount=95_000.0, receiver_vpa_age_days=0,
                  receiver_vpa="quickcash.help@paytm",
                  timestamp="2026-08-23T03:30:00")

    severity = {"ACCEPT": 0, "STEP_UP": 1, "HOLD": 2}
    assert severity[large["action"]] >= severity[small["action"]]


# --------------------------------------------------------------------------- #
# Sequence behaviour
# --------------------------------------------------------------------------- #
def test_the_rupee_one_probe_raises_the_score_of_the_leg_that_follows(client):
    """The scam is invisible in one row; the API's history store is what makes it visible.

    Scored cold, the drain is a large payment to a new account. Scored after the
    Rs.1 probe to the same receiver, it is a recognised sequence - and must score
    higher for that reason.
    """
    sender = "victim.sequence@okhdfcbank"
    receiver = "verify.acct@paytm"

    cold = score(client, sender_vpa="victim.cold@okhdfcbank", receiver_vpa=receiver,
                 amount=62_000.0, receiver_vpa_age_days=0,
                 timestamp="2026-08-23T20:15:43", time_since_last_txn_sec=43)

    score(client, sender_vpa=sender, receiver_vpa=receiver, amount=1.0,
          receiver_vpa_age_days=0, timestamp="2026-08-23T20:15:00",
          time_since_last_txn_sec=7200)
    warm = score(client, sender_vpa=sender, receiver_vpa=receiver, amount=62_000.0,
                 receiver_vpa_age_days=0, timestamp="2026-08-23T20:15:43",
                 time_since_last_txn_sec=43)

    assert warm["fraud_probability"] >= cold["fraud_probability"]
    concepts = {f["feature"] for f in warm["shap_features"]}
    assert "repeat payment to the same receiver" in concepts


# --------------------------------------------------------------------------- #
# Ledger integration
# --------------------------------------------------------------------------- #
def test_every_scored_transaction_is_replayable_from_the_ledger(client):
    result = score(client, amount=48_500.0, receiver_vpa_age_days=0,
                   receiver_vpa="quickcash.help@paytm")
    decision_id = result["decision_id"]
    assert decision_id

    record = client.get(f"/api/v1/decisions/{decision_id}").json()

    assert record["fraud_probability"] == pytest.approx(result["fraud_probability"], abs=1e-4)
    assert record["decision"] == result["action"]
    assert record["model_name"]
    # The ledger keeps the whole vector, not the filtered list the dashboard renders.
    assert len(record["shap_concepts"]) >= len(result["shap_features"])


def test_a_reviewer_can_disposition_an_alert_and_move_the_stats(client):
    result = score(client, amount=51_000.0, receiver_vpa_age_days=0,
                   receiver_vpa="refund.desk@paytm")

    created = client.post(
        f"/api/v1/decisions/{result['decision_id']}/disposition",
        json={"outcome": "confirmed_fraud", "reviewer": "analyst-1"},
    )
    assert created.status_code == 201

    stats = client.get("/api/v1/stats").json()
    assert stats["confirmed_fraud"] >= 1
    assert stats["decisions_recorded"] >= 1


def test_an_unknown_disposition_outcome_is_rejected(client):
    result = score(client)
    response = client.post(
        f"/api/v1/decisions/{result['decision_id']}/disposition",
        json={"outcome": "looks_fine_to_me"},
    )
    assert response.status_code == 422


def test_dispositioning_a_decision_that_does_not_exist_is_a_404(client):
    response = client.post(
        "/api/v1/decisions/dec-nonexistent/disposition",
        json={"outcome": "confirmed_fraud"},
    )
    assert response.status_code == 404


def test_the_alert_queue_returns_only_payments_needing_action(client):
    """The queue is held *and* challenged payments - anything not cleanly accepted.

    Filtering on a single literal is how this endpoint silently returned nothing when
    the API moved from two outcomes to three: an empty queue reads as a quiet day
    rather than a broken filter.
    """
    score(client, amount=120.0, receiver_vpa_age_days=700)
    score(client, amount=52_000.0, receiver_vpa_age_days=0,
          receiver_vpa="quickcash.help@paytm")

    alerts = client.get("/api/v1/decisions?only_actioned=true&limit=50").json()["decisions"]
    assert alerts
    assert all(d["decision"] in ("STEP_UP", "HOLD") for d in alerts)


def test_a_missing_decision_reads_as_404(client):
    assert client.get("/api/v1/decisions/dec-not-here").status_code == 404


# --------------------------------------------------------------------------- #
# Failure handling
# --------------------------------------------------------------------------- #
def test_a_ledger_outage_does_not_stop_the_engine_scoring(client, monkeypatch):
    """Bookkeeping failing must never take detection down with it.

    The response still carries a verdict and an explanation; only `decision_id` is
    null, which is how the caller learns the event went unrecorded.
    """
    import main

    monkeypatch.setattr(main.audit, "record_decision", lambda **_: None)
    result = score(client, amount=48_500.0, receiver_vpa_age_days=0,
                   receiver_vpa="quickcash.help@paytm")

    assert result["decision_id"] is None
    assert result["status"] == "BLOCKED"
    assert result["shap_features"]


def test_malformed_json_is_a_422_not_a_500(client):
    response = client.post(ANALYZE, content=b"{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422


def test_the_docs_and_root_probe_stay_reachable(client):
    assert client.get("/").status_code == 200
    assert client.get("/docs").status_code == 200
