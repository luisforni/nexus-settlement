import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.core.config import settings
from app.core.logging import get_logger
from app.models.feature_engineering import RawTransactionData, engineer_features
from app.models.fraud_detector import FraudDetector, FraudExplanation

logger = get_logger(__name__)

class FraudService:

    def __init__(self, detector: FraudDetector) -> None:
        self._detector = detector

    async def score_transaction(
        self,
        settlement_id: str,
        amount: Decimal,
        currency: str,
        payer_id: str,
        payee_id: str,
        timestamp: datetime | None = None,
    ) -> dict:
        """Score a transaction and return risk assessment.

        Args:
            settlement_id: Unique settlement identifier.
            amount: Transaction amount.
            currency: ISO 4217 currency code.
            payer_id: Payer UUID string.
            payee_id: Payee UUID string.
            timestamp: Transaction timestamp (defaults to now).

        Returns:
            dict with keys: settlement_id, risk_score, decision, scored_at.
        """
        ts = timestamp or datetime.now(timezone.utc)

        raw = RawTransactionData(
            settlement_id=settlement_id,
            amount=amount,
            currency=currency,
            payer_id=payer_id,
            payee_id=payee_id,
            timestamp=ts,
        )

        feature_vector = engineer_features(raw)
        risk_score = self._detector.predict_risk_score(
            feature_vector, amount=float(amount)
        )
        decision = self._make_decision(risk_score)

        logger.info(
            "Transaction scored",
            extra={
                "settlement_id": settlement_id,
                "risk_score": risk_score,
                "decision": decision,
                "model_version": self._detector.version,
            },
        )

        return {
            "settlement_id": settlement_id,
            "risk_score": risk_score,
            "decision": decision,
            "model_version": self._detector.version,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }

    async def explain_transaction(
        self,
        settlement_id: str,
        amount: Decimal,
        currency: str,
        payer_id: str,
        payee_id: str,
    ) -> FraudExplanation:
        """Generate a SHAP explanation for the fraud score.

        Used for regulatory audits and customer-facing dispute resolution.
        """
        from app.models.feature_engineering import FEATURE_NAMES

        ts = datetime.now(timezone.utc)
        raw = RawTransactionData(
            settlement_id=settlement_id,
            amount=amount,
            currency=currency,
            payer_id=payer_id,
            payee_id=payee_id,
            timestamp=ts,
        )

        feature_vector = engineer_features(raw)
        explanation = self._detector.explain(
            settlement_id=settlement_id,
            feature_vector=feature_vector,
            feature_names=FEATURE_NAMES,
            amount=float(amount),
        )

        logger.info(
            "Explanation generated",
            extra={
                "settlement_id": settlement_id,
                "risk_score": explanation.risk_score,
                "decision": explanation.decision,
            },
        )

        return explanation

    def _make_decision(self, risk_score: float) -> str:

        threshold = settings.FRAUD_RISK_THRESHOLD
        if risk_score < 0.40:
            return "APPROVE"
        if risk_score < threshold:
            return "REVIEW"
        return "BLOCK"
