"""Record the role of the officer who entered and who confirmed each fact.

The fact listing tells a reviewer who entered or confirmed a value only as a
role plus "you" / "another officer", never as a user id. Each role is written
in the same update as its user id and cannot change afterwards.

Revision ID: doc_0005_fact_actor_roles
Revises: doc_0004_document_api_lifecycle
"""

from alembic import op
import sqlalchemy as sa


revision = "doc_0005_fact_actor_roles"
down_revision = "doc_0004_document_api_lifecycle"
branch_labels = None
depends_on = None

_ROLES = "('INSTITUTION', 'SCRUTINY_COMMITTEE', 'RO_OFFICER', 'BUREAU_OFFICER', 'BUREAU_HEAD', 'AUDITOR')"


def upgrade() -> None:
    op.add_column("fact", sa.Column("review_typed_role", sa.Text(), nullable=True), schema="doc")
    op.add_column("fact", sa.Column("confirmed_role", sa.Text(), nullable=True), schema="doc")
    # facts entered before this revision have no role; new ones always do
    op.create_check_constraint(
        "ck_doc_fact_review_typed_role", "fact",
        f"(review_typed_role IS NULL OR (review_typed_by IS NOT NULL AND review_typed_role IN {_ROLES}))",
        schema="doc",
    )
    op.create_check_constraint(
        "ck_doc_fact_confirmed_role", "fact",
        f"(confirmed_role IS NULL OR (confirmed_by IS NOT NULL AND confirmed_role IN {_ROLES}))",
        schema="doc",
    )
    op.execute(
        """
        CREATE FUNCTION doc.guard_fact_actor_roles() RETURNS trigger AS $$
        BEGIN
            -- a role is set together with its user id and never changes afterwards
            IF NEW.review_typed_role IS DISTINCT FROM OLD.review_typed_role
               AND (OLD.review_typed_role IS NOT NULL OR OLD.review_typed_by IS NOT NULL) THEN
                RAISE EXCEPTION 'the role of the officer who entered a fact value is immutable';
            END IF;
            IF NEW.confirmed_role IS DISTINCT FROM OLD.confirmed_role
               AND (OLD.confirmed_role IS NOT NULL OR OLD.confirmed_by IS NOT NULL) THEN
                RAISE EXCEPTION 'the role of the officer who confirmed a fact is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_doc_fact_actor_roles BEFORE UPDATE ON doc.fact "
        "FOR EACH ROW EXECUTE FUNCTION doc.guard_fact_actor_roles()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_doc_fact_actor_roles ON doc.fact")
    op.execute("DROP FUNCTION IF EXISTS doc.guard_fact_actor_roles()")
    op.drop_constraint("ck_doc_fact_confirmed_role", "fact", schema="doc")
    op.drop_constraint("ck_doc_fact_review_typed_role", "fact", schema="doc")
    op.drop_column("fact", "confirmed_role", schema="doc")
    op.drop_column("fact", "review_typed_role", schema="doc")
