"""Durable, actor-owned What-If sweep checkpoints."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("whatif_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB()), sa.Column("error", sa.Text()),
        sa.Column("completed_cases", sa.Integer(), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("worker_token", sa.Text()),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status in ('queued','running','completed','cancelled','failed','interrupted')", name="ck_whatif_job_status"))
    op.create_index("idx_whatif_job_actor", "whatif_jobs", ["created_by", "created_at"])


def downgrade():
    op.drop_table("whatif_jobs")
