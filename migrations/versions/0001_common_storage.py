"""C-1: attack templates and attacks, with traceable source relation."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_common_storage"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attack_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("risk_subcategory", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_attack_templates_risk_subcategory", "attack_templates", ["risk_subcategory"]
    )
    op.create_table(
        "attacks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subcategory", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "source_template_id",
            sa.Uuid(),
            sa.ForeignKey("attack_templates.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_attacks_subcategory", "attacks", ["subcategory"])
    op.create_index("ix_attacks_source_template_id", "attacks", ["source_template_id"])


def downgrade():
    op.drop_table("attacks")
    op.drop_table("attack_templates")
