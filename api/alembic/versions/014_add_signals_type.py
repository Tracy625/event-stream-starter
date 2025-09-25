"""add_signals_type

Revision ID: 014
Revises: 013
Create Date: 2025-09-24

Add type column to signals table with CHECK constraint and index
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text as sa_text


# revision identifiers, used by Alembic.
revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add column (nullable initially for backfill)
    op.add_column('signals', sa.Column('type', sa.VARCHAR(20), nullable=True))

    # Step 2: Backfill data with explicit precedence
    # 2.1: Join to events.type (highest authority)
    op.execute(sa_text("""
        UPDATE signals s
        SET type = e.type
        FROM events e
        WHERE s.event_key = e.event_key
          AND e.type IN ('topic', 'primary', 'secondary', 'market_risk')
          AND s.type IS NULL
    """))

    # 2.2: Topic footprints
    op.execute(sa_text("""
        UPDATE signals
        SET type = 'topic'
        WHERE type IS NULL
          AND (topic_id IS NOT NULL
               OR topic_entities IS NOT NULL
               OR topic_keywords IS NOT NULL
               OR topic_confidence IS NOT NULL)
    """))

    # 2.3: Risk/GoPlus footprints
    op.execute(sa_text("""
        UPDATE signals
        SET type = 'market_risk'
        WHERE type IS NULL
          AND (goplus_risk IS NOT NULL
               OR buy_tax IS NOT NULL
               OR sell_tax IS NOT NULL
               OR lp_lock_days IS NOT NULL)
    """))

    # 2.4: Secondary/DEX footprints
    op.execute(sa_text("""
        UPDATE signals
        SET type = 'secondary'
        WHERE type IS NULL
          AND (COALESCE(dex_liquidity, 0) > 0
               OR features_snapshot IS NOT NULL)
    """))

    # 2.5: Default remaining to 'primary'
    op.execute(sa_text("""
        UPDATE signals
        SET type = 'primary'
        WHERE type IS NULL
    """))

    # Step 3: Make column NOT NULL
    op.alter_column('signals', 'type',
                    existing_type=sa.VARCHAR(20),
                    nullable=False)

    # Step 4: Add CHECK constraint
    op.create_check_constraint(
        'signals_type_check',
        'signals',
        "type IN ('topic', 'primary', 'secondary', 'market_risk')"
    )

    # Step 5: Add index
    op.create_index('idx_signals_type', 'signals', ['type'])


def downgrade() -> None:
    # Drop in reverse order
    op.drop_index('idx_signals_type', table_name='signals')
    op.drop_constraint('signals_type_check', 'signals', type_='check')
    op.drop_column('signals', 'type')