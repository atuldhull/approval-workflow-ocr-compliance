"""Seed 1 full-size replay uses real auth/API/engine/deadlines/ledger, no SQL cases."""
from collections import Counter

import pytest

from app.platform import registry as bindings
from app.platform.registry import port, provide
from app.workflow import guards
from app.workflow.commands import GuardFacts
from contracts.ports import ClockPort, DeadlinePort
from generator.cases.scale_generator import LogicalClock, generate, instant
from generator.cases.scale_loader import load_seed
from generator.cases.seed_demo import seed_scale_institutions


@pytest.mark.parametrize("applications", [22, 600])
def test_seed_one_full_scale_matches_key_through_real_api(client, monkeypatch, applications):
    monkeypatch.setattr(bindings, "_impls", bindings._impls.copy())
    clock = LogicalClock()
    provide(ClockPort, clock)
    scenario = {}

    def facts(uow, case, command):
        # Explicit trusted DEMO assignment/applicability provider: never an HTTP bypass.
        return GuardFacts(has_assignment=True, applicability={"SHC": scenario["shc_applicable"]},
                          live_clock_rules=frozenset({"AICTE_PROCESSING"}), second_approval_required=False)

    monkeypatch.setattr(guards, "_fact_loader", facts)
    data, answer = generate(1, institutions=min(300, applications), applications=applications)
    with client:
        # Startup wires P2; rebind only logical ClockPort after startup.
        provide(ClockPort, clock)
        real_deadlines = port(DeadlinePort)
        timer_calls = []

        class ObservedDeadline:
            """Transparent observer; all operations still run P2's real engine."""

            def invoke(self, name, uow, subject, rule_id, *args):
                delegate = getattr(real_deadlines, name)
                result = delegate(uow, subject, rule_id, *args)
                operation = {"open": "OPEN", "close": "CLOSE", "pause_internal": "PAUSE",
                             "resume_internal": "RESUME"}[name]
                timer_calls.append((str(subject.id), operation, rule_id, instant(clock.now())))
                return result

            def open(self, uow, subject, rule_id, anchor, ruleset_key):
                return self.invoke("open", uow, subject, rule_id, anchor, ruleset_key)

            def close(self, uow, subject, rule_id, outcome):
                return self.invoke("close", uow, subject, rule_id, outcome)

            def pause_internal(self, uow, subject, rule_id):
                return self.invoke("pause_internal", uow, subject, rule_id)

            def resume_internal(self, uow, subject, rule_id):
                return self.invoke("resume_internal", uow, subject, rule_id)

        provide(DeadlinePort, ObservedDeadline())
        receipt = load_seed(data, answer, client, clock, bootstrap_institutions=seed_scale_institutions,
                            configure_scenario=lambda value: (scenario.clear(), scenario.update(value)))
        assert len(receipt["cases"]) == applications
        assert len(receipt["applications"]) == applications and len(set(receipt["applications"].values())) == applications
        assert timer_calls == [(receipt["applications"][c["application_id"]], c["operation"], c["rule_id"], c["at_clock"])
                               for c in answer["clock_expectations"]]
        assert len(receipt["items"]) == answer["header"]["counts"]["deficiency_items"]
        expected = {w["application_id"]: w for w in answer["workflow_expectations"]}
        by_app_clocks = Counter(c["application_id"] for c in answer["clock_expectations"] if c["operation"] == "OPEN")
        for final in receipt["cases"]:
            logical = final["application_id"]
            wanted = expected[logical]
            assert final["stage"] is None and final["status"] == wanted["route_outcome"]["expected_status"]
            assert final["ruleset_key"] == "aph-2024-27@r1"
            prefix = "/api/cases/" + final["case_id"]
            headers = {"X-Demo-User": "00000000-0000-4000-9000-000000000001", "X-Demo-Role": "AUDITOR"}
            timeline_response = client.get(prefix + "/timeline", headers=headers)
            assert timeline_response.status_code == 200
            timeline = timeline_response.json()
            actual = Counter(e["event_type"] for e in timeline)
            assert actual["wf.deficiency_recorded"] == wanted["deficiency_loop_count"]
            assert actual["wf.compliance_submitted"] == wanted["deficiency_loop_count"]
            assert actual["dl.deadline_opened"] == by_app_clocks[logical]
            opened = [e for e in timeline if e["event_type"] == "dl.deadline_opened"]
            expected_opened = [c for c in answer["clock_expectations"] if c["application_id"] == logical and c["operation"] == "OPEN"]
            assert [(e["payload"]["rule_id"], e["payload"]["due_date"]) for e in opened] == [
                (c["rule_id"], c["expected_due_date"]) for c in expected_opened]
            rounds_response = client.get(prefix + "/deficiencies", headers=headers)
            assert rounds_response.status_code == 200
            rounds = rounds_response.json()["rounds"]
            assert len(rounds) == wanted["deficiency_loop_count"]
            for loop, row in zip(wanted["deficiency_loops"], rounds, strict=True):
                assert row["id"] == receipt["deficiencies"][loop["id"]]
                assert row["items"][0]["response_ref"] == loop["response_id"]
                assert row["status"] == "CLOSED"
            # Event order, rather than timestamp-tied stage_visit UUIDs, is the oracle.
            observed = [e["payload"]["first_stage"] for e in timeline if e["event_type"] == "wf.application_submitted"]
            observed += [e["payload"]["to_state"] for e in timeline if e["event_type"] == "wf.transition_applied"
                         and e["payload"]["to_state"] not in ("REJECTED", "WITHDRAWN")]
            assert observed == wanted["route_outcome"]["expected_visited_stages"]
        verify = client.get("/api/ledger/verify", headers=headers)
        assert verify.status_code == 200 and verify.json()["ok"]


def test_loader_rejects_mismatched_answer_before_bootstrap():
    data, answer = generate(1, 1, 1, 1)
    data["seed"] = 2
    with pytest.raises(ValueError, match="header mismatch"):
        load_seed(data, answer, None, LogicalClock(), bootstrap_institutions=lambda rows: pytest.fail("bootstrap called"),
                  configure_scenario=lambda row: None)
