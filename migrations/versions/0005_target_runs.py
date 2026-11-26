"""B2-7: durable target runs, cases and every attempted round."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_target_runs"
down_revision = "0004_target_loads"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "target_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "load_id",
            sa.Uuid(),
            sa.ForeignKey("target_loads.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
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
    op.create_table(
        "target_cases",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("target_runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("case_id", sa.Uuid(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("attack", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("total_rounds", sa.Integer(), nullable=False),
        sa.Column("completed_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
    )
    op.create_table(
        "target_rounds",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), primary_key=True),
        sa.Column("round_number", sa.Integer(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("response", JSONB()),
        sa.Column("evidence", JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("elapsed_ms", sa.Float()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["run_id", "case_id"],
            ["target_cases.run_id", "target_cases.case_id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index("ix_target_runs_status", "target_runs", ["status"])


def downgrade():
    op.drop_table("target_rounds")
    op.drop_table("target_cases")
    op.drop_table("target_runs")
