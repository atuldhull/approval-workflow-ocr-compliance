"""workflow: trace carried items and distinguish accepted/superseded rounds."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0005"
down_revision = "wf_0004"
branch_labels = None  # inherits the workflow chain label
depends_on = None


def upgrade() -> None:
    op.add_column("deficiency", sa.Column("closure_kind", sa.Text), schema="wf")
    op.execute("UPDATE wf.deficiency SET closure_kind = 'ACCEPTED' WHERE status = 'CLOSED'")
    op.create_check_constraint("ck_wf_deficiency_closure_kind", "deficiency",
                               "(status = 'CLOSED') = (closure_kind IS NOT NULL)", schema="wf")
    op.create_check_constraint("ck_wf_deficiency_closure_value", "deficiency",
                               "closure_kind IS NULL OR closure_kind IN ('ACCEPTED', 'SUPERSEDED')", schema="wf")
    op.add_column("deficiency_item", sa.Column("previous_item_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("wf.deficiency_item.id", name="fk_wf_deficiency_item_previous")), schema="wf")


def downgrade() -> None:
    op.drop_column("deficiency_item", "previous_item_id", schema="wf")
    op.drop_constraint("ck_wf_deficiency_closure_value", "deficiency", type_="check", schema="wf")
    op.drop_constraint("ck_wf_deficiency_closure_kind", "deficiency", type_="check", schema="wf")
    op.drop_column("deficiency", "closure_kind", schema="wf")
