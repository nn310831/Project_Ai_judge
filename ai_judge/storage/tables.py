import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
SCHEMA_REVISION = "0003_target_configs"
json_type = sa.JSON().with_variant(JSONB(), "postgresql")

target_configs = sa.Table(
    "target_configs",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("payload", json_type, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

attack_jobs = sa.Table(
    "attack_jobs",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("kind", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("total", sa.Integer(), nullable=True),
    sa.Column("result", json_type, nullable=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('running', 'succeeded', 'failed', 'interrupted')", name="ck_attack_jobs_status"
    ),
)

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
