import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()
SCHEMA_REVISION = "0005_target_runs"
json_type = sa.JSON().with_variant(JSONB(), "postgresql")

target_runs = sa.Table(
    "target_runs",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "load_id", sa.Uuid(), sa.ForeignKey("target_loads.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column("payload", json_type, nullable=False),
    sa.Column("status", sa.Text(), nullable=False, index=True),
    sa.Column("total_cases", sa.Integer(), nullable=False),
    sa.Column("completed_cases", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("failed_cases", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("current_case_id", sa.Uuid()),
    sa.Column("current_round", sa.Integer()),
    sa.Column("error", sa.Text()),
    sa.Column("owner", sa.Uuid()),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "status IN ('queued','running','succeeded','failed','interrupted','partial')",
        name="ck_target_runs_status",
    ),
)
target_cases = sa.Table(
    "target_cases",
    metadata,
    sa.Column(
        "run_id", sa.Uuid(), sa.ForeignKey("target_runs.id", ondelete="RESTRICT"), primary_key=True
    ),
    sa.Column("case_id", sa.Uuid(), primary_key=True),
    sa.Column("position", sa.Integer(), nullable=False),
    sa.Column("attack", json_type, nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("total_rounds", sa.Integer(), nullable=False),
    sa.Column("completed_rounds", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("error", sa.Text()),
)
target_rounds = sa.Table(
    "target_rounds",
    metadata,
    sa.Column("run_id", sa.Uuid(), primary_key=True),
    sa.Column("case_id", sa.Uuid(), primary_key=True),
    sa.Column("round_number", sa.Integer(), primary_key=True),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("request", json_type, nullable=False),
    sa.Column("response", json_type),
    sa.Column("evidence", json_type),
    sa.Column("error", sa.Text()),
    sa.Column("elapsed_ms", sa.Float()),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.ForeignKeyConstraint(
        ["run_id", "case_id"], ["target_cases.run_id", "target_cases.case_id"], ondelete="RESTRICT"
    ),
)

target_loads = sa.Table(
    "target_loads",
    metadata,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column(
        "model_config_id",
        sa.Uuid(),
        sa.ForeignKey("target_configs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("payload", json_type, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

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
