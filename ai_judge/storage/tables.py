import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
json_type = sa.JSON().with_variant(JSONB(), "postgresql")

attack_templates = sa.Table(
    "attack_templates",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("risk_subcategory", sa.Text(), nullable=False, index=True),
    sa.Column("payload", json_type, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
attacks = sa.Table(
    "attacks",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("subcategory", sa.Text(), nullable=False, index=True),
    sa.Column("payload", json_type, nullable=False),
    sa.Column(
        "source_template_id",
        sa.Uuid(),
        sa.ForeignKey("attack_templates.id", ondelete="RESTRICT"),
        index=True,
    ),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
