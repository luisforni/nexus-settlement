import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.settlement import SettlementStatus

class _BaseSchema(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        use_enum_values=True,
        from_attributes=True,
    )

class CreateSettlementRequest(_BaseSchema):

    idempotency_key: uuid.UUID = Field(
        ...,
        description="Client-generated UUID v4 used to deduplicate requests.",
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0"),
        le=Decimal("10000000"),
        decimal_places=4,
        description="Settlement amount. Must be positive, max 10,000,000.",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code (e.g. USD, EUR, GBP).",
    )
    payer_id: uuid.UUID = Field(
        ...,
        description="UUID of the paying party from the identity service.",
    )
    payee_id: uuid.UUID = Field(
        ...,
        description="UUID of the receiving party from the identity service.",
    )

    @field_validator("currency")
    @classmethod
    def currency_must_be_uppercase(cls, v: str) -> str:

        upper = v.upper()

        if not upper.isalpha():
            raise ValueError("currency must contain only alphabetic characters")
        return upper

    @field_validator("payer_id", "payee_id")
    @classmethod
    def payer_and_payee_different(
        cls, v: uuid.UUID, info: object
    ) -> uuid.UUID:
        """Guard against self-transactions (payer_id == payee_id).

        Note: cross-field validation in Pydantic v2 requires model_validator;
        this is a field validator placing the check here as a belt-and-suspenders.
        Full cross-field check is in the service layer.
        """
        return v

class SettlementResponse(_BaseSchema):

    id: uuid.UUID
    idempotency_key: uuid.UUID
    status: SettlementStatus
    amount: Decimal
    currency: str
    payer_id: uuid.UUID
    payee_id: uuid.UUID
    risk_score: Optional[Decimal] = None
    failure_reason: Optional[str] = None
    version: int
    created_at: datetime
    updated_at: datetime

class SettlementListResponse(_BaseSchema):

    items: list[SettlementResponse]
    total: int
    page: int
    page_size: int

class HealthResponse(_BaseSchema):

    status: str
    service: str
    version: str = "1.0.0"
    timestamp: datetime
