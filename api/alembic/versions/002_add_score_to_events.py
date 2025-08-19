"""Add score column to events table

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add score column to events table
    op.add_column('events', 
        sa.Column('score', sa.Float(), nullable=False, server_default=sa.text('0'))
    )


def downgrade() -> None:
    # Drop score column from events table
    op.drop_column('events', 'score')