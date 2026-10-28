"""Read-only projections of P1's persisted rule definitions, not module imports."""
from dataclasses import dataclass

from sqlalchemy import Column, MetaData, Table, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from contracts.errors import ValidationFailed

definitions = Table("route_def", MetaData(), Column("ruleset_key", Text), Column("route_id", Text),
                    Column("stage_list", JSONB), Column("clause_citation", JSONB), schema="wf")
rulesets = Table("ruleset", MetaData(), Column("key", Text), Column("source_metadata", JSONB), schema="wf")


class SubmissionBlocked(ValidationFailed):
    reason_code = "MANDATORY_ITEMS_MISSING"

    def __init__(self, keys):
        self.missing_item_keys = tuple(sorted(set(keys)))
        super().__init__(self.reason_code)


@dataclass(frozen=True)
class Plan:
    route_id: str
    ruleset_key: str
    stages: list[dict]
    clause_citation: dict
    checklist: dict
    assumptions: tuple[str, ...]
    evc: dict | None = None


def plan(session: Session, category: str, key: str) -> Plan:
    route = session.execute(select(definitions).where(definitions.c.ruleset_key == key,
                                                       definitions.c.route_id == category)).mappings().one_or_none()
    metadata = session.scalar(select(rulesets.c.source_metadata).where(rulesets.c.key == key))
    checklist = (metadata or {}).get("intake", {}).get(category)
    if route is None or checklist is None or not route["clause_citation"]:
        raise ValidationFailed("INTAKE_RULESET_NOT_LOADED")
    # a VERIFIED route citation rests on no assumption; the demo checklist still does
    cited = route["clause_citation"].get("assumption_ref")
    assumptions = sorted(set(checklist["assumption_refs"] + ([cited] if cited else [])))
    return Plan(category, key, route["stage_list"], route["clause_citation"], checklist, tuple(assumptions),
                (metadata or {}).get("evc"))


def ensure_complete(config: dict, provided: set[str], dsc_present: bool) -> None:
    missing = [item["item_key"] for item in config["items"] if item["mandatory"] and item["item_key"] not in provided]
    if config["dsc_required"] and not dsc_present:
        missing.append("DSC")
    if missing:
        raise SubmissionBlocked(missing)
