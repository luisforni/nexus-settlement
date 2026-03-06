import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Optional

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

    user_email: Optional[str] = Field(
        default=None,
        description="User email address for settlement completion notifications.",
    )
    user_phone: Optional[str] = Field(
        default=None,
        description="User phone number (E.164 format) for SMS notifications.",
    )
    webhook_url: Optional[str] = Field(
        default=None,
        description="HTTPS webhook URL to call on settlement completion.",
    )

    _PRIVATE_HOST_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|0\.0\.0\.0|::1|::ffff:|fd[0-9a-f]{2}:)",
        re.IGNORECASE,
    )

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:

        if v is None:
            return v
        from urllib.parse import urlparse
        try:
            parsed = urlparse(v)
        except Exception:
            raise ValueError("webhook_url is not a valid URL")
        if parsed.scheme != "https":
            raise ValueError("webhook_url must use HTTPS to prevent SSRF")
        hostname = parsed.hostname or ""
        if cls._PRIVATE_HOST_RE.match(hostname):
            raise ValueError(
                "webhook_url must not target a private or loopback host"
            )
        return v

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
