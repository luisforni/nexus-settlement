from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from app.messaging.kafka_producer import KafkaProducer

class TestSettlementCreation:

    @pytest.mark.asyncio
    async def test_create_settlement_success(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Happy path: valid payload returns 201 with settlement fields."""
        idempotency_key = valid_settlement_payload["idempotency_key"]
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "PENDING"
        assert data["currency"] == "USD"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_settlement_idempotent(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Submitting the same Idempotency-Key twice returns the same record."""
        idempotency_key = str(uuid.uuid4())
        valid_settlement_payload["idempotency_key"] = idempotency_key

        resp1 = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        resp2 = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": idempotency_key},
        )

        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["id"] == resp2.json()["id"]

    @pytest.mark.asyncio
    async def test_create_settlement_missing_idempotency_key(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Missing Idempotency-Key header returns 422."""
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_settlement_self_transaction(
        self,
        client: AsyncClient,
    ) -> None:
        """payer_id == payee_id returns 422 Unprocessable Entity."""
        same_id = str(uuid.uuid4())
        payload = {
            "idempotency_key": str(uuid.uuid4()),
            "amount": "500.00",
            "currency": "EUR",
            "payer_id": same_id,
            "payee_id": same_id,
        }
        response = await client.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_settlement_invalid_amount(
        self,
        client: AsyncClient,
    ) -> None:
        """Negative amount returns 422."""
        payload = {
            "idempotency_key": str(uuid.uuid4()),
            "amount": "-100.00",
            "currency": "USD",
            "payer_id": str(uuid.uuid4()),
            "payee_id": str(uuid.uuid4()),
        }
        response = await client.post(
            "/api/v1/settlements",
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_settlement_unknown_field_rejected(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Unknown fields in request body are rejected (OWASP A03 mass assignment)."""
        valid_settlement_payload["__proto__"] = "malicious"
        valid_settlement_payload["is_admin"] = True

        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422

class TestSettlementRetrieval:

    @pytest.mark.asyncio
    async def test_list_settlements_empty(self, client: AsyncClient) -> None:

        response = await client.get("/api/v1/settlements")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_get_settlement_not_found(self, client: AsyncClient) -> None:

        response = await client.get(f"/api/v1/settlements/{uuid.uuid4()}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_settlement_found(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Create a settlement then retrieve it by ID — returns the same record."""
        idempotency_key = valid_settlement_payload["idempotency_key"]
        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        assert create_resp.status_code == 201
        settlement_id = create_resp.json()["id"]

        get_resp = await client.get(f"/api/v1/settlements/{settlement_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == settlement_id

    @pytest.mark.asyncio
    async def test_list_settlements_with_status_filter(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Settlements created as PENDING appear when filtering by status=PENDING."""
        await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        response = await client.get("/api/v1/settlements?status=PENDING")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert all(item["status"] == "PENDING" for item in data["items"])

    @pytest.mark.asyncio
    async def test_list_settlements_invalid_status_returns_422(self, client: AsyncClient) -> None:

        response = await client.get("/api/v1/settlements?status=BOGUS")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_list_settlements_pagination(
        self,
        client: AsyncClient,
    ) -> None:
        """page_size=1 limits the items list to at most 1 record."""
        response = await client.get("/api/v1/settlements?page=1&page_size=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 1
        assert data["page_size"] == 1

class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient) -> None:

        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "settlement-service"

class TestSettlementReversal:

    @pytest.mark.asyncio
    async def test_reverse_nonexistent_returns_404(self, client: AsyncClient) -> None:

        response = await client.patch(
            f"/api/v1/settlements/{uuid.uuid4()}/reverse",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_reverse_pending_settlement_returns_409(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Reversing a PENDING settlement returns 409 Conflict (invalid transition)."""
        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = create_resp.json()["id"]

        reverse_resp = await client.patch(
            f"/api/v1/settlements/{settlement_id}/reverse",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert reverse_resp.status_code == 409

    @pytest.mark.asyncio
    async def test_reverse_completed_settlement_success(
        self,
        client: AsyncClient,
        db_session,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Reversing a COMPLETED settlement returns 200 with REVERSED status."""
        from app.models.settlement import Settlement, SettlementStatus
        from sqlalchemy import select as sa_select

        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = uuid.UUID(create_resp.json()["id"])

        result = await db_session.execute(
            sa_select(Settlement).where(Settlement.id == settlement_id)
        )
        settlement_obj = result.scalar_one()
        settlement_obj.status = SettlementStatus.COMPLETED
        settlement_obj.version = 2
        await db_session.flush()

        reverse_resp = await client.patch(
            f"/api/v1/settlements/{settlement_id}/reverse",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert reverse_resp.status_code == 200
        assert reverse_resp.json()["status"] == "REVERSED"

    @pytest.mark.asyncio
    async def test_reverse_completed_settlement_idempotent(
        self,
        client: AsyncClient,
        db_session,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Calling reverse twice with the same Idempotency-Key returns 200 both times."""
        from app.models.settlement import Settlement, SettlementStatus
        from sqlalchemy import select as sa_select

        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = uuid.UUID(create_resp.json()["id"])

        result = await db_session.execute(
            sa_select(Settlement).where(Settlement.id == settlement_id)
        )
        settlement_obj = result.scalar_one()
        settlement_obj.status = SettlementStatus.COMPLETED
        settlement_obj.version = 2
        await db_session.flush()

        reversal_key = str(uuid.uuid4())
        resp1 = await client.patch(
            f"/api/v1/settlements/{settlement_id}/reverse",
            headers={"Idempotency-Key": reversal_key},
        )
        resp2 = await client.patch(
            f"/api/v1/settlements/{settlement_id}/reverse",
            headers={"Idempotency-Key": reversal_key},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["id"] == resp2.json()["id"]
        assert resp2.json()["status"] == "REVERSED"

class TestSettlementCancellation:

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_404(self, client: AsyncClient) -> None:

        response = await client.patch(
            f"/api/v1/settlements/{uuid.uuid4()}/cancel",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_pending_settlement_success(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Cancelling a PENDING settlement returns 200 with CANCELLED status."""
        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = create_resp.json()["id"]

        cancel_resp = await client.patch(
            f"/api/v1/settlements/{settlement_id}/cancel",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_cancel_completed_settlement_returns_409(
        self,
        client: AsyncClient,
        db_session,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Cancelling a COMPLETED settlement returns 409 Conflict."""
        from app.models.settlement import Settlement, SettlementStatus
        from sqlalchemy import select as sa_select

        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = uuid.UUID(create_resp.json()["id"])

        result = await db_session.execute(
            sa_select(Settlement).where(Settlement.id == settlement_id)
        )
        settlement_obj = result.scalar_one()
        settlement_obj.status = SettlementStatus.COMPLETED
        settlement_obj.version = 2
        await db_session.flush()

        cancel_resp = await client.patch(
            f"/api/v1/settlements/{settlement_id}/cancel",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert cancel_resp.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_idempotent(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Cancelling an already-CANCELLED settlement returns 200 (idempotent)."""
        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = create_resp.json()["id"]

        cancel_key = str(uuid.uuid4())
        resp1 = await client.patch(
            f"/api/v1/settlements/{settlement_id}/cancel",
            headers={"Idempotency-Key": cancel_key},
        )
        resp2 = await client.patch(
            f"/api/v1/settlements/{settlement_id}/cancel",
            headers={"Idempotency-Key": cancel_key},
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["id"] == resp2.json()["id"]
        assert resp2.json()["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_cancel_missing_idempotency_key_returns_422(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Missing Idempotency-Key header on cancel returns 422."""
        create_resp = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert create_resp.status_code == 201
        settlement_id = create_resp.json()["id"]

        cancel_resp = await client.patch(
            f"/api/v1/settlements/{settlement_id}/cancel",
        )
        assert cancel_resp.status_code == 422

class TestKafkaPublish:

    @pytest.mark.asyncio
    async def test_kafka_publish_called_on_create(
        self,
        client: AsyncClient,
        mock_kafka: KafkaProducer,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Creating a settlement triggers a Kafka publish call."""
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert response.status_code == 201
        mock_kafka.publish.assert_called_once()
        call_kwargs = mock_kafka.publish.call_args
        assert call_kwargs.kwargs["topic"] == "nexus.settlements"
        assert call_kwargs.kwargs["event_type"] == "settlement.created"

    @pytest.mark.asyncio
    async def test_kafka_not_called_on_validation_error(
        self,
        client: AsyncClient,
        mock_kafka: KafkaProducer,
    ) -> None:
        """A rejected (422) request must never trigger a Kafka publish."""
        same_id = str(uuid.uuid4())
        await client.post(
            "/api/v1/settlements",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "amount": "-1",
                "currency": "USD",
                "payer_id": same_id,
                "payee_id": same_id,
            },
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        mock_kafka.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_fraud_block_rejects_settlement(
        self,
        client: AsyncClient,
        mock_kafka: KafkaProducer,
        mock_fraud,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """A BLOCK decision from the fraud service returns 422 and never persists."""
        from unittest.mock import AsyncMock
        mock_fraud.score = AsyncMock(return_value={
            "risk_score": 0.95,
            "decision": "BLOCK",
            "model_version": "test",
            "scored_at": "2026-01-01T00:00:00Z",
        })
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert response.status_code == 422
        assert "fraud" in response.json()["detail"].lower()
        mock_kafka.publish.assert_not_called()

class TestIdempotencyKeyValidation:

    @pytest.mark.asyncio
    async def test_idempotency_key_header_body_mismatch_returns_422(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Idempotency-Key header that differs from body idempotency_key returns 422."""
        valid_settlement_payload["idempotency_key"] = str(uuid.uuid4())
        different_key = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": different_key},
        )
        assert response.status_code == 422
        assert "idempotency" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_matching_idempotency_keys_accepted(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """When header and body idempotency_key match the request proceeds normally."""
        key = str(uuid.uuid4())
        valid_settlement_payload["idempotency_key"] = key
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 201

class TestWebhookUrlValidation:

    @pytest.mark.asyncio
    async def test_webhook_url_http_rejected(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """webhook_url with HTTP scheme is rejected (SSRF prevention)."""
        valid_settlement_payload["webhook_url"] = "http://partner.example.com/hook"
        valid_settlement_payload["idempotency_key"] = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_webhook_url_private_ip_rejected(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """webhook_url targeting RFC-1918 address is rejected (SSRF)."""
        valid_settlement_payload["webhook_url"] = "https://192.168.1.100/hook"
        valid_settlement_payload["idempotency_key"] = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_webhook_url_localhost_rejected(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """webhook_url targeting localhost is rejected (SSRF)."""
        valid_settlement_payload["webhook_url"] = "https://localhost/hook"
        valid_settlement_payload["idempotency_key"] = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_webhook_url_link_local_rejected(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """webhook_url targeting 169.254.x.x (AWS metadata endpoint) is rejected (SSRF)."""
        valid_settlement_payload["webhook_url"] = "https://169.254.169.254/latest/meta-data"
        valid_settlement_payload["idempotency_key"] = str(uuid.uuid4())
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": valid_settlement_payload["idempotency_key"]},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_webhook_url_public_https_accepted(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Valid public HTTPS webhook_url is accepted and settlement is created."""
        key = str(uuid.uuid4())
        valid_settlement_payload["webhook_url"] = "https://partner.example.com/hook"
        valid_settlement_payload["idempotency_key"] = key
        response = await client.post(
            "/api/v1/settlements",
            json=valid_settlement_payload,
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 201
