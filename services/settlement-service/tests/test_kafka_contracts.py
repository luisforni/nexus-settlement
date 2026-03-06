from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent.parent
CONTRACTS_DIR = REPO_ROOT / "shared" / "contracts"

SETTLEMENT_SCHEMA: dict[str, Any] = json.loads(
    (CONTRACTS_DIR / "settlement-event.json").read_text()
)

validator = jsonschema.Draft7Validator(
    SETTLEMENT_SCHEMA,
    format_checker=jsonschema.FormatChecker(),
)

def _uuid() -> str:
    return str(uuid.uuid4())

def _hash() -> str:

    return "a" * 64

def make_settlement_event(
    event_type: str = "settlement.completed",
    status: str = "COMPLETED",
    amount: str = "100.00",
    currency: str = "USD",
    *,
    extra_payload: dict[str, Any] | None = None,
    extra_top: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid settlement event envelope."""
    payload: dict[str, Any] = {
        "settlement_id": _uuid(),
        "status": status,
        "amount": amount,
        "currency": currency,
        "payer_id": _uuid(),
        "payee_id": _uuid(),
    }
    if extra_payload:
        payload.update(extra_payload)

    event: dict[str, Any] = {
        "event_id": _uuid(),
        "event_type": event_type,
        "schema_version": "1.0.0",
        "timestamp": "2026-03-10T12:00:00Z",
        "payload": payload,
        "integrity_hash": _hash(),
    }
    if extra_top:
        event.update(extra_top)
    return event

@pytest.mark.parametrize(
    "event_type,status",
    [
        ("settlement.created", "PENDING"),
        ("settlement.processing", "PROCESSING"),
        ("settlement.completed", "COMPLETED"),
        ("settlement.failed", "FAILED"),
        ("settlement.cancelled", "CANCELLED"),
        ("settlement.reversed", "REVERSED"),
    ],
)
def test_valid_event_type_and_status(event_type: str, status: str) -> None:
    event = make_settlement_event(event_type=event_type, status=status)
    errors = list(validator.iter_errors(event))
    assert errors == [], "\n".join(str(e) for e in errors)

@pytest.mark.parametrize(
    "amount",
    [
        "0.01",
        "100.00",
        "9999999.99",
        "0.12345678",
        "1.00",
    ],
)
def test_valid_amount_formats(amount: str) -> None:
    event = make_settlement_event(amount=amount)
    errors = list(validator.iter_errors(event))
    assert errors == [], f"Amount {amount!r} rejected: {errors}"

@pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "JPY", "BRL"])
def test_valid_iso4217_currencies(currency: str) -> None:
    event = make_settlement_event(currency=currency)
    assert list(validator.iter_errors(event)) == []

def test_optional_fields_accepted() -> None:
    event = make_settlement_event(
        extra_payload={
            "description": "Test payment",
            "risk_score": 0.42,
            "fraud_decision": "APPROVE",
            "completed_at": "2026-03-10T12:01:00Z",
            "user_email": "user@example.com",
            "version": 2,
        }
    )
    assert list(validator.iter_errors(event)) == []

def test_idempotency_key_accepted() -> None:
    event = make_settlement_event(extra_top={"idempotency_key": "idem-key-12345"})
    assert list(validator.iter_errors(event)) == []

def test_missing_event_id_is_rejected() -> None:
    event = make_settlement_event()
    del event["event_id"]
    assert list(validator.iter_errors(event)) != []

def test_missing_integrity_hash_is_rejected() -> None:
    event = make_settlement_event()
    del event["integrity_hash"]
    assert list(validator.iter_errors(event)) != []

def test_invalid_event_type_is_rejected() -> None:
    event = make_settlement_event(event_type="settlement.invented")
    assert list(validator.iter_errors(event)) != []

def test_invalid_uuid_event_id_is_rejected() -> None:
    event = make_settlement_event(extra_top={"event_id": "not-a-uuid"})
    errors = list(validator.iter_errors(event))
    assert any("uuid" in str(e).lower() for e in errors)

@pytest.mark.parametrize(
    "bad_amount",
    [
        "100",
        "100.1",
        "-50.00",
        "abc",
        "100.123456789",
    ],
)
def test_invalid_amount_formats_rejected(bad_amount: str) -> None:
    event = make_settlement_event(amount=bad_amount)
    assert list(validator.iter_errors(event)) != [], f"Amount {bad_amount!r} should be rejected"

@pytest.mark.parametrize(
    "bad_currency",
    [
        "us",
        "USDT",
        "123",
        "",
    ],
)
def test_invalid_currencies_rejected(bad_currency: str) -> None:
    event = make_settlement_event(currency=bad_currency)
    assert list(validator.iter_errors(event)) != []

def test_invalid_status_rejected() -> None:
    event = make_settlement_event(status="UNKNOWN")
    assert list(validator.iter_errors(event)) != []

def test_invalid_integrity_hash_length_rejected() -> None:
    event = make_settlement_event(extra_top={"integrity_hash": "abc123"})
    assert list(validator.iter_errors(event)) != []

def test_additional_top_level_properties_rejected() -> None:
    event = make_settlement_event(extra_top={"unexpected_field": "value"})
    assert list(validator.iter_errors(event)) != []

def test_risk_score_out_of_range_rejected() -> None:
    event = make_settlement_event(extra_payload={"risk_score": 1.5})
    assert list(validator.iter_errors(event)) != []

def test_description_too_long_rejected() -> None:
    event = make_settlement_event(extra_payload={"description": "x" * 256})
    assert list(validator.iter_errors(event)) != []

@pytest.mark.parametrize("version", ["1.0.0", "2.3.11", "0.0.1"])
def test_valid_schema_versions(version: str) -> None:
    event = make_settlement_event(extra_top={"schema_version": version})
    assert list(validator.iter_errors(event)) == []

@pytest.mark.parametrize("bad_version", ["1", "1.0", "v1.0.0", "latest"])
def test_invalid_schema_versions_rejected(bad_version: str) -> None:
    event = make_settlement_event(extra_top={"schema_version": bad_version})
    assert list(validator.iter_errors(event)) != []

def test_decimal_amount_parsing_precision() -> None:

    amount_str = "1234567.89"
    assert Decimal(amount_str) == Decimal("1234567.89")

    event = make_settlement_event(amount=amount_str)
    assert list(validator.iter_errors(event)) == []
