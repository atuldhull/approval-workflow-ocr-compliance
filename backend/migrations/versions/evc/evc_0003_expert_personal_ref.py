"""evc: keep optional personal details as a P3-owned opaque reference."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "evc_0003"
down_revision = "evc_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("expert", sa.Column("personal_ref", pg.UUID(as_uuid=True), nullable=True), schema="evc")


def downgrade() -> None:
    op.drop_column("expert", "personal_ref", schema="evc")
