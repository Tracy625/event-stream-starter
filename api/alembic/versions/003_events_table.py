"""Create events table for D5 event aggregation

Revision ID: 003
Revises: 002
Create Date: 2025-08-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def _has_table(insp, name: str) -> bool:
    return insp.has_table(name)

def _has_column(insp, table: str, col: str) -> bool:
    return any(c["name"] == col for c in insp.get_columns(table)) if insp.has_table(table) else False

def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, "events"):
        # 全新环境：一次建全（保持 timestamptz 与现有 start_ts/last_ts 一致）
        op.create_table(
            "events",
            sa.Column("event_key", sa.Text(), nullable=False),
            sa.Column("symbol", sa.Text(), nullable=True),
            sa.Column("token_ca", sa.Text(), nullable=True),
            sa.Column("topic_hash", sa.Text(), nullable=False),
            sa.Column("time_bucket_start", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("start_ts", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("last_ts", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("evidence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("candidate_score", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("keywords_norm", JSONB(), nullable=True),
            sa.Column("version", sa.Text(), nullable=False, server_default=sa.text("'v1'")),
            sa.Column("last_sentiment", sa.Text(), nullable=True),
            sa.Column("last_sentiment_score", sa.Float(), nullable=True),
            sa.PrimaryKeyConstraint("event_key"),
        )
    else:
        # 旧表已存在：只补我们需要的列（全部幂等）
        add_cols = [
            ("symbol", sa.Text(), True),
            ("token_ca", sa.Text(), True),
            ("topic_hash", sa.Text(), True),  # 先允许 NULL，回填后再加约束
            ("time_bucket_start", sa.TIMESTAMP(timezone=True), True),
            ("evidence_count", sa.Integer(), False, sa.text("0")),
            ("candidate_score", sa.Float(), False, sa.text("0")),
            ("keywords_norm", JSONB(), True),
            ("version", sa.Text(), False, sa.text("'v1'")),
            ("last_sentiment", sa.Text(), True),
            ("last_sentiment_score", sa.Float(), True),
        ]
        for name, coltype, nullable, *default in add_cols:
            if not _has_column(insp, "events", name):
                kwargs = {"nullable": nullable}
                if default:
                    kwargs["server_default"] = default[0]
                op.add_column("events", sa.Column(name, coltype, **kwargs))

    # 索引幂等创建
    if _has_table(insp, "events"):
        existing = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes("events")}
        if "idx_events_symbol_bucket" not in existing:
            op.create_index("idx_events_symbol_bucket", "events", ["symbol", "time_bucket_start"])
        if "idx_events_last_ts" not in existing:
            op.create_index("idx_events_last_ts", "events", [sa.text("last_ts DESC")])

def downgrade() -> None:
    # 只撤我们新增的索引和列，别动老字段/外键/整张表
    op.execute("DROP INDEX IF EXISTS idx_events_last_ts")
    op.execute("DROP INDEX IF EXISTS idx_events_symbol_bucket")
    for col in [
        "last_sentiment_score", "last_sentiment", "version", "keywords_norm",
        "candidate_score", "evidence_count", "time_bucket_start",
        "topic_hash", "token_ca", "symbol",
    ]:
        op.execute(f'ALTER TABLE "events" DROP COLUMN IF EXISTS "{col}"')