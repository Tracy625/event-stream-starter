"""Day11: add heat_slope to signals

Revision ID: 009
Revises: 008
Create Date: 2025-09-07

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("signals", sa.Column("heat_slope", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("signals", "heat_slope")
