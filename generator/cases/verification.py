"""Pure P1 comparison of immutable expectations and independently observed data."""
from datetime import datetime
from typing import Any

from generator.cases.answer_key_models import AnswerKey


def utc(value: str) -> str:
    from generator.cases.scale_generator import instant

    return instant(datetime.fromisoformat(value.replace("Z", "+00:00")))


def compare(answer: dict, receipt: dict, actual: dict) -> dict:
    """Return every discovered mismatch; never mutate input or read a database.

    Actual data is captured from the HTTP API and real port calls, not generated
    from the expected model. A failed/incomplete replay cannot produce PASS.
    """
    key = AnswerKey.model_validate(answer)
    mismatches = []

    def check(path: str, expected: Any, observed: Any) -> None:
        if expected != observed:
            mismatches.append(dict(path=path, expected=expected, actual=observed))

    check("seed", key.header.seed, actual.get("seed"))
    check("receipt.seed", key.header.seed, receipt.get("seed"))
    check("replay_complete", True, actual.get("replay_complete"))
    expected_ids = sorted(a.id for a in key.applications)
    check("applications", expected_ids, sorted(actual.get("cases", {})))
    check("receipt.applications", expected_ids, sorted(receipt.get("applications", {})))
    mapped = receipt.get("applications", {})
    if len(mapped.values()) != len(set(mapped.values())):
        check("receipt.unique_runtime_ids", len(mapped), len(set(mapped.values())))
    workflows = {w.application_id: w for w in key.workflow_expectations}
    for app in key.applications:
        # Workflow order is not part of the schema: always join by application ID.
        workflow = workflows[app.id]
        path = f"cases.{app.id}"
        record = actual.get("cases", {}).get(app.id)
        if record is None:
            continue
        state = record.get("state", {})
        check(path + ".runtime_id", mapped.get(app.id), state.get("case_id"))
        check(path + ".route_id", app.route_id, state.get("route_id"))
        check(path + ".ruleset_key", app.pinned_ruleset_key, state.get("ruleset_key"))
        check(path + ".route", [s.model_dump(mode="json") for s in workflow.route_outcome.expected_stage_list], state.get("route"))
        check(path + ".status", workflow.route_outcome.expected_status.value, state.get("status"))
        # Current scale scenarios are terminal; nonterminal keys retain their last visit.
        terminal = workflow.route_outcome.expected_status.value in {"APPROVED", "REJECTED", "WITHDRAWN"}
        expected_stage = None if terminal else (workflow.route_outcome.expected_visited_stages[-1].value
            if workflow.route_outcome.expected_visited_stages else None)
        check(path + ".stage", expected_stage, state.get("stage"))
        timeline = record.get("timeline", [])
        visited = []
        for event in timeline:
            payload = event.get("payload", {})
            if event.get("event_type") == "wf.application_submitted":
                visited.append(payload.get("first_stage"))
            elif event.get("event_type") == "wf.transition_applied" and payload.get("to_state") not in {"APPROVED", "REJECTED", "WITHDRAWN"}:
                visited.append(payload.get("to_state"))
        check(path + ".visited_stages", [s.value for s in workflow.route_outcome.expected_visited_stages], visited)
        opened = [dict(rule_id=e["payload"].get("rule_id"), due_date=e["payload"].get("due_date"), at_clock=utc(e["at"]))
                  for e in timeline if e.get("event_type") == "dl.deadline_opened"]
        check(path + ".clock_openings", [dict(rule_id=c.rule_id, due_date=c.expected_due_date, at_clock=c.at_clock)
            for c in key.clock_expectations if c.application_id == app.id and c.operation == "OPEN"], opened)
        rounds = record.get("deficiencies", {}).get("rounds", [])
        check(path + ".round_count", workflow.deficiency_loop_count, len(rounds))
        for number, loop in enumerate(workflow.deficiency_loops, 1):
            row = next((r for r in rounds if r.get("round_no") == number), None)
            prefix = path + f".rounds.{number}"
            if row is None:
                check(prefix, "PRESENT", None)
                continue
            check(prefix + ".id", receipt.get("deficiencies", {}).get(loop.id), row.get("id"))
            check(prefix + ".opened_at", loop.recorded_at_clock, utc(row["opened_at"]) if row.get("opened_at") else None)
            expected_closed = all(i.status == "RESOLVED" for i in loop.items) or number < len(workflow.deficiency_loops)
            check(prefix + ".status", "CLOSED" if expected_closed else ("RESPONDED" if loop.response_id else "OPEN"), row.get("status"))
            check(prefix + ".closure_kind", ("ACCEPTED" if all(i.status == "RESOLVED" for i in loop.items) else "SUPERSEDED")
                  if expected_closed else None, row.get("closure_kind"))
            check(prefix + ".closed_at", loop.as_of_clock if expected_closed else None,
                  utc(row["closed_at"]) if row.get("closed_at") else None)
            items = row.get("items", [])
            check(prefix + ".item_count", len(loop.items), len(items))
            for item in loop.items:
                runtime_id = receipt.get("items", {}).get(item.id)
                observed = next((i for i in items if i.get("id") == runtime_id), None)
                item_path = prefix + f".items.{item.id}"
                if observed is None:
                    check(item_path, "PRESENT", None)
                    continue
                state_expected = "ACCEPTED" if item.status == "RESOLVED" else (
                    "REJECTED" if expected_closed else "RESPONDED" if loop.response_id else "OPEN")
                check(item_path + ".state", state_expected, observed.get("state"))
                check(item_path + ".response_ref", loop.response_id, observed.get("response_ref"))
        letters = record.get("letters", [])
        wanted = [dict(type=l.type.value, at_clock=l.issue_at_clock, lists_deficiencies=l.lists_deficiencies)
                  for l in workflow.letters_to_issue]
        seen = [dict(type=l.get("type"), at_clock=l.get("at_clock"), lists_deficiencies=l.get("lists_deficiencies")) for l in letters]
        check(path + ".letters", wanted, seen)
        for index, letter in enumerate(letters):
            if not letter.get("letter_id"):
                check(path + f".letters.{index}.letter_id", "NONEMPTY", letter.get("letter_id"))
    expected_calls = [dict(application_id=c.application_id, operation=c.operation, rule_id=c.rule_id, at_clock=c.at_clock)
                      for c in key.clock_expectations]
    check("clocks.count", len(expected_calls), len(actual.get("clock_calls", [])))
    for index in range(max(len(expected_calls), len(actual.get("clock_calls", [])))):
        wanted = expected_calls[index] if index < len(expected_calls) else None
        observed = actual.get("clock_calls", [])[index] if index < len(actual.get("clock_calls", [])) else None
        check(f"clocks.{index}", wanted, observed)
    check("ledger_verify", True, actual.get("ledger_verify", {}).get("ok"))
    return dict(label="DEMO", simulation_status="SIMULATED", seed=key.header.seed,
        status="PASS" if not mismatches else "FAIL", mismatch_count=len(mismatches), mismatches=mismatches,
        counts=key.header.counts.model_dump(),
        coverage=dict(letters="NO_POSITIVE_COVERAGE" if key.header.counts.letters == 0 else "CHECKED",
                      clocks="REAL_PORT_OBSERVER", p2_extensions="NOT_SUPPLIED", p3_extensions="NOT_SUPPLIED"))
