from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
CONTRACTS_DIR = REPO_ROOT / "shared" / "contracts"

FRAUD_SCHEMA: dict[str, Any] = json.loads(
    (CONTRACTS_DIR / "fraud-alert-event.json").read_text()
)

validator = jsonschema.Draft7Validator(
    FRAUD_SCHEMA,
    format_checker=jsonschema.FormatChecker(),
)

def _uuid() -> str:
    return str(uuid.uuid4())

def make_fraud_event(
    event_type: str = "fraud.scored",
    decision: str = "APPROVE",
    risk_score: float = 0.12,
    *,
    extra_payload: dict[str, Any] | None = None,
    extra_top: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "transaction_id": _uuid(),
        "settlement_id": _uuid(),
        "risk_score": risk_score,
        "decision": decision,
        "model_version": "xgb-v1.2.0",
        "features_used": 18,
    }
    if extra_payload:
        payload.update(extra_payload)

    event: dict[str, Any] = {
        "event_id": _uuid(),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": "2026-03-10T12:00:00Z",
        "payload": payload,
    }
    if extra_top:
        event.update(extra_top)
    return event

@pytest.mark.parametrize(
    "event_type,decision",
    [
        ("fraud.scored", "APPROVE"),
        ("fraud.review", "REVIEW"),
        ("fraud.blocked", "BLOCK"),
    ],
)
def test_valid_event_type_and_decision(event_type: str, decision: str) -> None:
    event = make_fraud_event(event_type=event_type, decision=decision)
    errors = list(validator.iter_errors(event))
    assert errors == [], "\n".join(str(e) for e in errors)

@pytest.mark.parametrize("score", [0.0, 0.01, 0.5, 0.74, 0.99, 1.0])
def test_valid_risk_score_range(score: float) -> None:
    event = make_fraud_event(risk_score=score)
    assert list(validator.iter_errors(event)) == []

def test_top_risk_factors_accepted() -> None:
    event = make_fraud_event(
        extra_payload={
            "top_risk_factors": [
                {"feature": "amount_zscore", "shap_value": 0.87, "contribution": "increases_risk"},
                {"feature": "country_risk", "shap_value": -0.12, "contribution": "decreases_risk"},
            ]
        }
    )
    assert list(validator.iter_errors(event)) == []

def test_rule_triggered_accepted() -> None:
    event = make_fraud_event(
        extra_payload={"rule_triggered": "HIGH_AMOUNT_FIRST_TX", "decision": "BLOCK"},
        decision="BLOCK",
        event_type="fraud.blocked",
    )
    assert list(validator.iter_errors(event)) == []

def test_rule_triggered_null_accepted() -> None:
    event = make_fraud_event(extra_payload={"rule_triggered": None})
    assert list(validator.iter_errors(event)) == []

def test_latency_ms_accepted() -> None:
    event = make_fraud_event(extra_payload={"latency_ms": 42})
    assert list(validator.iter_errors(event)) == []

def test_invalid_event_type_rejected() -> None:
    event = make_fraud_event(event_type="fraud.invented")
    assert list(validator.iter_errors(event)) != []

def test_invalid_decision_rejected() -> None:
    event = make_fraud_event(decision="ALLOW")
    assert list(validator.iter_errors(event)) != []

@pytest.mark.parametrize("bad_score", [-0.01, 1.01, 2.0])
def test_risk_score_out_of_range_rejected(bad_score: float) -> None:
    event = make_fraud_event(risk_score=bad_score)
    assert list(validator.iter_errors(event)) != []

def test_missing_transaction_id_rejected() -> None:
    event = make_fraud_event()
    del event["payload"]["transaction_id"]
    assert list(validator.iter_errors(event)) != []

def test_missing_settlement_id_rejected() -> None:
    event = make_fraud_event()
    del event["payload"]["settlement_id"]
    assert list(validator.iter_errors(event)) != []

def test_features_used_zero_rejected() -> None:

    event = make_fraud_event(extra_payload={"features_used": 0})
    assert list(validator.iter_errors(event)) != []

def test_top_risk_factors_overflow_rejected() -> None:

    factors = [{"feature": f"f{i}", "shap_value": float(i) * 0.1} for i in range(11)]
    event = make_fraud_event(extra_payload={"top_risk_factors": factors})
    assert list(validator.iter_errors(event)) != []

def test_additional_payload_properties_rejected() -> None:
    event = make_fraud_event(extra_payload={"undocumented_field": "value"})
    assert list(validator.iter_errors(event)) != []

def test_missing_model_version_rejected() -> None:
    event = make_fraud_event()
    del event["payload"]["model_version"]
    assert list(validator.iter_errors(event)) != []
