"""add_signals_state

Revision ID: 012
Revises: 011
Create Date: 2025-09-08

Add state column to signals table with check constraint and index
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import text as sa_text

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Existence checks BEFORE batch_alter_table to avoid flush-time exceptions
    state_exists = bind.execute(
        sa_text(
            """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'signals'
          AND column_name = 'state'
    """
        )
    ).scalar()
    check_exists = bind.execute(
        sa_text(
            """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = current_schema()
          AND table_name = 'signals'
          AND constraint_name = 'signals_state_check'
          AND constraint_type = 'CHECK'
    """
        )
    ).scalar()

    # Add column and CHECK constraint only if missing (true idempotency)
    if not state_exists or not check_exists:
        with op.batch_alter_table("signals") as batch_op:
            if not state_exists:
                batch_op.add_column(
                    sa.Column(
                        "state", sa.Text(), server_default="candidate", nullable=False
                    )
                )
            if not check_exists:
                batch_op.create_check_constraint(
                    "signals_state_check",
                    "state IN ('candidate','verified','downgraded')",
                )

    # Create index concurrently, outside transaction with adaptive column selection
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        # Detect available time column
        time_col = bind.execute(
            sa_text(
                """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'signals'
              AND column_name IN ('created_at', 'updated_at')
            ORDER BY CASE column_name
                WHEN 'created_at' THEN 1
                WHEN 'updated_at' THEN 2
                ELSE 3
            END
            LIMIT 1
        """
            )
        ).scalar()

        if time_col:
            idx_name = f"idx_signals_state_{time_col}"
            # Create if not exists
            exists = bind.execute(
                sa_text(
                    """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = :idx
            """
                ),
                {"idx": idx_name},
            ).scalar()
            if not exists:
                op.create_index(
                    idx_name,
                    "signals",
                    ["state", time_col],
                    unique=False,
                    postgresql_concurrently=True,
                )
        else:
            # Fallback: index only on state
            idx_name = "idx_signals_state_onlystate"
            exists = bind.execute(
                sa_text(
                    """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = :idx
            """
                ),
                {"idx": idx_name},
            ).scalar()
            if not exists:
                op.create_index(
                    idx_name,
                    "signals",
                    ["state"],
                    unique=False,
                    postgresql_concurrently=True,
                )


def downgrade() -> None:
    # Drop possible indexes concurrently (created_at / updated_at / onlystate)
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        for idx_name in (
            "idx_signals_state_created_at",
            "idx_signals_state_updated_at",
            "idx_signals_state_onlystate",
        ):
            exists = bind.execute(
                sa_text(
                    """
                SELECT 1 FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = :idx
            """
                ),
                {"idx": idx_name},
            ).scalar()
            if exists:
                op.drop_index(
                    idx_name, table_name="signals", postgresql_concurrently=True
                )

    # Drop constraint and column (idempotent with existence check)
    bind = op.get_bind()
    check_exists = bind.execute(
        sa_text(
            """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = current_schema()
          AND table_name = 'signals'
          AND constraint_name = 'signals_state_check'
          AND constraint_type = 'CHECK'
    """
        )
    ).scalar()
    state_exists = bind.execute(
        sa_text(
            """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'signals'
          AND column_name = 'state'
    """
        )
    ).scalar()

    if check_exists or state_exists:
        with op.batch_alter_table("signals") as batch_op:
            if check_exists:
                batch_op.drop_constraint("signals_state_check", type_="check")
            if state_exists:
                batch_op.drop_column("state")
