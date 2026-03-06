"""
Integration tests: fraud detection service.
"""
import uuid
import pytest
import httpx

pytestmark = pytest.mark.integration


class TestFraudScore:

    @pytest.mark.asyncio
    async def test_score_returns_expected_shape(self, fraud_svc: httpx.AsyncClient):
        r = await fraud_svc.post(
            "/api/v1/fraud/score",
            json={
                "settlement_id": str(uuid.uuid4()),
                "amount": "250.00",
                "currency": "EUR",
                "payer_id": str(uuid.uuid4()),
                "payee_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) >= {"settlement_id", "risk_score", "decision", "model_version", "scored_at"}
        assert body["decision"] in ("APPROVE", "REVIEW", "BLOCK")
        assert 0.0 <= body["risk_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_explain_returns_features(self, fraud_svc: httpx.AsyncClient):
        r = await fraud_svc.post(
            "/api/v1/fraud/explain",
            json={
                "settlement_id": str(uuid.uuid4()),
                "amount": "1500.00",
                "currency": "USD",
                "payer_id": str(uuid.uuid4()),
                "payee_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "top_features" in body
        assert isinstance(body["top_features"], list)

    @pytest.mark.asyncio
    async def test_model_info_endpoint(self, fraud_svc: httpx.AsyncClient):
        r = await fraud_svc.get("/api/v1/fraud/model/info")
        assert r.status_code == 200
        body = r.json()
        assert "version" in body
        assert "model_type" in body

    @pytest.mark.asyncio
    async def test_invalid_currency_rejected(self, fraud_svc: httpx.AsyncClient):
        r = await fraud_svc.post(
            "/api/v1/fraud/score",
            json={
                "settlement_id": str(uuid.uuid4()),
                "amount": "100.00",
                "currency": "INVALID",
                "payer_id": str(uuid.uuid4()),
                "payee_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_amount_rejected(self, fraud_svc: httpx.AsyncClient):
        r = await fraud_svc.post(
            "/api/v1/fraud/score",
            json={
                "settlement_id": str(uuid.uuid4()),
                "amount": "-50.00",
                "currency": "USD",
                "payer_id": str(uuid.uuid4()),
                "payee_id": str(uuid.uuid4()),
            },
        )
        assert r.status_code == 422
