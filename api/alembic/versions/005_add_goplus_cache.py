"""Add goplus_cache table

Revision ID: 005
Revises: 004
Create Date: 2025-8-26

"""
# --- Alembic identifiers ---
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'goplus_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('endpoint', sa.String(100), nullable=False),
        sa.Column('chain_id', sa.String(20), nullable=True),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('payload_hash', sa.String(64), nullable=True),
        sa.Column('resp_json', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('fetched_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), onupdate=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create composite index for lookups
    op.create_index(
        'idx_goplus_cache_lookup',
        'goplus_cache',
        ['endpoint', 'chain_id', 'key'],
        unique=False
    )
    
    # Create index for expiration queries
    op.create_index(
        'idx_goplus_cache_expires',
        'goplus_cache',
        ['expires_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('idx_goplus_cache_expires', table_name='goplus_cache')
    op.drop_index('idx_goplus_cache_lookup', table_name='goplus_cache')
    op.drop_table('goplus_cache')