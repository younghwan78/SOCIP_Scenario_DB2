"""initial schema — §22 DDL

Revision ID: 0001
Revises:
Create Date: 2026-04-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ HW Capability
    op.create_table(
        "soc_platforms",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("process_node",   sa.Text),
        sa.Column("memory_type",    sa.Text),
        sa.Column("bus_protocol",   sa.Text),
        sa.Column("ips",            JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    op.create_table(
        "ip_catalog",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("category",       sa.Text),
        sa.Column("hierarchy",      JSONB),
        sa.Column("capabilities",   JSONB),
        sa.Column("rtl_version",    sa.Text),
        sa.Column("compatible_soc", JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    # ------------------------------------------------------------------ SW Capability
    op.create_table(
        "sw_profiles",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("metadata",       JSONB,   nullable=False),
        sa.Column("components",     JSONB,   nullable=False),
        sa.Column("feature_flags",  JSONB,   nullable=False),
        sa.Column("compatibility",  JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )
    op.create_index(
        "idx_sw_prof_features", "sw_profiles", ["feature_flags"],
        postgresql_using="gin",
    )
    op.execute(
        "CREATE INDEX idx_sw_prof_family ON sw_profiles "
        "((metadata->>'baseline_family'))"
    )

    op.create_table(
        "sw_components",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("category",       sa.Text),
        sa.Column("metadata",       JSONB),
        sa.Column("feature_flags",  JSONB),
        sa.Column("capabilities",   JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    # ------------------------------------------------------------------ Definition
    op.create_table(
        "projects",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("metadata",       JSONB,   nullable=False),
        sa.Column("globals",        JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    op.create_table(
        "scenarios",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("project_ref",    sa.Text, sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("metadata",       JSONB,   nullable=False),
        sa.Column("pipeline",       JSONB,   nullable=False),
        sa.Column("size_profile",   JSONB),
        sa.Column("design_axes",    JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    op.create_table(
        "scenario_variants",
        sa.Column("scenario_id",          sa.Text, sa.ForeignKey("scenarios.id"), primary_key=True),
        sa.Column("id",                   sa.Text, primary_key=True),
        sa.Column("severity",             sa.Text),
        sa.Column("design_conditions",    JSONB),
        sa.Column("ip_requirements",      JSONB),
        sa.Column("sw_requirements",      JSONB),
        sa.Column("violation_policy",     JSONB),
        sa.Column("tags",                 JSONB),
        sa.Column("derived_from_variant", sa.Text),
    )

    # ------------------------------------------------------------------ Evidence
    op.create_table(
        "sweep_jobs",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("scenario_ref",   sa.Text, sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("variant_ref",    sa.Text, nullable=False),
        sa.Column("sweep_axis",     sa.Text, nullable=False),
        sa.Column("sweep_values",   JSONB,   nullable=False),
        sa.Column("total_runs",     sa.Integer, nullable=False),
        sa.Column("completed_runs", sa.Integer, server_default="0"),
        sa.Column("status",         sa.Text),
        sa.Column("launched_at",    sa.DateTime(timezone=True)),
        sa.Column("completed_at",   sa.DateTime(timezone=True)),
    )
    op.create_index(
        "idx_sweep_jobs_scenario", "sweep_jobs", ["scenario_ref", "variant_ref"],
    )

    op.create_table(
        "evidence",
        sa.Column("id",                  sa.Text, primary_key=True),
        sa.Column("schema_version",      sa.Text, nullable=False),
        sa.Column("kind",                sa.Text, nullable=False),
        sa.Column("scenario_ref",        sa.Text, sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("variant_ref",         sa.Text, nullable=False),
        sa.Column("sw_baseline_ref",     sa.Text, sa.ForeignKey("sw_profiles.id")),
        sa.Column("sweep_job_id",        sa.Text, sa.ForeignKey("sweep_jobs.id")),
        sa.Column("execution_context",   JSONB,   nullable=False),
        sa.Column("sweep_context",       JSONB),
        sa.Column("resolution_result",   JSONB),
        sa.Column("overall_feasibility", sa.Text),
        sa.Column("aggregation",         JSONB,   nullable=False),
        sa.Column("kpi",                 JSONB,   nullable=False),
        sa.Column("run_info",            JSONB),
        sa.Column("ip_breakdown",        JSONB),
        sa.Column("provenance",          JSONB),
        sa.Column("artifacts",           JSONB),
        sa.Column("yaml_sha256",         sa.Text, nullable=False),
        # Generated columns — §22
        sa.Column(
            "sw_version_hint",
            sa.Text,
            sa.Computed("(execution_context->>'sw_baseline_ref')::text", persisted=True),
        ),
        sa.Column(
            "sweep_value_hint",
            sa.Text,
            sa.Computed("(sweep_context->>'sweep_value')::text", persisted=True),
        ),
    )
    op.create_index("idx_ev_sw",          "evidence", ["sw_version_hint"])
    op.create_index("idx_ev_sweep",       "evidence", ["sweep_job_id"])
    op.create_index("idx_ev_feasibility", "evidence", ["overall_feasibility"])

    # ------------------------------------------------------------------ Decision
    op.create_table(
        "gate_rules",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("metadata",       JSONB,   nullable=False),
        sa.Column("trigger",        JSONB,   nullable=False),
        sa.Column("applies_to",     JSONB),
        sa.Column("condition",      JSONB,   nullable=False),
        sa.Column("action",         JSONB,   nullable=False),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    op.create_table(
        "issues",
        sa.Column("id",             sa.Text, primary_key=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("metadata",       JSONB,   nullable=False),
        sa.Column("affects",        JSONB),
        sa.Column("affects_ip",     JSONB),
        sa.Column("pmu_signature",  JSONB),
        sa.Column("resolution",     JSONB),
        sa.Column("yaml_sha256",    sa.Text, nullable=False),
    )

    op.create_table(
        "waivers",
        sa.Column("id",                      sa.Text, primary_key=True),
        sa.Column("yaml_sha256",             sa.Text, nullable=False),
        sa.Column("title",                   sa.Text, nullable=False),
        sa.Column("issue_ref",               sa.Text, sa.ForeignKey("issues.id")),
        sa.Column("scope",                   JSONB,   nullable=False),
        sa.Column("justification",           sa.Text),
        sa.Column("status",                  sa.Text, nullable=False),
        sa.Column("approver_claim",          sa.Text, nullable=False),
        sa.Column("claim_at",                sa.Date),
        sa.Column("git_commit_sha",          sa.Text),
        sa.Column("git_commit_author_email", sa.Text),
        sa.Column("git_signed",              sa.Boolean),
        sa.Column("approved_by_auth",        sa.Text),
        sa.Column("auth_method",             sa.Text),
        sa.Column("auth_timestamp",          sa.DateTime(timezone=True)),
        sa.Column("auth_session_id",         sa.Text),
        sa.Column("approved_at",             sa.Date),
        sa.Column("expires_on",              sa.Date),
    )

    op.create_table(
        "waiver_audit_log",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("waiver_id",    sa.Text, nullable=False),
        sa.Column("action",       sa.Text, nullable=False),
        sa.Column("actor",        sa.Text),
        sa.Column("actor_method", sa.Text),
        sa.Column("timestamp",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("before_state", JSONB),
        sa.Column("after_state",  JSONB),
    )

    op.create_table(
        "reviews",
        sa.Column("id",                      sa.Text, primary_key=True),
        sa.Column("yaml_sha256",             sa.Text, nullable=False),
        sa.Column("scenario_ref",            sa.Text, sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("variant_ref",             sa.Text, nullable=False),
        sa.Column("evidence_refs",           JSONB),
        sa.Column("gate_result",             sa.Text),
        sa.Column("auto_checks",             JSONB),
        sa.Column("decision",                sa.Text),
        sa.Column("waiver_ref",              sa.Text, sa.ForeignKey("waivers.id")),
        sa.Column("rationale",               sa.Text),
        sa.Column("review_scope",            JSONB),
        sa.Column("validation",              JSONB),
        sa.Column("status",                  sa.Text, nullable=False),
        sa.Column("approver_claim",          sa.Text, nullable=False),
        sa.Column("claim_at",                sa.Date),
        sa.Column("git_commit_sha",          sa.Text),
        sa.Column("git_commit_author_email", sa.Text),
        sa.Column("git_signed",              sa.Boolean),
        sa.Column("approved_by_auth",        sa.Text),
        sa.Column("auth_method",             sa.Text),
        sa.Column("auth_timestamp",          sa.DateTime(timezone=True)),
        sa.Column("auth_session_id",         sa.Text),
    )

    op.create_table(
        "review_audit_log",
        sa.Column("id",           UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("review_id",    sa.Text, nullable=False),
        sa.Column("action",       sa.Text, nullable=False),
        sa.Column("actor",        sa.Text),
        sa.Column("actor_method", sa.Text),
        sa.Column("timestamp",    sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("before_state", JSONB),
        sa.Column("after_state",  JSONB),
    )


def downgrade() -> None:
    op.drop_table("review_audit_log")
    op.drop_table("reviews")
    op.drop_table("waiver_audit_log")
    op.drop_table("waivers")
    op.drop_table("issues")
    op.drop_table("gate_rules")
    op.drop_table("evidence")
    op.drop_table("sweep_jobs")
    op.drop_table("scenario_variants")
    op.drop_table("scenarios")
    op.drop_table("projects")
    op.drop_table("sw_components")
    op.drop_table("sw_profiles")
    op.drop_table("ip_catalog")
    op.drop_table("soc_platforms")
