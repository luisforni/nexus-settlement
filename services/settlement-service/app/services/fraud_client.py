import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

class FraudScoreResponse(BaseModel):

    model_config = {"extra": "ignore"}

    risk_score: float
    decision: str
    model_version: str
    scored_at: Optional[str] = None

class FraudClient:

    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def score(
        self,
        *,
        settlement_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        payer_id: uuid.UUID,
        payee_id: uuid.UUID,
        timestamp: datetime | None = None,
        request_id: str | None = None,
    ) -> dict:
        """Call the fraud-detection /score endpoint.

        Args:
            settlement_id: Prospective settlement UUID (pre-generated).
            amount: Transaction amount.
            currency: ISO 4217 currency code.
            payer_id: Payer UUID.
            payee_id: Payee UUID.
            timestamp: Optional transaction timestamp; defaults to now in the service.

        Returns:
            Dict with at least ``risk_score`` (float) and ``decision`` (str).

        Raises:
            HTTPException 503: On any network error or timeout (fail-closed).
        """
        payload: dict = {
            "settlement_id": str(settlement_id),
            "amount": str(amount),
            "currency": currency,
            "payer_id": str(payer_id),
            "payee_id": str(payee_id),
        }
        if timestamp is not None:
            payload["timestamp"] = timestamp.isoformat()

        try:
            extra_headers = {"X-Request-Id": request_id} if request_id else {}
            response = await self._client.post(
                "/api/v1/fraud/score",
                json=payload,
                headers=extra_headers,
            )
            response.raise_for_status()
            try:
                return FraudScoreResponse(**response.json()).model_dump()
            except Exception as exc:
                logger.error(
                    "Fraud service returned unexpected response schema",
                    extra={"settlement_id": str(settlement_id), "error": str(exc)},
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Fraud detection service returned an invalid response.",
                )
        except httpx.TimeoutException:
            logger.error(
                "Fraud service timed out",
                extra={"settlement_id": str(settlement_id), "timeout": self._timeout},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Fraud detection service timed out — please retry.",
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Fraud service returned an error response",
                extra={
                    "settlement_id": str(settlement_id),
                    "http_status": exc.response.status_code,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Fraud detection service is unavailable.",
            )
        except httpx.ConnectError:
            logger.error(
                "Fraud service unreachable",
                extra={"settlement_id": str(settlement_id), "url": self._base_url},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Fraud detection service is unreachable.",
            )

fraud_client = FraudClient(
    base_url=settings.FRAUD_DETECTION_URL,
    timeout=settings.FRAUD_CHECK_TIMEOUT_SECONDS,
)
