"""Architecture exploration runs, promoted predictions, architecture review reports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB()
NOW = sa.text("now()")


def upgrade():
    op.create_table(
        "arch_exploration_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("scenario_type", sa.Text(), nullable=False),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id")),
        sa.Column("soc_ref", sa.Text()),
        sa.Column("spec", JSONB, nullable=False),
        sa.Column("variants", JSONB, nullable=False),
        sa.Column("errors", JSONB, nullable=False),
        sa.Column("summary", JSONB, nullable=False),
        sa.Column("dvfs_table_ref", sa.Text()),
        sa.Column("engine_rev", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_arch_exploration_runs_scenario_type", "arch_exploration_runs", ["scenario_type"])
    op.create_index("ix_arch_exploration_runs_soc_ref", "arch_exploration_runs", ["soc_ref"])

    op.create_table(
        "predictions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("scenario_ref", sa.Text(), sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("variant_ref", sa.Text(), nullable=False),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("exploration_run_ref", sa.Text(), sa.ForeignKey("arch_exploration_runs.id"), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("selection_rule", sa.Text(), nullable=False),
        sa.Column("selected_by", sa.Text(), nullable=False),
        sa.Column("selected_by_user", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("dvfs_table_ref", sa.Text()),
        sa.Column("supersedes_ref", sa.Text(), sa.ForeignKey("predictions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status in ('current', 'superseded')", name="ck_prediction_status"),
        sa.CheckConstraint("selected_by in ('auto', 'user')", name="ck_prediction_selected_by"),
    )
    op.create_index("idx_prediction_variant", "predictions", ["scenario_ref", "variant_ref", "status"])
    op.create_index(
        "uq_prediction_current", "predictions", ["scenario_ref", "variant_ref"],
        unique=True, postgresql_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "arch_reports",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("target_soc_ref", sa.Text()),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id")),
        sa.Column("scenario_type", sa.Text(), nullable=False),
        sa.Column("exploration_run_refs", JSONB, nullable=False),
        sa.Column("dvfs_table_ref", sa.Text()),
        sa.Column("engine_rev", sa.Text(), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("rendered_html", sa.Text(), nullable=False),
        sa.Column("html_sha256", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.Text()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status in ('draft', 'published')", name="ck_arch_report_status"),
    )
    op.create_index("ix_arch_reports_target_soc_ref", "arch_reports", ["target_soc_ref"])


def downgrade():
    op.drop_table("arch_reports")
    op.drop_index("uq_prediction_current", table_name="predictions")
    op.drop_index("idx_prediction_variant", table_name="predictions")
    op.drop_table("predictions")
    op.drop_table("arch_exploration_runs")
