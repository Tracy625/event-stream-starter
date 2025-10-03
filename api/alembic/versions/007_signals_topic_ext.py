"""signals_topic_ext

Revision ID: 007
Revises: 006
Create Date: 2025-09-04 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _has_column(bind, table, column):
    insp = inspect(bind)
    names = {c["name"] for c in insp.get_columns(table)}
    return column in names


def _safe_add(table, column: sa.Column):
    bind = op.get_bind()
    if not _has_column(bind, table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    # events table columns
    _safe_add("events", sa.Column("topic_hash", sa.String(20), nullable=True))
    _safe_add(
        "events", sa.Column("topic_entities", sa.ARRAY(sa.String()), nullable=True)
    )
    _safe_add("events", sa.Column("evidence_refs", postgresql.JSON, nullable=True))

    # signals table columns
    _safe_add("signals", sa.Column("topic_id", sa.String(20), nullable=True))
    _safe_add(
        "signals", sa.Column("topic_entities", sa.ARRAY(sa.String()), nullable=True)
    )
    _safe_add(
        "signals", sa.Column("topic_keywords", sa.ARRAY(sa.String()), nullable=True)
    )
    _safe_add("signals", sa.Column("topic_slope_10m", sa.Float(), nullable=True))
    _safe_add("signals", sa.Column("topic_slope_30m", sa.Float(), nullable=True))
    _safe_add("signals", sa.Column("topic_mention_count", sa.Integer(), nullable=True))
    _safe_add("signals", sa.Column("topic_confidence", sa.Float(), nullable=True))
    _safe_add("signals", sa.Column("topic_merge_mode", sa.String(20), nullable=True))
    _safe_add(
        "signals", sa.Column("topic_sources", sa.ARRAY(sa.String()), nullable=True)
    )
    _safe_add(
        "signals",
        sa.Column("topic_evidence_links", sa.ARRAY(sa.String()), nullable=True),
    )

    # Create indices (skip check for simplicity, CREATE INDEX IF NOT EXISTS not universal)
    try:
        op.create_index("idx_events_topic_hash", "events", ["topic_hash"])
    except:
        pass
    try:
        op.create_index("idx_events_topic_last_ts", "events", ["topic_hash", "last_ts"])
    except:
        pass
    try:
        op.create_index("idx_signals_topic_id", "signals", ["topic_id"])
    except:
        pass


def downgrade() -> None:
    # Drop indices
    try:
        op.drop_index("idx_events_topic_last_ts", table_name="events")
    except:
        pass
    try:
        op.drop_index("idx_events_topic_hash", table_name="events")
    except:
        pass
    try:
        op.drop_index("idx_signals_topic_id", table_name="signals")
    except:
        pass

    # Drop columns from events (PostgreSQL specific with IF EXISTS)
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS evidence_refs")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS topic_entities")
    op.execute("ALTER TABLE events DROP COLUMN IF EXISTS topic_hash")

    # Drop columns from signals
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_evidence_links")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_sources")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_merge_mode")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_confidence")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_mention_count")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_slope_30m")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_slope_10m")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_keywords")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_entities")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS topic_id")
