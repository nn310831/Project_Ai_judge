"""B2-1: immutable target model configurations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_target_configs"
down_revision = "0002_phase1_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "target_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade():
    op.drop_table("target_configs")
