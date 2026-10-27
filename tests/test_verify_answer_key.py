"""Independent small oracle plus deliberate observation corruption and CLI exits."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import UUID

import pytest

from generator.cases.verification import compare
from generator.cases.verification_runtime import DeadlineObserver, preflight

A, H, D, I, R, ACTUAL = [str(UUID(int=n)) for n in range(1, 7)]
T0, T1, T2, T3, T4 = [f"2026-07-01T04:30:0{n}Z" for n in range(5)]


@pytest.fixture
def oracle():
    # Hand-written expectations and independently specified API observations.
    # Not copied from generator commands, compare(), or the production engine.
    answer = dict(header=dict(schema_version="0.1.0", review_status="PROPOSED_TEAM_REVIEW", label="DEMO", seed=1,
        generator_version="1.0.0", ruleset_key="aph-2024-27@r1", generated_at_clock=T0,
        counts=dict(institutions=1, applications=1, deficiency_loops=1, deficiency_items=1,
                    late_responses=0, evc_delays=0, letters=0, clock_expectations=2)),
        institutions=[dict(id=H, region="DEMO_REGION_01", ro_id="DEMO_RO_01", category="DEMO_TECHNICAL", label="DEMO")],
        applications=[dict(id=A, institution_id=H, category="BANK_DETAILS", route_id="BANK_DETAILS", pinned_ruleset_key="aph-2024-27@r1", label="DEMO")],
        workflow_expectations=[dict(application_id=A, deficiency_loop_count=1, deficiency_loops=[dict(id=D,
            recorded_at_clock=T1, as_of_clock=T3, response_id=R, responded_at_clock=T2,
            items=[dict(id=I, status="RESOLVED", resolved_at_clock=T2, resolution_response_id=R)])],
            late_responses=[], evc_delays=[], letters_to_issue=[], route_outcome=dict(at_clock=T4,
                expected_stage_list=[dict(stage="SCRUTINY", when="always")],
                expected_visited_stages=["SCRUTINY", "DEFICIENT", "RESCRUTINY"], expected_status="WITHDRAWN"))],
        clock_expectations=[dict(id=str(UUID(int=7)), application_id=A, subject_type="application", subject_id=A,
            rule_id="AICTE_PROCESSING", clock_kind="INTERNAL", clock_owner="AICTE", at_clock=T1,
            basis="DEMO_ASSUMPTION", operation="PAUSE"), dict(id=str(UUID(int=8)), application_id=A,
            subject_type="application", subject_id=A, rule_id="AICTE_PROCESSING", clock_kind="INTERNAL",
            clock_owner="AICTE", at_clock=T2, basis="DEMO_ASSUMPTION", operation="RESUME")],
        p2_extensions={}, p3_extensions={})
    receipt = dict(seed=1, applications={A: ACTUAL}, deficiencies={D: D}, items={I: I})
    actual = dict(seed=1, replay_complete=True, ledger_verify=dict(ok=True), clock_calls=[
        dict(application_id=A, operation="PAUSE", rule_id="AICTE_PROCESSING", at_clock=T1),
        dict(application_id=A, operation="RESUME", rule_id="AICTE_PROCESSING", at_clock=T2)],
        cases={A: dict(state=dict(case_id=ACTUAL, route_id="BANK_DETAILS", ruleset_key="aph-2024-27@r1",
            route=[dict(stage="SCRUTINY", when="always")], status="WITHDRAWN", stage=None),
            timeline=[dict(event_type="wf.application_submitted", payload=dict(first_stage="SCRUTINY")),
                      dict(event_type="wf.transition_applied", payload=dict(to_state="DEFICIENT")),
                      dict(event_type="wf.transition_applied", payload=dict(to_state="RESCRUTINY")),
                      dict(event_type="wf.transition_applied", payload=dict(to_state="WITHDRAWN"))],
            deficiencies=dict(rounds=[dict(id=D, round_no=1, opened_at=T1, closed_at=T3, status="CLOSED", closure_kind="ACCEPTED",
                items=[dict(id=I, state="ACCEPTED", response_ref=R)])]), letters=[])})
    return answer, receipt, actual


def test_independent_observations_pass_without_mutation(oracle):
    original = deepcopy(oracle)
    result = compare(*oracle)
    assert result["status"] == "PASS" and result["mismatch_count"] == 0
    assert result["coverage"]["letters"] == "NO_POSITIVE_COVERAGE"
    assert result["coverage"]["p2_extensions"] == result["coverage"]["p3_extensions"] == "NOT_SUPPLIED"
    assert oracle == original


@pytest.mark.parametrize("path,value", [
    (("cases", A, "state", "route"), []),
    (("cases", A, "state", "stage"), "SCRUTINY"),
    (("cases", A, "state", "ruleset_key"), "aph-2024-27@r3-DEMO"),
    (("cases", A, "timeline"), []),
    (("cases", A, "deficiencies", "rounds"), []),
    (("cases", A, "deficiencies", "rounds", 0, "items", 0, "response_ref"), H),
    (("cases", A, "deficiencies", "rounds", 0, "items", 0, "state"), "OPEN"),
    (("cases", A, "deficiencies", "rounds", 0, "opened_at"), T0),
    (("cases", A, "deficiencies", "rounds", 0, "closed_at"), T4),
    (("clock_calls",), []),
    (("clock_calls", 0, "operation"), "RESUME"),
    (("clock_calls", 0, "at_clock"), T0),
    (("cases", A, "letters"), [dict(letter_id=I, type="LOA", at_clock=T4, lists_deficiencies=False)]),
    (("ledger_verify", "ok"), False),
    (("replay_complete",), False),
    (("seed",), 2),
])
def test_corrupted_observations_report_paths_and_values(oracle, path, value):
    answer, receipt, actual = oracle
    target = actual
    for token in path[:-1]:
        target = target[token]
    target[path[-1]] = value
    result = compare(answer, receipt, actual)
    assert result["status"] == "FAIL" and result["mismatch_count"] > 0
    assert all(set(m) == {"path", "expected", "actual"} for m in result["mismatches"])


def test_extra_and_reordered_clock_operations_are_not_deduplicated(oracle):
    answer, receipt, actual = oracle
    actual["clock_calls"].reverse()
    actual["clock_calls"].append(deepcopy(actual["clock_calls"][0]))
    result = compare(answer, receipt, actual)
    assert {m["path"] for m in result["mismatches"]} >= {"clocks.count", "clocks.0", "clocks.1", "clocks.2"}


def test_positive_letter_comparison_requires_exact_type_time_flag_and_id(oracle):
    answer, receipt, actual = oracle
    answer["workflow_expectations"][0]["letters_to_issue"] = [dict(id=I, type="EOA", issue_at_clock=T4, lists_deficiencies=True)]
    answer["header"]["counts"]["letters"] = 1
    actual["cases"][A]["letters"] = [dict(letter_id=D, type="EOA", at_clock=T4, lists_deficiencies=True)]
    assert compare(answer, receipt, actual)["status"] == "PASS"
    actual["cases"][A]["letters"][0]["lists_deficiencies"] = None
    assert compare(answer, receipt, actual)["status"] == "FAIL"


@pytest.mark.parametrize("url", [None, "postgresql://host/awoc", "postgresql://host/production"])
def test_preflight_refuses_default_or_non_verification_database(monkeypatch, url):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_AUTH", "true")
    if url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="dedicated"):
        preflight()


def test_preflight_refuses_non_demo_and_observer_does_not_invent_success(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    with pytest.raises(ValueError, match="DEMO_MODE"):
        preflight()
    def fail(*args):
        raise RuntimeError("delegate failed")
    observer = DeadlineObserver(SimpleNamespace(pause_internal=fail), SimpleNamespace(now=lambda: pytest.fail("clock read")))
    with pytest.raises(RuntimeError, match="delegate failed"):
        observer.pause_internal(None, SimpleNamespace(id=A), "AICTE_PROCESSING")
    assert observer.calls == []


@pytest.mark.parametrize("mode,exit_code", [("pass", 0), ("mismatch", 1), ("error", 2)])
def test_cli_prints_mismatches_and_returns_honest_exit_code(oracle, monkeypatch, tmp_path, capsys, mode, exit_code):
    from generator.cases import verification_runtime, verify_answer_key
    answer, receipt, actual = oracle
    monkeypatch.setattr(verification_runtime, "preflight", lambda: None)
    monkeypatch.setattr(verify_answer_key, "generate", lambda *args: ({"seed": 1}, answer))
    if mode == "mismatch":
        actual["clock_calls"] = []
    def replay(*args):
        if mode == "error":
            raise RuntimeError("replay aborted")
        return receipt, actual
    monkeypatch.setattr(verification_runtime, "replay", replay)
    assert verify_answer_key.main(["--seed", "1", "--out", str(tmp_path / "result")]) == exit_code
    output = capsys.readouterr().out
    assert ("PASS" if mode == "pass" else "FAIL" if mode == "mismatch" else "ERROR") in output
    if mode == "mismatch":
        assert "clocks.count" in output
