from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "settlements",
        sa.Column("user_email", sa.String(320), nullable=True,
                  comment="User email address for settlement notification delivery"),
    )
    op.add_column(
        "settlements",
        sa.Column("user_phone", sa.String(20), nullable=True,
                  comment="User phone number in E.164 format for SMS notification delivery"),
    )
    op.add_column(
        "settlements",
        sa.Column("webhook_url", sa.String(2048), nullable=True,
                  comment="HTTPS webhook URL for settlement event delivery"),
    )

def downgrade() -> None:
    op.drop_column("settlements", "webhook_url")
    op.drop_column("settlements", "user_phone")
    op.drop_column("settlements", "user_email")
