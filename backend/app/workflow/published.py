"""Read-only columns of other modules' records that the workflow shows beside a case.

Like app.intake.rules for wf, these standalone Tables are not added to Base.metadata, create nothing and are never
written: deadlines (dl) and compliance (cmp) stay the only writers. Used for the appeal window's clock and the case
summary; only stable columns are listed.
"""
from sqlalchemy import Boolean, Column, Date, DateTime, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import UUID

deadlines = Table(
    "deadline", MetaData(),
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("subject_type", Text), Column("subject_id", UUID(as_uuid=True)), Column("rule_id", Text),
    Column("clause", Text), Column("source_status", Text), Column("clock_kind", Text), Column("clock_owner", Text),
    Column("status", Text), Column("due_at", DateTime(timezone=True)), Column("due_date", Date),
    schema="dl",
)

letters = Table(
    "approval_letter", MetaData(),
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("application_id", UUID(as_uuid=True)), Column("letter_type", Text), Column("academic_year", Text),
    Column("issue_date", Date), Column("issue_date_source", Text), Column("lists_deficiencies", Boolean),
    Column("valid_until", Date), Column("registered_at", DateTime(timezone=True)),
    schema="cmp",
)

obligations = Table(
    "obligation", MetaData(),
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("application_id", UUID(as_uuid=True)), Column("kind", Text), Column("source_letter_id", UUID(as_uuid=True)),
    Column("source_clause", Text), Column("source_status", Text), Column("rule_id", Text),
    Column("deadline_id", UUID(as_uuid=True)), Column("due_date", Date), Column("status", Text),
    Column("created_at", DateTime(timezone=True)),
    schema="cmp",
)

# a BREACHED clock is still running (app.deadlines.service.LIVE)
LIVE_DEADLINES = ("RUNNING", "PAUSED", "BREACHED")
