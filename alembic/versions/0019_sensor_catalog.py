"""Reusable sensor catalogs, timing profiles and project selections."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

def upgrade():
    for table, fields in [
        ("sensor_catalogs", ["board", "sensor_name"]),
        ("sensor_timing_profiles", ["sensor_name"]),
        ("sensor_board_lineups", []),
    ]:
        op.create_table(table, sa.Column("id", sa.Text(), primary_key=True),
            *[sa.Column(f, sa.Text(), nullable=False) for f in fields],
            sa.Column("document", postgresql.JSONB(), nullable=False),
            sa.Column("yaml_sha256", sa.Text(), nullable=False))
        for field in fields: op.create_index(f"ix_{table}_{field}", table, [field])
    op.create_table("project_sensor_selections",
        sa.Column("project_ref", sa.Text(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("slot", sa.Text(), primary_key=True),
        sa.Column("catalog_ref", sa.Text(), sa.ForeignKey("sensor_catalogs.id"), nullable=False),
        sa.Column("lineup_ref", sa.Text(), sa.ForeignKey("sensor_board_lineups.id"), nullable=False),
        sa.Column("board_config", sa.Text(), nullable=False))

def downgrade():
    for table in ["project_sensor_selections", "sensor_board_lineups", "sensor_timing_profiles", "sensor_catalogs"]:
        op.drop_table(table)
