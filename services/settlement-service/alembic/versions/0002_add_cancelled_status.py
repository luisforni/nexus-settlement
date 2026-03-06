from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:

    op.execute("COMMIT")
    op.execute("ALTER TYPE settlement_status ADD VALUE IF NOT EXISTS 'CANCELLED'")

def downgrade() -> None:

    op.execute("COMMIT")
    op.execute(
        """
        ALTER TABLE settlements
            ALTER COLUMN status TYPE VARCHAR(20);
        """
    )

    op.execute(
        """
        UPDATE settlements SET status = 'FAILED' WHERE status = 'CANCELLED';
        """
    )
    op.execute("DROP TYPE settlement_status")
    op.execute(
        """
        CREATE TYPE settlement_status AS ENUM (
            'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'REVERSED'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE settlements
            ALTER COLUMN status TYPE settlement_status
                USING status::settlement_status;
        """
    )
