import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.settlement import Settlement, SettlementStatus
from app.schemas.settlement import (
    CreateSettlementRequest,
    SettlementListResponse,
    SettlementResponse,
)
from app.messaging.kafka_producer import KafkaProducer
from app.services.fraud_client import FraudClient

logger = get_logger(__name__)

class SettlementService:

    def __init__(self, db: AsyncSession, kafka: KafkaProducer, fraud: FraudClient) -> None:
        self._db = db
        self._kafka = kafka
        self._fraud = fraud

    async def create_settlement(
        self,
        request: CreateSettlementRequest,
        requesting_user_id: uuid.UUID,
        request_id: str | None = None,
    ) -> SettlementResponse:
        """Create a new settlement, or return the existing one if idempotent retry.

        Args:
            request: Validated settlement creation request.
            requesting_user_id: ID of the authenticated user making the request.

        Returns:
            The created (or existing) settlement.

        Raises:
            HTTPException 422: If payer_id == payee_id (self-transaction).
            HTTPException 503: If fraud check service is unreachable.
        """

        if request.payer_id == request.payee_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="payer_id and payee_id must be different",
            )

        existing = await self._get_by_idempotency_key(request.idempotency_key)
        if existing is not None:
            logger.info(
                "Idempotent settlement request — returning existing record",
                extra={"idempotency_key": str(request.idempotency_key)},
            )
            return SettlementResponse.model_validate(existing)

        settlement_id = uuid.uuid4()

        score_result = await self._fraud.score(
            settlement_id=settlement_id,
            amount=request.amount,
            currency=request.currency,
            payer_id=request.payer_id,
            payee_id=request.payee_id,
            request_id=request_id,
        )

        if score_result["decision"] == "BLOCK":
            logger.warning(
                "Settlement blocked by fraud gate",
                extra={
                    "settlement_id": str(settlement_id),
                    "risk_score": score_result["risk_score"],
                },
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Transaction blocked by fraud detection.",
            )

        settlement = Settlement(
            id=settlement_id,
            idempotency_key=request.idempotency_key,
            amount=request.amount,
            currency=request.currency,
            payer_id=request.payer_id,
            payee_id=request.payee_id,
            status=SettlementStatus.PENDING,
            risk_score=score_result["risk_score"],
            user_email=request.user_email,
            user_phone=request.user_phone,
            webhook_url=str(request.webhook_url) if request.webhook_url else None,
        )

        try:
            self._db.add(settlement)
            await self._db.flush()
            await self._db.refresh(settlement)
        except IntegrityError:
            await self._db.rollback()

            existing = await self._get_by_idempotency_key(request.idempotency_key)
            if existing:
                return SettlementResponse.model_validate(existing)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate idempotency_key",
            )

        await self._kafka.publish(
            topic="nexus.settlements",
            event_type="settlement.created",
            key=str(settlement.id),
            payload={
                "settlement_id": str(settlement.id),
                "status": settlement.status.value,
                "idempotency_key": str(settlement.idempotency_key),
                "amount": str(settlement.amount),
                "currency": settlement.currency,
                "payer_id": str(settlement.payer_id),
                "payee_id": str(settlement.payee_id),
                "requesting_user_id": str(requesting_user_id),
                "user_email": request.user_email,
                "user_phone": request.user_phone,
                "webhook_url": request.webhook_url,
            },
        )

        logger.info(
            "Settlement created",
            extra={
                "settlement_id": str(settlement.id),
                "amount": str(settlement.amount),
                "currency": settlement.currency,
            },
        )

        return SettlementResponse.model_validate(settlement)

    async def get_settlement(self, settlement_id: uuid.UUID) -> SettlementResponse:

        settlement = await self._get_or_404(settlement_id)
        return SettlementResponse.model_validate(settlement)

    async def list_settlements(
        self,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[SettlementStatus] = None,
    ) -> SettlementListResponse:
        """Return a paginated list of settlements.

        Args:
            page: 1-indexed page number.
            page_size: Records per page (max 100).
            status_filter: Optional status to filter by.
        """
        if page_size > 100:
            page_size = 100

        stmt = select(Settlement).where(Settlement.deleted_at.is_(None))

        if status_filter is not None:
            stmt = stmt.where(Settlement.status == status_filter)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self._db.execute(count_stmt)
        total: int = total_result.scalar_one()

        stmt = (
            stmt.order_by(Settlement.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        result = await self._db.execute(stmt)
        records = result.scalars().all()

        return SettlementListResponse(
            items=[SettlementResponse.model_validate(r) for r in records],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def reverse_settlement(
        self,
        settlement_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        idempotency_key: uuid.UUID,
    ) -> SettlementResponse:
        """Reverse a completed settlement.

        Only COMPLETED settlements can be reversed.
        Uses SELECT … FOR UPDATE to prevent concurrent reversals.
        Idempotency: if the settlement is already REVERSED, return it as-is.

        Raises:
            HTTPException 404: Settlement not found.
            HTTPException 409: Invalid state transition.
        """
        stmt = (
            select(Settlement)
            .where(
                Settlement.id == settlement_id,
                Settlement.deleted_at.is_(None),
            )
            .with_for_update()
        )
        result = await self._db.execute(stmt)
        settlement = result.scalar_one_or_none()
        if settlement is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Settlement {settlement_id} not found",
            )

        if settlement.status == SettlementStatus.REVERSED:
            await self._db.refresh(settlement)
            return SettlementResponse.model_validate(settlement)

        if not settlement.can_transition_to(SettlementStatus.REVERSED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot reverse settlement in status {settlement.status.value}. "
                    "Only COMPLETED settlements can be reversed."
                ),
            )

        settlement.status = SettlementStatus.REVERSED
        settlement.version += 1
        await self._db.flush()
        await self._db.refresh(settlement)

        await self._kafka.publish(
            topic="nexus.settlements",
            event_type="settlement.reversed",
            key=str(settlement_id),
            payload={
                "settlement_id": str(settlement_id),
                "status": settlement.status.value,
                "amount": str(settlement.amount),
                "currency": settlement.currency,
                "payer_id": str(settlement.payer_id),
                "payee_id": str(settlement.payee_id),
                "requesting_user_id": str(requesting_user_id),
                **({
                    "user_email": settlement.user_email
                } if settlement.user_email else {}),
                **({
                    "user_phone": settlement.user_phone
                } if settlement.user_phone else {}),
                **({
                    "webhook_url": settlement.webhook_url
                } if settlement.webhook_url else {}),
            },
        )

        logger.info(
            "Settlement reversed",
            extra={"settlement_id": str(settlement_id)},
        )

        return SettlementResponse.model_validate(settlement)

    async def cancel_settlement(
        self,
        settlement_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        idempotency_key: uuid.UUID,
    ) -> SettlementResponse:
        """Cancel a PENDING or PROCESSING settlement.

        Uses SELECT … FOR UPDATE to prevent concurrent state transitions.
        Idempotency: if already CANCELLED, returns the record as-is.

        Raises:
            HTTPException 404: Settlement not found.
            HTTPException 409: Invalid state transition.
        """
        stmt = (
            select(Settlement)
            .where(
                Settlement.id == settlement_id,
                Settlement.deleted_at.is_(None),
            )
            .with_for_update()
        )
        result = await self._db.execute(stmt)
        settlement = result.scalar_one_or_none()
        if settlement is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Settlement {settlement_id} not found",
            )

        if settlement.status == SettlementStatus.CANCELLED:
            await self._db.refresh(settlement)
            return SettlementResponse.model_validate(settlement)

        if not settlement.can_transition_to(SettlementStatus.CANCELLED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot cancel settlement in status {settlement.status.value}. "
                    "Only PENDING, PROCESSING, or FAILED settlements can be cancelled."
                ),
            )

        settlement.status = SettlementStatus.CANCELLED
        settlement.version += 1
        await self._db.flush()
        await self._db.refresh(settlement)

        await self._kafka.publish(
            topic="nexus.settlements",
            event_type="settlement.cancelled",
            key=str(settlement_id),
            payload={
                "settlement_id": str(settlement_id),
                "status": settlement.status.value,
                "amount": str(settlement.amount),
                "currency": settlement.currency,
                "payer_id": str(settlement.payer_id),
                "payee_id": str(settlement.payee_id),
                "requesting_user_id": str(requesting_user_id),
                **({
                    "user_email": settlement.user_email
                } if settlement.user_email else {}),
                **({
                    "user_phone": settlement.user_phone
                } if settlement.user_phone else {}),
                **({
                    "webhook_url": settlement.webhook_url
                } if settlement.webhook_url else {}),
            },
        )

        logger.info(
            "Settlement cancelled",
            extra={"settlement_id": str(settlement_id)},
        )

        return SettlementResponse.model_validate(settlement)

    async def _get_or_404(self, settlement_id: uuid.UUID) -> Settlement:

        stmt = select(Settlement).where(
            Settlement.id == settlement_id,
            Settlement.deleted_at.is_(None),
        )
        result = await self._db.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Settlement {settlement_id} not found",
            )
        return record

    async def _get_by_idempotency_key(
        self,
        idempotency_key: uuid.UUID,
    ) -> Optional[Settlement]:
        """Return a settlement matching the idempotency key, or None."""
        stmt = select(Settlement).where(
            Settlement.idempotency_key == idempotency_key,
            Settlement.deleted_at.is_(None),
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()
