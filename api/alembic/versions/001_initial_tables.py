"""Create initial tables

Revision ID: 001
Revises: 
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create raw_posts table
    op.create_table('raw_posts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('author', sa.Text(), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('ts', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('urls', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column('token_ca', sa.Text(), nullable=True),
        sa.Column('symbol', sa.Text(), nullable=True),
        sa.Column('is_candidate', sa.Boolean(), server_default=sa.text("FALSE"), nullable=True),
        sa.Column('sentiment_label', sa.Text(), nullable=True),
        sa.Column('sentiment_score', sa.Float(), nullable=True),
        sa.Column('keywords', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_raw_posts_ts'), 'raw_posts', ['ts'], unique=False)
    
    # Create events table
    op.create_table('events',
        sa.Column('event_key', sa.Text(), nullable=False),
        sa.Column('type', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=True),
        sa.Column('impacted_assets', postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column('start_ts', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('last_ts', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('heat_10m', sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column('heat_30m', sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.PrimaryKeyConstraint('event_key')
    )
    
    # Create signals table
    op.create_table('signals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('event_key', sa.Text(), nullable=True),
        sa.Column('market_type', sa.Text(), nullable=True),
        sa.Column('advice_tag', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('goplus_risk', sa.Text(), nullable=True),
        sa.Column('goplus_tax', sa.Float(), nullable=True),
        sa.Column('lp_lock_days', sa.Integer(), nullable=True),
        sa.Column('dex_liquidity', sa.Float(), nullable=True),
        sa.Column('dex_volume_1h', sa.Float(), nullable=True),
        sa.Column('ts', sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(['event_key'], ['events.event_key'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_signals_event_key_ts', 'signals', ['event_key', sa.text('ts DESC')], unique=False)


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_signals_event_key_ts', table_name='signals')
    op.drop_index(op.f('ix_raw_posts_ts'), table_name='raw_posts')
    
    # Drop tables
    op.drop_table('signals')
    op.drop_table('events')
    op.drop_table('raw_posts')