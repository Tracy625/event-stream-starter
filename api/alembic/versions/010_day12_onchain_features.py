"""day12_onchain_features

Revision ID: 010
Revises: 009
Create Date: 2025-09-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create onchain_features table
    op.create_table('onchain_features',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('chain', sa.Text(), nullable=False),
        sa.Column('address', sa.Text(), nullable=False),
        sa.Column('as_of_ts', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('window_minutes', sa.Integer(), nullable=False),
        sa.Column('addr_active', sa.Integer(), nullable=True),
        sa.Column('tx_count', sa.Integer(), nullable=True),
        sa.Column('growth_ratio', sa.Numeric(), nullable=True),
        sa.Column('top10_share', sa.Numeric(), nullable=True),
        sa.Column('self_loop_ratio', sa.Numeric(), nullable=True),
        sa.Column('calc_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        #sa.PrimaryKeyConstraint('id'),把这行注释掉，避免重复主键错误
        sa.UniqueConstraint('chain', 'address', 'as_of_ts', 'window_minutes'),
        sa.CheckConstraint('window_minutes IN (30, 60, 180)', name='check_window_minutes')
    )
    
    # Create index for lookups
    op.create_index('idx_onf_lookup', 'onchain_features', 
                    ['chain', 'address', 'window_minutes', 'as_of_ts'])
    
    # Add columns to signals table
    op.add_column('signals', sa.Column('onchain_asof_ts', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('signals', sa.Column('onchain_confidence', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Drop index and table
    op.drop_index('idx_onf_lookup', table_name='onchain_features')
    op.drop_table('onchain_features')
    
    # Drop columns from signals table
    op.drop_column('signals', 'onchain_confidence')
    op.drop_column('signals', 'onchain_asof_ts')