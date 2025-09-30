"""add_indexes_idempotency

Revision ID: 015
Revises: 014
Create Date: 2025-09-30

Create idempotency and performance indexes:
 - uniq_signals_event_type on signals(event_key, type)
 - idx_signals_ts on signals(ts)
 - idx_signals_event_key on signals(event_key)
 - uniq_outbox_event_channel on push_outbox(event_key, channel_id)
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql import text as sa_text


# revision identifiers, used by Alembic.
revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use autocommit block for CONCURRENTLY and avoid DO $$ $$ (functions)
    with op.get_context().autocommit_block():
        op.execute(sa_text(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uniq_signals_event_type "
            "ON signals(event_key, type)"
        ))
        op.execute(sa_text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signals_ts ON signals(ts)"
        ))
        op.execute(sa_text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signals_event_key ON signals(event_key)"
        ))
        op.execute(sa_text(
            "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uniq_outbox_event_channel "
            "ON push_outbox(event_key, channel_id)"
        ))


def downgrade() -> None:
    # Drop indexes concurrently if exist (Postgres >= 9.5 supports IF EXISTS)
    with op.get_context().autocommit_block():
        op.execute(sa_text("DROP INDEX CONCURRENTLY IF EXISTS uniq_outbox_event_channel"))
        op.execute(sa_text("DROP INDEX CONCURRENTLY IF EXISTS idx_signals_event_key"))
        op.execute(sa_text("DROP INDEX CONCURRENTLY IF EXISTS idx_signals_ts"))
        op.execute(sa_text("DROP INDEX CONCURRENTLY IF EXISTS uniq_signals_event_type"))
