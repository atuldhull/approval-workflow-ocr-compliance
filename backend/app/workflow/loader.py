"""Reproducible YAML definition materialization; never approves or repins cases.

No commit is performed here. The startup caller owns a single transaction.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from app.platform.db import new_session
from app.platform.registry import port
from app.platform.settings import settings
from app.workflow.grammar import WorkflowDefinition, validate_workflow
from app.workflow.models import RouteDefinition, Ruleset, TransitionDefinition
from app.workflow.registry import RulesetRegistry, _read, split_key
from contracts.errors import Conflict, ValidationFailed
from contracts.ports import ClockPort
from contracts.types import RuleSet

BOOTSTRAP_REF = uuid5(NAMESPACE_URL, "sih26262:wf:yaml-bootstrap")
_SYNC_LOCK = 26262012


@dataclass(frozen=True)
class SyncResult:
    inserted: tuple[str, ...]
    unchanged: tuple[str, ...]
    skipped_demo: tuple[str, ...]


def _id(token: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"sih26262:wf:{token}")


def _sources(root: Path, key: str, seen: frozenset[str] = frozenset()) -> tuple[list[Path], dict, bool]:
    if key in seen:
        raise ValidationFailed(f"cyclic overlay inheritance: {key}")
    name, revision = split_key(key)
    folder = (root / name / revision).resolve()
    if not folder.is_relative_to(root.resolve()):
        raise ValidationFailed("ruleset source escapes configured root")
    overlay = folder / "overlay.yaml"
    if overlay.is_file():
        raw = _read(overlay)
        base = raw.get("extends")
        if not isinstance(base, str):
            raise ValidationFailed(f"{key}: overlay extends must be a ruleset key")
        files, route_raw, inherited_demo = _sources(root, base, seen | {key})
        return files + [overlay], route_raw, inherited_demo or raw.get("status") == "unverified_demo" or raw.get("demo_only") is True
    routes_path = folder / "routes.yaml"
    raw = _read(routes_path)
    files = [routes_path]
    deadlines = folder / "deadlines.yaml"
    if deadlines.is_file():
        files.append(deadlines)
    return files, raw, raw.get("demo_only") is True or raw.get("status") == "unverified_demo"


def _manifest(root: Path, files: list[Path]) -> tuple[str, list[dict]]:
    entries = []
    for path in sorted(set(files)):
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ValidationFailed("ruleset source escapes configured root")
        entries.append({"path": resolved.relative_to(root.resolve()).as_posix(), "sha256": sha256(resolved.read_bytes()).hexdigest()})
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest(), entries


def _store_routes(session: Session, row: Ruleset, rules: RuleSet, raw: dict, compiled: WorkflowDefinition) -> None:
    transitions = []
    for category, route in rules.routes.items():
        route_id = _id(f"{rules.key}:route:{category}")
        session.add(RouteDefinition(
            id=route_id, ruleset_id=row.id, ruleset_key=row.key, route_id=category, category=category,
            stage_list=[{"stage": stage.stage.value, "when": stage.when} for stage in route.stages],
            clause_citation=raw["routes"][category].get("clause_citation"),
        ))
        for position, edge in enumerate(compiled.routes[category]):
            spec = edge.transition.model_dump(mode="json")
            transitions.append({
                "id": _id(f"{rules.key}:route:{category}:edge:{position}"), "route_def_id": route_id,
                "position": position, "template_id": edge.template, "action": spec["action"],
                "from_stage": edge.source, "to_stage": edge.target,
                "roles": spec["allowed_roles"], "guards": spec["guards"], "timers": spec["timers"],
                "letter": spec["letter"], "reason_codes_required": spec["reason_codes_required"],
                "emits_event": spec["emits_event"], "definition": spec,
            })
    session.flush()
    if transitions:
        session.execute(insert(TransitionDefinition), transitions)


def sync_rulesets(session: Session, registry: RulesetRegistry, *, created_by_ref: UUID = BOOTSTRAP_REF) -> SyncResult:
    """Append immutable source snapshots; unchanged keys are a strict no-op.

    Lifecycle DRAFT here means imported configuration, not an authorized approval.
    All writes are to definition tables in wf; case_state is never updated.
    """
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SYNC_LOCK})
    inserted, unchanged, skipped = [], [], []
    keys = registry.available()
    if registry.default_key() not in keys:
        raise ValidationFailed("default ruleset source is missing")
    # Fresh cache avoids persisting a stale parsed definition with a new hash.
    fresh = RulesetRegistry(registry.root, registry.default_key(), registry.demo_mode)
    now = None
    for key in keys:
        files, raw, demo_only = _sources(fresh.root, key)
        if demo_only and not fresh.demo_mode:
            if key == fresh.default_key():
                raise ValidationFailed("default ruleset is demo-only outside demo mode")
            skipped.append(key)
            continue
        checksum, manifest = _manifest(fresh.root, files)
        rules = fresh.get(key)
        compiled = validate_workflow(raw, rules.routes, rules.deadline_rules)
        after_files, _, _ = _sources(fresh.root, key)
        if _manifest(fresh.root, after_files)[0] != checksum:
            raise Conflict(f"ruleset source changed while loading {key}")
        existing = session.scalar(select(Ruleset).where(Ruleset.key == key).with_for_update())
        if existing is not None:
            if existing.checksum != checksum:
                raise Conflict(f"immutable ruleset {key} has different source checksum; create a new revision")
            unchanged.append(key)
            continue
        if now is None:
            now = port(ClockPort).now()
        row = Ruleset(
            id=_id(f"ruleset:{key}"), key=key, version=rules.revision, status="DRAFT", checksum=checksum,
            demo_only=demo_only, source_status=rules.status, source_files=manifest,
            source_metadata={"source": raw.get("source"), "workflow_source": raw.get("workflow_source"),
                             "roles": rules.roles, "banner": rules.banner},
            created_at=now, created_by_ref=created_by_ref, approved_at=None, approved_by_ref=None,
        )
        session.add(row)
        session.flush()
        _store_routes(session, row, rules, raw, compiled)
        inserted.append(key)
    return SyncResult(tuple(inserted), tuple(unchanged), tuple(skipped))


def sync_at_startup() -> None:
    """Called by workflow's router after wiring and after migrations, never import."""
    registry = RulesetRegistry(settings.rulesets_dir, settings.default_ruleset, settings.demo_mode)
    with new_session() as session, session.begin():
        sync_rulesets(session, registry)
