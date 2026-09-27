"""Power options: scenario architecture knobs + IQ review status of power-saving options."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB()
NOW = sa.text("now()")


def upgrade():
    op.add_column("scenarios", sa.Column("power_options", JSONB, nullable=True))
    op.create_table(
        "power_option_reviews",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id")),
        sa.Column("scenario_ref", sa.Text(), sa.ForeignKey("scenarios.id"), nullable=False),
        sa.Column("variant_ref", sa.Text(), nullable=False),  # '*' = every variant of the scenario
        sa.Column("option_key", sa.Text(), nullable=False),   # one option item, e.g. knob:crop_strategy=byrp_bcrop
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("history", JSONB, nullable=False),
        sa.Column("updated_by", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("status in ('candidate', 'iq_eval', 'adopted', 'rejected')",
                           name="ck_power_option_review_status"),
        sa.UniqueConstraint("scenario_ref", "variant_ref", "option_key", name="uq_power_option_review"),
    )
    op.create_index("ix_power_option_reviews_project_ref", "power_option_reviews", ["project_ref"])


def downgrade():
    op.drop_index("ix_power_option_reviews_project_ref", table_name="power_option_reviews")
    op.drop_table("power_option_reviews")
    op.drop_column("scenarios", "power_options")
