"""fix_onchain_confidence_type

Revision ID: 011
Revises: 010
Create Date: 2025-09-08

Fix onchain_confidence column type from Integer to NUMERIC(4,3)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text as sa_text

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if columns exist and add/modify as needed
    conn = op.get_bind()

    # Check if onchain_asof_ts exists
    result = conn.execute(
        sa_text(
            """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'signals' AND column_name = 'onchain_asof_ts'
    """
        )
    )

    if not result.fetchone():
        op.add_column(
            "signals",
            sa.Column("onchain_asof_ts", sa.TIMESTAMP(timezone=True), nullable=True),
        )

    # Check if onchain_confidence exists with wrong type
    result = conn.execute(
        sa_text(
            """
        SELECT data_type 
        FROM information_schema.columns 
        WHERE table_name = 'signals' AND column_name = 'onchain_confidence'
    """
        )
    )

    row = result.fetchone()
    if row:
        # Column exists, check if it's integer type
        if row[0].lower() in ["integer", "bigint", "smallint"]:
            # Drop and recreate with correct type
            op.drop_column("signals", "onchain_confidence")
            op.add_column(
                "signals",
                sa.Column(
                    "onchain_confidence",
                    sa.Numeric(precision=4, scale=3),
                    nullable=True,
                ),
            )
    else:
        # Column doesn't exist, add it
        op.add_column(
            "signals",
            sa.Column(
                "onchain_confidence", sa.Numeric(precision=4, scale=3), nullable=True
            ),
        )


def downgrade() -> None:
    # Safe downgrade - only drop columns if they exist
    conn = op.get_bind()

    # Check and drop onchain_confidence
    result = conn.execute(
        sa_text(
            """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'signals' AND column_name = 'onchain_confidence'
    """
        )
    )

    if result.fetchone():
        op.drop_column("signals", "onchain_confidence")

    # Check and drop onchain_asof_ts
    result = conn.execute(
        sa_text(
            """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'signals' AND column_name = 'onchain_asof_ts'
    """
        )
    )

    if result.fetchone():
        op.drop_column("signals", "onchain_asof_ts")
