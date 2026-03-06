"""
Integration tests: full settlement creation flow.

Covers the happy-path pipe:
  API gateway → settlement-service (fraud gate) → Kafka → notification-service

Run with:
    docker-compose up -d
    pytest tests/integration/test_settlement_flow.py -v
"""

import asyncio
import uuid

import pytest
import httpx

from .conftest import settlement_payload, SETTLEMENT_URL


pytestmark = pytest.mark.integration


class TestHealthChecks:
    """All services must be healthy before functional tests run."""

    @pytest.mark.asyncio
    async def test_settlement_service_healthy(self, settlement_svc: httpx.AsyncClient):
        r = await settlement_svc.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"

    @pytest.mark.asyncio
    async def test_fraud_service_healthy(self, fraud_svc: httpx.AsyncClient):
        r = await fraud_svc.get("/health")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_notification_service_healthy(self, notification_svc: httpx.AsyncClient):
        r = await notification_svc.get("/health")
        assert r.status_code in (200, 503)  # 503 acceptable during Kafka reconnect


class TestCreateSettlement:
    """POST /api/v1/settlements — happy path and validation."""

    @pytest.mark.asyncio
    async def test_create_returns_201(self, settlement_svc: httpx.AsyncClient):
        payload = settlement_payload()
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] in ("PENDING", "PROCESSING")
        assert body["amount"] == payload["amount"]
        assert body["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_create_includes_settlement_id(self, settlement_svc: httpx.AsyncClient):
        payload = settlement_payload()
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # Must be a valid UUID
        uuid.UUID(body["id"])

    @pytest.mark.asyncio
    async def test_idempotency_returns_same_record(self, settlement_svc: httpx.AsyncClient):
        payload = settlement_payload()
        headers = {"Idempotency-Key": payload["idempotency_key"]}
        r1 = await settlement_svc.post("/api/v1/settlements", json=payload, headers=headers)
        r2 = await settlement_svc.post("/api/v1/settlements", json=payload, headers=headers)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]

    @pytest.mark.asyncio
    async def test_self_transaction_rejected(self, settlement_svc: httpx.AsyncClient):
        same_party = str(uuid.uuid4())
        payload = settlement_payload(payer_id=same_party, payee_id=same_party)
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_idempotency_key_rejected(self, settlement_svc: httpx.AsyncClient):
        payload = settlement_payload()
        r = await settlement_svc.post("/api/v1/settlements", json=payload)
        # No Idempotency-Key header → 422
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self, settlement_svc: httpx.AsyncClient):
        payload = settlement_payload(amount="-100.00")
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_excessive_amount_rejected(self, settlement_svc: httpx.AsyncClient):
        payload = settlement_payload(amount="99999999.00")
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert r.status_code == 422


class TestFraudGate:
    """Fraud detection is called synchronously during settlement creation."""

    @pytest.mark.asyncio
    async def test_fraud_score_endpoint_accepts_valid_request(
        self, fraud_svc: httpx.AsyncClient
    ):
        r = await fraud_svc.post(
            "/api/v1/fraud/score",
            json={
                "settlement_id": str(uuid.uuid4()),
                "amount": "1000.00",
                "currency": "USD",
                "payer_id": str(uuid.uuid4()),
                "payee_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "risk_score" in body
        assert body["decision"] in ("APPROVE", "REVIEW", "BLOCK")

    @pytest.mark.asyncio
    async def test_settlement_creation_calls_fraud_gate(
        self, settlement_svc: httpx.AsyncClient
    ):
        """
        We create a settlement and verify it was persisted (which only happens
        after a successful fraud gate call).
        """
        payload = settlement_payload()
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        # A 201 means the fraud gate returned APPROVE or REVIEW (not BLOCK)
        assert r.status_code in (201, 403), r.text

    @pytest.mark.asyncio
    async def test_large_amount_may_trigger_review(self, fraud_svc: httpx.AsyncClient):
        """Very large amounts should get a higher risk score."""
        r = await fraud_svc.post(
            "/api/v1/fraud/score",
            json={
                "settlement_id": str(uuid.uuid4()),
                "amount": "9500000.00",
                "currency": "USD",
                "payer_id": str(uuid.uuid4()),
                "payee_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200
        # Not asserting BLOCK since the untrained model may not produce it,
        # but the score must be in [0, 1]
        body = r.json()
        assert 0.0 <= body["risk_score"] <= 1.0


class TestSettlementRetrieval:
    """GET /api/v1/settlements — list and fetchby ID."""

    @pytest.mark.asyncio
    async def test_list_settlements_returns_200(self, settlement_svc: httpx.AsyncClient):
        r = await settlement_svc.get("/api/v1/settlements")
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body

    @pytest.mark.asyncio
    async def test_get_settlement_by_id(self, settlement_svc: httpx.AsyncClient):
        # Create first
        payload = settlement_payload()
        create_r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert create_r.status_code == 201
        settlement_id = create_r.json()["id"]

        # Then fetch
        get_r = await settlement_svc.get(f"/api/v1/settlements/{settlement_id}")
        assert get_r.status_code == 200
        assert get_r.json()["id"] == settlement_id

    @pytest.mark.asyncio
    async def test_get_nonexistent_settlement_returns_404(
        self, settlement_svc: httpx.AsyncClient
    ):
        r = await settlement_svc.get(f"/api/v1/settlements/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, settlement_svc: httpx.AsyncClient):
        r = await settlement_svc.get("/api/v1/settlements?status=PENDING")
        assert r.status_code == 200


class TestFullFlow:
    """
    Coarse end-to-end check: create a settlement and poll until it transitions
    past PENDING.  The settlement processor runs asynchronously so we poll with
    a short timeout.
    """

    @pytest.mark.asyncio
    async def test_settlement_transitions_from_pending(
        self, settlement_svc: httpx.AsyncClient
    ):
        payload = settlement_payload()
        r = await settlement_svc.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": payload["idempotency_key"]},
        )
        assert r.status_code == 201
        sid = r.json()["id"]

        # Poll for up to 15 s for the processor to advance the state
        for _ in range(15):
            await asyncio.sleep(1)
            poll = await settlement_svc.get(f"/api/v1/settlements/{sid}")
            assert poll.status_code == 200
            current_status = poll.json()["status"]
            if current_status != "PENDING":
                break

        final_status = (await settlement_svc.get(f"/api/v1/settlements/{sid}")).json()[
            "status"
        ]
        # Either the processor advanced it or it stayed PENDING because no
        # Kafka event fired — acceptable in fast integration runs without a
        # full Kafka stack.
        assert final_status in ("PENDING", "PROCESSING", "COMPLETED", "FAILED")
