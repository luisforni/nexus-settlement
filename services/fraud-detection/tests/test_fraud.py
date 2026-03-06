import uuid
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pytest
from httpx import AsyncClient

from app.models.feature_engineering import (
    FEATURE_NAMES,
    RawTransactionData,
    engineer_features,
)
from app.models.fraud_detector import FraudDetector

class TestFeatureEngineering:

    def _make_raw(
        self,
        amount: Decimal = Decimal("1000.00"),
        currency: str = "USD",
        hour: int = 14,
    ) -> RawTransactionData:
        ts = datetime(2026, 3, 5, hour, 0, 0, tzinfo=timezone.utc)
        return RawTransactionData(
            settlement_id=str(uuid.uuid4()),
            amount=amount,
            currency=currency.upper(),
            payer_id=str(uuid.uuid4()),
            payee_id=str(uuid.uuid4()),
            timestamp=ts,
        )

    def test_feature_vector_shape(self) -> None:

        raw = self._make_raw()
        vector = engineer_features(raw)
        assert vector.shape == (len(FEATURE_NAMES),), (
            f"Expected shape ({len(FEATURE_NAMES)},), got {vector.shape}"
        )

    def test_feature_vector_dtype(self) -> None:

        raw = self._make_raw()
        vector = engineer_features(raw)
        assert vector.dtype == np.float32

    def test_high_risk_currency_flag(self) -> None:

        raw = self._make_raw(currency="USD")
        vector = engineer_features(raw)
        idx = FEATURE_NAMES.index("is_high_risk_currency")
        assert vector[idx] == 1.0

    def test_round_amount_flag(self) -> None:

        raw = self._make_raw(amount=Decimal("1000.00"))
        vector = engineer_features(raw)
        idx = FEATURE_NAMES.index("is_round_amount")
        assert vector[idx] == 1.0

    def test_non_round_amount_flag(self) -> None:

        raw = self._make_raw(amount=Decimal("123.45"))
        vector = engineer_features(raw)
        idx = FEATURE_NAMES.index("is_round_amount")
        assert vector[idx] == 0.0

    def test_weekend_encoding(self) -> None:

        ts = datetime(2026, 3, 7, 12, 0, 0, tzinfo=timezone.utc)
        raw = RawTransactionData(
            settlement_id="test",
            amount=Decimal("500"),
            currency="EUR",
            payer_id="a",
            payee_id="b",
            timestamp=ts,
        )
        vector = engineer_features(raw)
        idx = FEATURE_NAMES.index("is_weekend")
        assert vector[idx] == 1.0

    def test_amount_log_transformation(self) -> None:

        import math

        raw = self._make_raw(amount=Decimal("1000.00"))
        vector = engineer_features(raw)
        idx = FEATURE_NAMES.index("amount_log")
        expected = math.log1p(1000.0)
        assert abs(float(vector[idx]) - expected) < 1e-4

class TestFraudDetector:

    def setup_method(self) -> None:
        self.detector = FraudDetector.untrained()

    def test_low_amount_low_risk(self) -> None:

        vector = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
        score = self.detector.predict_risk_score(vector, amount=100.0)
        assert 0.0 <= score <= 1.0
        assert score < 0.5

    def test_high_amount_higher_risk(self) -> None:

        vector = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
        score = self.detector.predict_risk_score(vector, amount=1_000_000.0)
        assert score > 0.5

    def test_score_in_range(self) -> None:

        vector = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
        for amount in [0, 100, 10_000, 1_000_000]:
            score = self.detector.predict_risk_score(vector, amount=float(amount))
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for amount {amount}"

    def test_decision_approve(self) -> None:

        vector = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
        explanation = self.detector.explain(
            settlement_id="test",
            feature_vector=vector,
            feature_names=FEATURE_NAMES,
            amount=100.0,
        )
        assert explanation.decision == "APPROVE"

    def test_decision_block(self) -> None:

        vector = np.zeros(len(FEATURE_NAMES), dtype=np.float32)
        explanation = self.detector.explain(
            settlement_id="test",
            feature_vector=vector,
            feature_names=FEATURE_NAMES,
            amount=1_000_000.0,
        )
        assert explanation.decision in {"REVIEW", "BLOCK"}

    def test_model_version(self) -> None:

        assert self.detector.version == "untrained-v0"

class TestFraudAPI:

    def _score_payload(
        self,
        amount: str = "1000.00",
        currency: str = "USD",
    ) -> dict:
        return {
            "settlement_id": str(uuid.uuid4()),
            "amount": amount,
            "currency": currency,
            "payer_id": str(uuid.uuid4()),
            "payee_id": str(uuid.uuid4()),
        }

    @pytest.mark.asyncio
    async def test_score_valid_request(self, client: AsyncClient) -> None:

        resp = await client.post("/api/v1/fraud/score", json=self._score_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_score" in data
        assert "decision" in data
        assert "model_version" in data
        assert 0.0 <= data["risk_score"] <= 1.0
        assert data["decision"] in {"APPROVE", "REVIEW", "BLOCK"}

    @pytest.mark.asyncio
    async def test_score_negative_amount_fails(self, client: AsyncClient) -> None:

        payload = self._score_payload(amount="-500.00")
        resp = await client.post("/api/v1/fraud/score", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_score_zero_amount_fails(self, client: AsyncClient) -> None:

        payload = self._score_payload(amount="0.00")
        resp = await client.post("/api/v1/fraud/score", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_score_unknown_field_rejected(self, client: AsyncClient) -> None:

        payload = self._score_payload()
        payload["__proto__"] = "malicious"
        resp = await client.post("/api/v1/fraud/score", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_score_high_amount_decision(self, client: AsyncClient) -> None:

        payload = self._score_payload(amount="5000000.00")
        resp = await client.post("/api/v1/fraud/score", json=payload)
        assert resp.status_code == 200
        assert resp.json()["decision"] in {"REVIEW", "BLOCK"}

    @pytest.mark.asyncio
    async def test_explain_endpoint(self, client: AsyncClient) -> None:

        settlement_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/fraud/explain/{settlement_id}?amount=1000&currency=USD")
        assert resp.status_code == 200
        data = resp.json()
        assert "risk_score" in data
        assert "decision" in data
        assert isinstance(data["top_features"], list)
        for feature in data["top_features"]:
            assert "name" in feature
            assert "shap_value" in feature

    @pytest.mark.asyncio
    async def test_model_info_endpoint(self, client: AsyncClient) -> None:

        resp = await client.get("/api/v1/fraud/model-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert "model_type" in data
        assert "feature_count" in data
        assert isinstance(data["feature_count"], int)
        assert data["feature_count"] > 0

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient) -> None:

        resp = await client.get("/api/v1/fraud/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
