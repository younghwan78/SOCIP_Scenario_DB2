"""Producer-defined camera paths and chain timing."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence", sa.Column("execution_path_id", sa.Text()))
    for name in ("pipeline_model", "stage_timing", "profiling_metadata"):
        op.add_column("evidence", sa.Column(name, JSONB()))
    op.create_index("ix_evidence_execution_path_id", "evidence", ["execution_path_id"])


def downgrade():
    op.drop_index("ix_evidence_execution_path_id", table_name="evidence")
    for name in ("profiling_metadata", "stage_timing", "pipeline_model", "execution_path_id"):
        op.drop_column("evidence", name)
