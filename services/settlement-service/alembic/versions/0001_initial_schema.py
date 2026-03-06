from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:

    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "settlements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Settlement record identifier (UUID v4)",
        ),
        sa.Column(
            "idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Client-supplied idempotency key; prevents duplicate processing",
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                "REVERSED",
                name="settlement_status",
            ),
            nullable=False,
            comment="Current state in the settlement state machine",
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=20, scale=4),
            nullable=False,
            comment="Transaction amount (supports up to 16 integer digits, 4 decimal places)",
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            comment="ISO 4217 currency code (e.g. USD, EUR)",
        ),
        sa.Column(
            "payer_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Identifier of the paying party (from identity service)",
        ),
        sa.Column(
            "payee_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Identifier of the receiving party (from identity service)",
        ),
        sa.Column(
            "risk_score",
            sa.Numeric(precision=4, scale=3),
            nullable=True,
            comment="Fraud risk score [0.000, 1.000] set by fraud-detection service",
        ),
        sa.Column(
            "failure_reason",
            sa.Text(),
            nullable=True,
            comment="Human-readable failure reason (populated on FAILED status)",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Optimistic locking counter; incremented on every update",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Record creation timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Record last-modification timestamp (UTC)",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft-delete timestamp; NULL = record is active",
        ),

        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_settlements_idempotency_key"),
        sa.CheckConstraint("amount > 0", name="ck_settlements_amount_positive"),
        sa.CheckConstraint(
            "length(currency) = 3", name="ck_settlements_currency_iso4217"
        ),
    )

    op.create_index(
        "ix_settlements_idempotency_key",
        "settlements",
        ["idempotency_key"],
    )
    op.create_index(
        "ix_settlements_payer_id",
        "settlements",
        ["payer_id"],
    )
    op.create_index(
        "ix_settlements_payee_id",
        "settlements",
        ["payee_id"],
    )

    op.create_index(
        "ix_settlements_status_created",
        "settlements",
        ["status", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql'
    """)
    op.execute("""
        CREATE TRIGGER settlements_updated_at
        BEFORE UPDATE ON settlements
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column()
    """)

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS settlements_updated_at ON settlements")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
    op.drop_index("ix_settlements_status_created", table_name="settlements")
    op.drop_index("ix_settlements_payee_id", table_name="settlements")
    op.drop_index("ix_settlements_payer_id", table_name="settlements")
    op.drop_index("ix_settlements_idempotency_key", table_name="settlements")
    op.drop_table("settlements")
    sa.Enum(name="settlement_status").drop(op.get_bind(), checkfirst=True)
