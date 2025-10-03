"""Add refine_columns table

Revision ID: 004
Revises: 003
Create Date: 2025-8-24

"""

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"


def upgrade():
    with op.batch_alter_table("events") as tbl:
        tbl.add_column(sa.Column("refined_type", sa.Text(), nullable=True))
        tbl.add_column(sa.Column("refined_summary", sa.Text(), nullable=True))
        tbl.add_column(
            sa.Column(
                "refined_impacted_assets", sa.ARRAY(sa.Text()), server_default="{}"
            )
        )
        tbl.add_column(
            sa.Column("refined_reasons", sa.ARRAY(sa.Text()), server_default="{}")
        )
        tbl.add_column(sa.Column("refined_confidence", sa.Float(), nullable=True))
        tbl.add_column(sa.Column("refine_backend", sa.Text(), nullable=True))
        tbl.add_column(sa.Column("refine_latency_ms", sa.Integer(), nullable=True))
        tbl.add_column(sa.Column("refine_ok", sa.Boolean(), nullable=True))
        tbl.add_column(sa.Column("refine_error", sa.Text(), nullable=True))
        tbl.add_column(
            sa.Column(
                "refine_ts",
                sa.TIMESTAMP(timezone=True),
                server_default=sa.text("now()"),
            )
        )
    op.create_index("idx_events_refine_ts", "events", ["refine_ts"], unique=False)
    op.create_index("idx_events_refine_ok", "events", ["refine_ok"], unique=False)


def downgrade():
    op.drop_index("idx_events_refine_ok", table_name="events")
    op.drop_index("idx_events_refine_ts", table_name="events")
    with op.batch_alter_table("events") as tbl:
        for col in [
            "refined_type",
            "refined_summary",
            "refined_impacted_assets",
            "refined_reasons",
            "refined_confidence",
            "refine_backend",
            "refine_latency_ms",
            "refine_ok",
            "refine_error",
            "refine_ts",
        ]:
            tbl.drop_column(col)
