import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_db
from app.messaging.kafka_producer import kafka_producer
from app.models.settlement import SettlementStatus
from app.schemas.settlement import (
    CreateSettlementRequest,
    SettlementListResponse,
    SettlementResponse,
)
from app.services.fraud_client import fraud_client
from app.services.settlement_service import SettlementService

logger = get_logger(__name__)

router = APIRouter(prefix="/settlements", tags=["Settlements"])

def get_settlement_service(
    db: AsyncSession = Depends(get_db),
) -> SettlementService:
    """FastAPI dependency that constructs the SettlementService."""
    return SettlementService(db=db, kafka=kafka_producer, fraud=fraud_client)

@router.get(
    "",
    response_model=SettlementListResponse,
    summary="List settlements (paginated)",
    status_code=status.HTTP_200_OK,
)
async def list_settlements(
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=20, ge=1, le=100),
    status_filter: Optional[SettlementStatus] = Query(
        default=None, alias="status"
    ),
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementListResponse:
    """Return a paginated list of settlements.

    Supports filtering by ``status``.
    """
    return await service.list_settlements(
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )

@router.get(
    "/{settlement_id}",
    response_model=SettlementResponse,
    summary="Get a settlement by ID",
    status_code=status.HTTP_200_OK,
)
async def get_settlement(
    settlement_id: uuid.UUID,
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Retrieve a single settlement by its UUID."""
    return await service.get_settlement(settlement_id)

@router.post(
    "",
    response_model=SettlementResponse,
    summary="Create a settlement",
    status_code=status.HTTP_201_CREATED,
)
async def create_settlement(
    request: CreateSettlementRequest,
    idempotency_key: uuid.UUID = Header(
        ...,
        alias="Idempotency-Key",
        description="Client-generated UUID v4 for idempotency. Required.",
    ),
    x_user_id: uuid.UUID = Header(
        ...,
        alias="X-User-Id",
        description="Authenticated user ID injected by the API gateway from the verified JWT sub claim.",
    ),
    x_request_id: Optional[str] = Header(
        default=None,
        alias="X-Request-Id",
        description="Distributed trace correlation ID.",
    ),
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Create a new settlement.

    The ``Idempotency-Key`` header (UUID v4) is required.
    Submitting the same key multiple times returns the original response
    without creating a duplicate settlement.
    """
    if request.idempotency_key != idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header must match idempotency_key in the request body.",
        )

    return await service.create_settlement(
        request=request,
        requesting_user_id=x_user_id,
        request_id=x_request_id,
    )

@router.patch(
    "/{settlement_id}/cancel",
    response_model=SettlementResponse,
    summary="Cancel a pending or processing settlement",
    status_code=status.HTTP_200_OK,
)
async def cancel_settlement(
    settlement_id: uuid.UUID,
    idempotency_key: uuid.UUID = Header(
        ...,
        alias="Idempotency-Key",
    ),
    x_user_id: uuid.UUID = Header(
        ...,
        alias="X-User-Id",
        description="Authenticated user ID injected by the API gateway from the verified JWT sub claim.",
    ),
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Cancel a PENDING or PROCESSING settlement.

    Returns 409 Conflict for invalid state transitions.
    """
    return await service.cancel_settlement(
        settlement_id=settlement_id,
        requesting_user_id=x_user_id,
        idempotency_key=idempotency_key,
    )

@router.patch(
    "/{settlement_id}/reverse",
    response_model=SettlementResponse,
    summary="Reverse a completed settlement",
    status_code=status.HTTP_200_OK,
)
async def reverse_settlement(
    settlement_id: uuid.UUID,
    idempotency_key: uuid.UUID = Header(
        ...,
        alias="Idempotency-Key",
    ),
    x_user_id: uuid.UUID = Header(
        ...,
        alias="X-User-Id",
        description="Authenticated user ID injected by the API gateway from the verified JWT sub claim.",
    ),
    service: SettlementService = Depends(get_settlement_service),
) -> SettlementResponse:
    """Reverse a COMPLETED settlement.

    Only COMPLETED settlements can be reversed.
    Returns 409 Conflict for invalid state transitions.
    """
    return await service.reverse_settlement(
        settlement_id=settlement_id,
        requesting_user_id=x_user_id,
        idempotency_key=idempotency_key,
    )
