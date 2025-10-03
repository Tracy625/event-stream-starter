"""outbox_push

Revision ID: 013
Revises: 012
Create Date: 2025-09-13

Add push_outbox and push_outbox_dlq tables for Telegram push retry
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create push_outbox table
    op.create_table(
        "push_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("thread_id", sa.BigInteger(), nullable=True),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("payload_json", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_try_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','retry','done','dlq')", name="ck_push_outbox_status"
        ),
    )

    # Create indexes
    op.create_index(
        "ix_push_outbox_status_next_try_at", "push_outbox", ["status", "next_try_at"]
    )
    op.create_index("ix_push_outbox_event_key", "push_outbox", ["event_key"])
    op.create_index("ix_push_outbox_channel_id", "push_outbox", ["channel_id"])

    # Create push_outbox_dlq table
    op.create_table(
        "push_outbox_dlq",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", pg.JSONB(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    # Drop tables
    op.drop_table("push_outbox_dlq")

    # Drop indexes
    op.drop_index("ix_push_outbox_channel_id", table_name="push_outbox")
    op.drop_index("ix_push_outbox_event_key", table_name="push_outbox")
    op.drop_index("ix_push_outbox_status_next_try_at", table_name="push_outbox")

    op.drop_table("push_outbox")
