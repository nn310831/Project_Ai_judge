"""B2-2: immutable configuration and sampling snapshots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_target_loads"
down_revision = "0003_target_configs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "target_loads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "model_config_id",
            sa.Uuid(),
            sa.ForeignKey("target_configs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade():
    op.drop_table("target_loads")
