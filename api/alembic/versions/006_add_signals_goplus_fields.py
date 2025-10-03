"""Add signals goplus fields (idempotent)

Revision ID: 006
Revises: 005
Create Date: 2025-01-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Create enum type if missing
    op.execute(
        """
    DO $$
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'goplus_risk_enum') THEN
        CREATE TYPE goplus_risk_enum AS ENUM ('red','yellow','green','unknown');
      END IF;
    END$$;
    """
    )

    # helper: check if column exists
    def col_exists(table: str, col: str) -> bool:
        return (
            bind.execute(
                sa.text(
                    """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = :t AND column_name = :c
            """
                ),
                {"t": table, "c": col},
            ).first()
            is not None
        )

    # 2) goplus_risk: alter to enum if exists, else add
    if col_exists("signals", "goplus_risk"):
        op.execute(
            """
        ALTER TABLE signals
        ALTER COLUMN goplus_risk TYPE goplus_risk_enum
        USING (
          CASE
            WHEN goplus_risk IN ('red','yellow','green','unknown')
              THEN goplus_risk::goplus_risk_enum
            ELSE 'unknown'::goplus_risk_enum
          END
        );
        """
        )
    else:
        risk_enum = postgresql.ENUM(
            "red", "yellow", "green", "unknown", name="goplus_risk_enum"
        )
        op.add_column("signals", sa.Column("goplus_risk", risk_enum, nullable=True))

    # 3) other columns: add if not exists
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS buy_tax DOUBLE PRECISION;")
    op.execute(
        "ALTER TABLE signals ADD COLUMN IF NOT EXISTS sell_tax DOUBLE PRECISION;"
    )
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS lp_lock_days INTEGER;")
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS honeypot BOOLEAN;")

    # 4) index on goplus_risk: create if missing
    op.execute(
        """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'idx_signals_goplus_risk' AND c.relkind = 'i'
      ) THEN
        CREATE INDEX idx_signals_goplus_risk ON signals (goplus_risk);
      END IF;
    END$$;
    """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # drop index if exists
    op.execute("DROP INDEX IF EXISTS idx_signals_goplus_risk;")

    # downgrade goplus_risk to text if present
    if bind.execute(
        sa.text(
            """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name='signals' AND column_name='goplus_risk'
    """
        )
    ).first():
        op.execute(
            """
        ALTER TABLE signals
        ALTER COLUMN goplus_risk TYPE text
        USING goplus_risk::text;
        """
        )

    # drop the other columns if exist
    for col in ["honeypot", "lp_lock_days", "sell_tax", "buy_tax"]:
        op.execute(f"ALTER TABLE signals DROP COLUMN IF EXISTS {col};")

    # drop enum type if no longer used
    op.execute(
        """
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_depend d ON d.refobjid = t.oid
        WHERE t.typname = 'goplus_risk_enum' AND d.classid = 'pg_type'::regclass
      ) THEN
        DROP TYPE IF EXISTS goplus_risk_enum;
      END IF;
    END$$;
    """
    )
