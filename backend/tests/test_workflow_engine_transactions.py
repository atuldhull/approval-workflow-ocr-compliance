"""PostgreSQL atomicity with test-local transactional P2/P3 fake adapters."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator
from sqlalchemy import event, func, insert, select
import pytest

from app.intake.models import Application, ApplicationItem, StageVisit
from app.platform.db import get_engine, new_session, unit_of_work
from app.platform.ledger import Ledger
from app.platform.models import DomainEvent, LedgerEntry
from app.platform.registry import provide
from app.workflow import engine, guards
from app.workflow.commands import Command, GuardFacts, Options, Payload, WorkflowConflict, WorkflowValidationFailed
from app.workflow.loader import sync_rulesets
from app.workflow.models import CaseState, TransitionDefinition
from app.workflow.registry import RulesetRegistry
from app.workflow.storage import visits
from conftest import SUNRISE
from contracts.enums import ApplicationStatus, Role
from contracts.errors import Conflict, Forbidden
from contracts.fakes import AllowAllAuthz, FakeCases, FakeClock, FakeCompliance, FakeDeadlines, FakeDeadlineRuleParser, FakeEvc, FakeLedger, FakeNotes
from contracts.ports import AuthzPort, CasePort, ClockPort, CompliancePort, DeadlinePort, DeadlineRuleParserPort, EvcPort, LedgerPort, NotesPort, RulesetPort
from contracts.types import CaseRef, Principal
from test_workflow_engine_core import DECISION, ITEM, RESPONSE, SECOND, letter

ROOT = Path(__file__).resolve().parents[2]
AT = datetime(2026, 7, 1, 4, 30, tzinfo=timezone.utc)
R1 = "aph-2024-27@r1"


def journal(uow, obj, names):
    key = ("engine-fake", id(obj))
    if key in uow.session.info:
        return
    snapshot = {name: deepcopy(getattr(obj, name)) for name in names}
    uow.session.info[key] = snapshot

    def undo(session):
        for name, value in snapshot.items():
            setattr(obj, name, deepcopy(value))
    event.listen(uow.session, "after_rollback", undo, once=True)


class TxNotes(FakeNotes):
    def create(self, uow, body):
        journal(uow, self, ["notes"])
        return super().create(uow, body)


class TxCompliance(FakeCompliance):
    def register_letter(self, uow, value):
        journal(uow, self, ["letters"])
        return super().register_letter(uow, value)


class TxEvc(FakeEvc):
    """Isolate workflow tests; real EVC/clock atomicity is covered by queue tests."""
    def enter(self, uow, case, **kwargs):
        journal(uow, self, ["calls", "requests"])
        return super().enter(uow, case, **kwargs)

    def complete(self, uow, case, **kwargs):
        journal(uow, self, ["calls", "requests"])
        return super().complete(uow, case, **kwargs)

    def cancel(self, uow, case, **kwargs):
        journal(uow, self, ["calls", "requests"])
        return super().cancel(uow, case, **kwargs)


class TxDeadlines(FakeDeadlines):
    def __init__(self):
        super().__init__()
        self.live = {"AICTE_PROCESSING"}
        self.attempts = []
        self.fail_pause = False
        self.anchors = []

    def open(self, uow, subject, rule_id, anchor, ruleset_key):
        journal(uow, self, ["calls", "live", "anchors"])
        self.live.add(rule_id)
        self.anchors.append(anchor)
        return super().open(uow, subject, rule_id, anchor, ruleset_key)

    def close(self, uow, subject, rule_id, outcome):
        journal(uow, self, ["calls", "live", "anchors"])
        self.live.discard(rule_id)
        return super().close(uow, subject, rule_id, outcome)

    def pause_internal(self, uow, subject, rule_id):
        journal(uow, self, ["calls", "live", "anchors"])
        self.attempts.append("pause_internal")
        if self.fail_pause:
            raise Conflict("LEGAL_CLOCK_REFUSED")
        return super().pause_internal(uow, subject, rule_id)

    def resume_internal(self, uow, subject, rule_id):
        journal(uow, self, ["calls", "live", "anchors"])
        return super().resume_internal(uow, subject, rule_id)


class TxLedger(FakeLedger):
    def __init__(self):
        super().__init__()
        self.fail_on = None
        self.real = False
        self.attempt_ids = []

    def append(self, uow, value):
        journal(uow, self, ["events"])
        schema_path = ROOT / "contracts/events" / value.event_type.replace(".", "/", 1)
        schema = json.loads(schema_path.with_suffix(f".v{value.event_version}.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(json.loads(json.dumps(value.payload, default=str)))
        self.attempt_ids.extend(uow.session.scalars(select(visits.c.id).where(visits.c.exited_at.is_(None))).all())
        seq = super().append(uow, value)
        if self.real:
            seq = Ledger().append(uow, value)
        if self.fail_on is not None and len(self.events) == self.fail_on:
            raise RuntimeError("ledger failed")
        return seq


@pytest.fixture
def lab(client, monkeypatch):
    clock, ledger, notes, deadlines, compliance, cases = FakeClock(AT), TxLedger(), TxNotes(), TxDeadlines(), TxCompliance(), FakeCases()
    evc = TxEvc()
    provide(ClockPort, clock)
    provide(DeadlineRuleParserPort, FakeDeadlineRuleParser())
    registry = RulesetRegistry(ROOT / "rulesets", R1, demo_mode=False)
    provide(RulesetPort, registry)
    with new_session() as session, session.begin():
        sync_rulesets(session, registry)
    for kind, implementation in [(LedgerPort, ledger), (NotesPort, notes), (DeadlinePort, deadlines),
                                 (CompliancePort, compliance), (CasePort, cases), (EvcPort, evc), (AuthzPort, AllowAllAuthz())]:
        provide(kind, implementation)
    data = SimpleNamespace(clock=clock, ledger=ledger, notes=notes, deadlines=deadlines, compliance=compliance, cases=cases,
                           confirmed_letter=None, applicability={"SHC": True}, open_items=0, assignment=True, evc=evc)

    def facts(uow, row, command):
        return GuardFacts(open_item_count=data.open_items, checklist_complete=True, has_assignment=data.assignment,
                          reason_codes=frozenset({"DEMO_REASON"}), item_refs=frozenset({ITEM}), response_refs=frozenset({RESPONSE}),
                          decision_refs=frozenset({DECISION}), confirmed_letter=data.confirmed_letter,
                          applicability=data.applicability, live_clock_rules=frozenset(deadlines.live),
                          second_approval_required=False, second_approver_refs=frozenset({SECOND}))
    monkeypatch.setattr(guards, "_fact_loader", facts)
    monkeypatch.setattr(engine, "options", lambda: Options(True, True))
    return data


def seed(lab, *, category="NEW_INSTITUTION", stage="SCRUTINY", status="IN_PROCESS"):
    application_id = uuid5(NAMESPACE_URL, f"engine-db:{category}:{stage}:{status}")
    plan = next(r for r in engine._get_port(RulesetPort).get(R1).routes.values() if r.category == category)
    with new_session() as session, session.begin():
        session.add(Application(id=application_id, institution_id=SUNRISE, category=category, academic_year="2027-28",
                                status=status, current_stage=None if status == "DRAFT" else stage,
                                ruleset_rev=None if status == "DRAFT" else R1, route=None,
                                created_at=AT, submitted_at=None if status == "DRAFT" else AT, dsc_present=True))
        session.flush()
        if status == "DRAFT":
            session.add(ApplicationItem(application_id=application_id, item_key="DEMO_CORE_REFERENCE", state="PROVIDED", document_ref=ITEM))
        session.add(CaseState(application_id=application_id, route_id=category, ruleset_key=R1,
                              current_stage=None if status == "DRAFT" else stage, status=status))
        if status != "DRAFT":
            session.add(StageVisit(id=uuid5(NAMESPACE_URL, f"engine-db:initial:{application_id}"),
                                   application_id=application_id, stage=stage, entered_at=AT))
    lab.cases.cases[application_id] = CaseRef(application_id, SUNRISE, "Southern")
    if status == "DRAFT":
        lab.deadlines.live.clear()
    return application_id


def command(application_id, action="advance", role=Role.SCRUTINY_COMMITTEE, *, version=1, note=None, payload=None):
    actor = Principal(uuid5(NAMESPACE_URL, "engine-db:actor"), role, institution_id=SUNRISE)
    return Command(application_id=application_id, action=action, expected_version=version, reason_code="DEMO_REASON",
                   note_body=note, payload=payload or Payload(item_refs=(ITEM,), response_ref=RESPONSE, decision_ref=DECISION,
                       item_keys=("DEMO_CORE_REFERENCE",) if action == "record_deficiency" else (),
                       responses=({"item_id": uuid5(NAMESPACE_URL, f"sih26262:deficiency-item:{uuid5(NAMESPACE_URL, f'sih26262:deficiency:{application_id}:1')}:DEMO_CORE_REFERENCE"),
                                   "response_ref": RESPONSE},) if action == "submit_compliance" else ()), actor=actor)


def snapshot(application_id):
    with new_session() as session:
        row = session.get(CaseState, application_id)
        history = session.execute(select(visits).where(visits.c.application_id == application_id).order_by(visits.c.id)).all()
        return (row.current_stage, row.status, row.version, history)


def test_success_notes_versions_visits_and_event_schema(lab):
    application_id = seed(lab)
    result = engine.execute(command(application_id, note="private note body"))
    assert (result.current_stage, result.version, result.ruleset_key) == ("EVC", 2, R1)
    assert result.assumption_status == "DEMO_ASSUMPTION"
    assert [e.event_type for e in lab.ledger.events] == ["wf.transition_applied", "wf.stage_exited", "wf.stage_entered"]
    assert list(lab.notes.notes.values()) == ["private note body"]
    assert all(e.note_ref and e.note_hash and e.reason_code == "DEMO_REASON" and e.ruleset_rev == R1 for e in lab.ledger.events)
    assert "private note body" not in json.dumps([e.payload for e in lab.ledger.events], default=str)
    state = snapshot(application_id)
    assert len(state[3]) == 2 and sum(row.exited_at is None for row in state[3]) == 1


def test_replay_same_expected_version_is_conflict_without_second_effect(lab):
    application_id = seed(lab)
    cmd = command(application_id)
    engine.execute(cmd)
    before = snapshot(application_id)
    with pytest.raises(WorkflowConflict, match="VERSION_CONFLICT"):
        engine.execute(cmd)
    assert snapshot(application_id) == before and len(lab.ledger.events) == 3


def test_p2_legal_pause_refusal_rolls_back_everything(lab):
    application_id = seed(lab)
    before = snapshot(application_id)
    lab.deadlines.fail_pause = True
    with pytest.raises(Conflict, match="LEGAL_CLOCK_REFUSED"):
        engine.execute(command(application_id, "record_deficiency", note="must roll back"))
    assert lab.deadlines.attempts == ["pause_internal"]
    assert snapshot(application_id) == before
    assert lab.ledger.events == [] and lab.notes.notes == {} and lab.deadlines.calls == []
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(DomainEvent)) == 0


def test_metadata_legal_clock_is_refused_even_if_port_is_permissive(lab):
    application_id = seed(lab)
    before = snapshot(application_id)
    engine._get_port(RulesetPort).get(R1).deadline_rules["AICTE_PROCESSING"]["clock_kind"] = "LEGAL"
    with pytest.raises(WorkflowConflict, match="LEGAL_CLOCK_CANNOT_PAUSE"):
        engine.execute(command(application_id, "record_deficiency"))
    assert snapshot(application_id) == before and lab.ledger.events == [] and lab.deadlines.calls == []


def test_deficiency_compliance_rescrutiny_sequence_calls_all_timer_operations(lab):
    application_id = seed(lab)
    first = engine.execute(command(application_id, "record_deficiency"))
    assert (first.current_stage, first.version) == ("DEFICIENT", 2)
    assert [c[0] for c in lab.deadlines.calls] == ["pause", "open"]
    second = engine.execute(command(application_id, "submit_compliance", Role.INSTITUTION, version=2))
    assert (second.current_stage, second.version) == ("RESCRUTINY", 3)
    assert [c[0] for c in lab.deadlines.calls] == ["pause", "open", "close", "resume"]
    from app.workflow.deficiency import ReviewIn, review
    from app.workflow.models import DeficiencyItem
    cmd = command(application_id, version=3)
    with unit_of_work(cmd.actor) as uow:
        item = uow.session.scalar(select(DeficiencyItem))
        review(uow, application_id, item.deficiency_id, ReviewIn(expected_version=3,
            decisions=[{"item_id": item.id, "state": "ACCEPTED", "reason_code": "DEMO_REASON"}]))
    assert snapshot(application_id)[:3] == ("EVC", "IN_PROCESS", 4)
    assert len(lab.ledger.events) == 14


def test_draft_submit_uses_v2_schema_and_opens_logical_clock(lab):
    application_id = seed(lab, category="EOA_SELF_DISCLOSURE", stage="SELF_DISCLOSURE", status="DRAFT")
    result = engine.execute(command(application_id, "submit", Role.INSTITUTION))
    assert (result.status, result.current_stage, result.version) == ("IN_PROCESS", "SELF_DISCLOSURE", 2)
    assert [e.event_type for e in lab.ledger.events] == ["wf.application_submitted", "wf.stage_entered"]
    assert lab.ledger.events[0].event_version == 2 and lab.ledger.events[0].payload["dsc_present"] is True
    assert lab.deadlines.anchors[0].at == AT and lab.deadlines.anchors[0].event_seq is None


def test_ledger_failure_rolls_back_real_ledger_and_fake_effects(lab):
    application_id = seed(lab)
    before = snapshot(application_id)
    lab.ledger.real, lab.ledger.fail_on = True, 2
    with pytest.raises(RuntimeError, match="ledger failed"):
        engine.execute(command(application_id, "record_deficiency", note="rollback note"))
    assert snapshot(application_id) == before
    assert lab.notes.notes == {} and lab.ledger.events == [] and lab.deadlines.calls == []
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(DomainEvent)) == 0
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 0


def test_stage_ids_deterministic_after_rollback_retry(lab):
    application_id = seed(lab)
    lab.ledger.fail_on = 1
    cmd = command(application_id)
    with pytest.raises(RuntimeError):
        engine.execute(cmd)
    first_id = lab.ledger.attempt_ids[0]
    lab.ledger.fail_on = None
    engine.execute(cmd)
    assert lab.ledger.attempt_ids[-1] == first_id


def test_authorization_before_state_read_or_mutation(lab):
    application_id = seed(lab)
    before = snapshot(application_id)
    calls = []

    class Deny:
        def check(self, principal, action, resource):
            calls.append((action, resource.owner_institution_id))
            raise Forbidden("DENIED")

    provide(AuthzPort, Deny())
    with pytest.raises(Forbidden):
        engine.execute(command(application_id))
    assert calls == [("case.advance", SUNRISE)] and snapshot(application_id) == before
    assert lab.notes.notes == {} and lab.ledger.events == []


def test_actor_spoof_rejected(lab):
    application_id = seed(lab)
    cmd = command(application_id)
    other = Principal(uuid5(NAMESPACE_URL, "engine:spoof"), Role.BUREAU_OFFICER)
    with pytest.raises(Forbidden, match="ACTOR_MISMATCH"):
        with unit_of_work(other) as uow:
            engine.handle(uow, cmd)
    assert snapshot(application_id)[2] == 1


@pytest.mark.parametrize("stage,action", [("COUNCIL", "submit_compliance"), ("SCRUTINY", "not_an_action"), ("BROKEN", "advance")])
def test_invalid_pair_is_422_reason_code_and_no_effect(lab, stage, action):
    application_id = seed(lab, stage=stage)
    before = snapshot(application_id)
    with pytest.raises(WorkflowValidationFailed) as raised:
        engine.execute(command(application_id, action))
    assert raised.value.reason_code == "INVALID_TRANSITION" and raised.value.status_code == 422
    assert snapshot(application_id) == before and lab.ledger.events == []


def test_real_ledger_accepts_new_events(lab):
    application_id = seed(lab)
    lab.ledger.real = True
    engine.execute(command(application_id))
    with new_session() as session:
        assert session.scalar(select(func.count()).select_from(DomainEvent)) == 3
        assert Ledger().verify(session).ok


def test_letter_flag_off_then_enabled_port_receives_confirmed_references(lab, monkeypatch):
    application_id = seed(lab, category="EOA_SELF_DISCLOSURE", stage="SELF_DISCLOSURE")
    lab.confirmed_letter = letter("EOA")
    cmd = command(application_id, "issue_eoa", Role.BUREAU_OFFICER,
                  payload=Payload(decision_ref=DECISION, letter=lab.confirmed_letter))
    monkeypatch.setattr(engine, "options", lambda: Options(True, False))
    with pytest.raises(WorkflowValidationFailed, match="LETTER_ISSUANCE_DISABLED"):
        engine.execute(cmd)
    assert snapshot(application_id)[2] == 1 and lab.compliance.letters == []
    monkeypatch.setattr(engine, "options", lambda: Options(True, True))
    result = engine.execute(cmd)
    assert result.status == "APPROVED" and result.current_stage is None and result.letter_ref
    assert len(lab.compliance.letters) == 1
    value = lab.compliance.letters[0]
    assert value.application_id == application_id and value.institution_id == SUNRISE and value.letter_type == "EOA"
    assert len(lab.ledger.events) == 2  # terminal status is not a fake Stage value


def test_handle_rolls_back_even_when_caller_catches_exception(lab):
    application_id = seed(lab)
    before = snapshot(application_id)
    lab.ledger.fail_on = 1
    cmd = command(application_id)
    with unit_of_work(cmd.actor) as uow:
        with pytest.raises(RuntimeError):
            engine.handle(uow, cmd)
    assert snapshot(application_id) == before


def test_storage_view_matches_authoritative_stage_visit_mapping():
    assert list(visits.c.keys()) == list(StageVisit.__table__.c.keys())
    assert visits.schema == StageVisit.__table__.schema == "wf"


def test_available_actions_accept_attached_case_without_writes(lab):
    application_id = seed(lab)
    before = snapshot(application_id)
    with new_session() as session:
        row = session.get(CaseState, application_id)
        actor = command(application_id).actor
        first = engine.list_available_actions(row, actor)
        assert first == engine.list_available_actions(row, actor)
        assert any(a.action == "advance" and a.enabled and a.targets == ("EVC",) for a in first)
    assert snapshot(application_id) == before and lab.ledger.events == []


def test_locked_case_refreshes_cached_version_before_guards(lab):
    application_id = seed(lab)
    cmd = command(application_id)
    with unit_of_work(cmd.actor) as uow:
        cached = uow.session.get(CaseState, application_id)
        assert cached.version == 1
        with get_engine().begin() as connection:
            connection.execute(CaseState.__table__.update().where(CaseState.application_id == application_id).values(version=2))
        with pytest.raises(WorkflowConflict, match="VERSION_CONFLICT"):
            engine.handle(uow, cmd)
    assert snapshot(application_id)[2] == 2 and lab.ledger.events == []
