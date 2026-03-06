import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.logging import get_logger
from app.services.fraud_service import FraudService

logger = get_logger(__name__)

class ScoreRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    settlement_id: uuid.UUID = Field(
        ...,
        description="UUID of the settlement to score.",
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        le=Decimal("10000000"),
        description="Settlement amount.",
    )
    currency: str = Field(..., min_length=3, max_length=3)
    payer_id: uuid.UUID = Field(...)
    payee_id: uuid.UUID = Field(...)
    timestamp: datetime | None = Field(
        default=None,
        description="Settlement timestamp (defaults to now if omitted).",
    )

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:

        return v.upper()

class ScoreResponse(BaseModel):

    model_config = ConfigDict(extra="forbid")

    settlement_id: str
    risk_score: float
    decision: str
    model_version: str
    scored_at: str

class ExplainFeature(BaseModel):

    name: str
    shap_value: float

class ExplainResponse(BaseModel):

    settlement_id: str
    risk_score: float
    decision: str
    top_features: list[ExplainFeature]

class ModelInfoResponse(BaseModel):

    version: str
    model_type: str
    auc_roc: float | None
    training_date: str | None
    feature_count: int

router = APIRouter(prefix="/fraud", tags=["Fraud Detection"])

def get_fraud_service() -> FraudService:

    from app.main import get_detector

    detector = get_detector()
    return FraudService(detector=detector)

@router.post(
    "/score",
    response_model=ScoreResponse,
    summary="Score a transaction for fraud risk",
    status_code=status.HTTP_200_OK,
)
async def score_transaction(
    request: ScoreRequest,
    service: FraudService = Depends(get_fraud_service),
) -> ScoreResponse:
    """Score a settlement for fraud risk.

    Returns a risk score [0.0, 1.0] and a decision:
      - ``APPROVE`` — score < 0.40
      - ``REVIEW``  — 0.40 ≤ score < threshold
      - ``BLOCK``   — score ≥ threshold (configurable via FRAUD_RISK_THRESHOLD)
    """
    result = await service.score_transaction(
        settlement_id=str(request.settlement_id),
        amount=request.amount,
        currency=request.currency,
        payer_id=str(request.payer_id),
        payee_id=str(request.payee_id),
        timestamp=request.timestamp,
    )
    return ScoreResponse(**result)

@router.get(
    "/explain/{settlement_id}",
    response_model=ExplainResponse,
    summary="Get SHAP explanation for a settlement score",
    status_code=status.HTTP_200_OK,
)
async def explain_score(
    settlement_id: uuid.UUID,
    amount: Decimal = Decimal("1000"),
    currency: str = "USD",
    payer_id: Optional[uuid.UUID] = None,
    payee_id: Optional[uuid.UUID] = None,
    service: FraudService = Depends(get_fraud_service),
) -> ExplainResponse:
    """Return SHAP feature importance for a fraud decision.

    Used for regulatory audit trails and dispute resolution.
    """
    pid = payer_id or uuid.uuid4()
    ppid = payee_id or uuid.uuid4()

    explanation = await service.explain_transaction(
        settlement_id=str(settlement_id),
        amount=amount,
        currency=currency.upper(),
        payer_id=str(pid),
        payee_id=str(ppid),
    )
    return ExplainResponse(
        settlement_id=explanation.settlement_id,
        risk_score=explanation.risk_score,
        decision=explanation.decision,
        top_features=[
            ExplainFeature(name=name, shap_value=val)
            for name, val in explanation.top_features
        ],
    )

@router.get(
    "/model-info",
    response_model=ModelInfoResponse,
    summary="Get loaded model metadata",
    status_code=status.HTTP_200_OK,
)
async def model_info(
    service: FraudService = Depends(get_fraud_service),
) -> ModelInfoResponse:
    """Return metadata about the currently loaded fraud model."""
    detector = service._detector
    meta = detector.metadata
    return ModelInfoResponse(
        version=meta.version,
        model_type=meta.model_type,
        auc_roc=meta.auc_roc,
        training_date=meta.training_date,
        feature_count=len(meta.feature_names),
    )

@router.get(
    "/health",
    summary="Health check",
    include_in_schema=False,
    status_code=status.HTTP_200_OK,
)
async def health() -> dict:

    return {
        "status": "ok",
        "service": "fraud-detection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
