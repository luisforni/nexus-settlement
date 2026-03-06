import uuid
from typing import Any

import pytest
from httpx import AsyncClient

class TestSettlementCreation:

    @pytest.mark.asyncio
    async def test_create_settlement_success(
        self,
        client: AsyncClient,
        valid_settlement_payload: dict[str, Any],
    ) -> None:
        """Happy path: valid payload returns 201 with settlement fields."""
        idempotency_key = str(uuid.uuid4())
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
        idempotency_key = str(uuid.uuid4())
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
            headers={"Idempotency-Key": str(uuid.uuid4())},
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
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert create_resp.status_code == 201
        settlement_id = create_resp.json()["id"]

        reverse_resp = await client.patch(
            f"/api/v1/settlements/{settlement_id}/reverse",
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert reverse_resp.status_code == 409

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
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 201
        mock_kafka.publish.assert_called_once()
        call_kwargs = mock_kafka.publish.call_args
        assert call_kwargs.kwargs["topic"] == "nexus.settlements"

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
