"""Day9.2: signals add source_level, features_snapshot; extend goplus_risk_enum with 'gray'"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    # 0) 扩展 ENUM：在添加任何依赖它的约束之前
    op.execute("ALTER TYPE goplus_risk_enum ADD VALUE IF NOT EXISTS 'gray'")

    # 1) 新增可空列（最小变更，读路径不破）
    with op.batch_alter_table("signals") as batch_op:
        batch_op.add_column(sa.Column("source_level", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "features_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            )
        )

    # 2) 不再额外创建 CHECK。该列为 ENUM，枚举本身已限定取值范围。
    # 若你执意要 CHECK，请使用显式枚举字面量，示例：
    # op.create_check_constraint(
    #     "ck_signals_goplus_risk_enum",
    #     "signals",
    #     "goplus_risk IN ('red'::goplus_risk_enum,'yellow'::goplus_risk_enum,"
    #     "'green'::goplus_risk_enum,'unknown'::goplus_risk_enum,'gray'::goplus_risk_enum)"
    # )


def downgrade():
    # 注意：Postgres 不支持移除 ENUM 的某个 value，故此处不可逆
    # 仅回滚新增列
    with op.batch_alter_table("signals") as batch_op:
        batch_op.drop_column("features_snapshot")
        batch_op.drop_column("source_level")
    # ENUM 'gray' 将保留（不可降级）
