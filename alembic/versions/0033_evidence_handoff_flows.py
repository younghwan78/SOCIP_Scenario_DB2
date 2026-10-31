"""Hand-off flow document (sdb.handoff/1) on measurement evidence."""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("handoff_flows", JSONB))


def downgrade() -> None:
    op.drop_column("evidence", "handoff_flows")
