"""workflow: institutions, applications, stage visits

Revision ID: wf_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "wf_0001"
down_revision = None
branch_labels = ("workflow",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS wf")
    op.create_table(
        "institution",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("ro_region", sa.Text, nullable=False),
        sa.Column("is_demo", sa.Boolean, nullable=False),
        schema="wf",
    )
    op.create_table(
        "application",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("institution_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.institution.id"), nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("academic_year", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("current_stage", sa.Text),
        sa.Column("ruleset_rev", sa.Text),
        sa.Column("route", pg.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        schema="wf",
    )
    op.create_index("ix_wf_application_institution_id", "application", ["institution_id"], schema="wf")
    op.create_table(
        "stage_visit",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", pg.UUID(as_uuid=True), sa.ForeignKey("wf.application.id"), nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True)),
        schema="wf",
    )
    op.create_index("ix_wf_stage_visit_application_id", "stage_visit", ["application_id"], schema="wf")


def downgrade() -> None:
    op.execute("DROP SCHEMA wf CASCADE")
