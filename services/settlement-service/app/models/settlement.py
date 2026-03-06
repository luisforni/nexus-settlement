import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

class SettlementStatus(str, enum.Enum):

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"

VALID_TRANSITIONS: dict[SettlementStatus, set[SettlementStatus]] = {
    SettlementStatus.PENDING: {SettlementStatus.PROCESSING, SettlementStatus.CANCELLED},
    SettlementStatus.PROCESSING: {
        SettlementStatus.COMPLETED,
        SettlementStatus.FAILED,
        SettlementStatus.CANCELLED,
    },
    SettlementStatus.COMPLETED: {SettlementStatus.REVERSED},
    SettlementStatus.FAILED: {SettlementStatus.CANCELLED},
    SettlementStatus.REVERSED: set(),
    SettlementStatus.CANCELLED: set(),
}

class Settlement(Base):

    __tablename__ = "settlements"

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_settlements_idempotency_key"),
        CheckConstraint("amount > 0", name="ck_settlements_amount_positive"),
        CheckConstraint(
            "length(currency) = 3",
            name="ck_settlements_currency_iso4217",
        ),

        Index(
            "ix_settlements_status_created",
            "status",
            "created_at",
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_settlements_payer_id", "payer_id"),
        Index("ix_settlements_payee_id", "payee_id"),
        {"schema": None},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Settlement record identifier (UUID v4)",
    )

    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Client-supplied idempotency key; prevents duplicate processing",
    )

    status: Mapped[SettlementStatus] = mapped_column(
        Enum(SettlementStatus, name="settlement_status"),
        nullable=False,
        default=SettlementStatus.PENDING,
        comment="Current state in the settlement state machine",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=20, scale=4),
        nullable=False,
        comment="Transaction amount (supports up to 16 integer digits, 4 decimal places)",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO 4217 currency code (e.g. USD, EUR)",
    )

    payer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Identifier of the paying party (from identity service)",
    )
    payee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Identifier of the receiving party (from identity service)",
    )

    risk_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=4, scale=3),
        nullable=True,
        comment="Fraud risk score [0.000, 1.000] set by fraud-detection service",
    )

    failure_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable failure reason (populated on FAILED status)",
    )

    user_email: Mapped[Optional[str]] = mapped_column(
        String(320),
        nullable=True,
        comment="User email address for settlement notification delivery",
    )
    user_phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="User phone number in E.164 format for SMS notification delivery",
    )
    webhook_url: Mapped[Optional[str]] = mapped_column(
        String(2048),
        nullable=True,
        comment="HTTPS webhook URL for settlement event delivery",
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        comment="Optimistic locking counter; incremented on every update",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Record creation timestamp (UTC)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Record last-modification timestamp (UTC)",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft-delete timestamp; NULL = record is active",
    )

    def can_transition_to(self, new_status: SettlementStatus) -> bool:

        return new_status in VALID_TRANSITIONS.get(self.status, set())

    def __repr__(self) -> str:
        return (
            f"<Settlement id={self.id} status={self.status} "
            f"amount={self.amount} {self.currency}>"
        )
