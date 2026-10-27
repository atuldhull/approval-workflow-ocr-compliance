"""Core access to P1's stable wf.stage_visit schema, without intake imports.

This standalone Table is not added to Base.metadata and creates no second table.
The existing mapped schema remains the migration/autogeneration authority.
"""
from sqlalchemy import Boolean, Column, DateTime, MetaData, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

visits = Table(
    "stage_visit", MetaData(),
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("application_id", UUID(as_uuid=True), nullable=False),
    Column("stage", Text, nullable=False),
    Column("entered_at", DateTime(timezone=True), nullable=False),
    Column("exited_at", DateTime(timezone=True)),
    Column("outcome", Text), Column("reason_code", Text), Column("note_ref", UUID(as_uuid=True)),
    schema="wf",
)

# P1-owned intake projection. Use only these stable columns; no module imports.
applications = Table(
    "application", MetaData(),
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("category", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("current_stage", Text),
    Column("ruleset_rev", Text),
    Column("route", JSONB),
    Column("submitted_at", DateTime(timezone=True)),
    Column("dsc_present", Boolean, nullable=False),
    schema="wf",
)

application_items = Table("application_item", MetaData(),
    Column("application_id", UUID(as_uuid=True), primary_key=True), Column("item_key", Text, primary_key=True),
    Column("state", Text), Column("document_ref", UUID(as_uuid=True)), schema="wf")
