"""Replay a DEMO manifest through real HTTP endpoints using explicit adapters.

The caller wires the same LogicalClock into ClockPort on the demo server and
supplies trusted assignment/applicability facts. This module cannot bypass guards.
Runtime UUIDs are mapped to deterministic scenario IDs in the returned receipt.
"""
from collections.abc import Callable
from typing import Any, Protocol

from generator.cases.answer_key_models import AnswerKey
from generator.cases.scale_generator import LogicalClock, identity


class Client(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


def load_seed(data: dict, answer: dict, client: Client, clock: LogicalClock, *,
              bootstrap_institutions: Callable[[list[dict]], int],
              configure_scenario: Callable[[dict], None], validate_outcome: bool = True) -> dict:
    """Load into a fresh disposable DEMO server; fail fast on API/answer mismatch.

    Not a retry/idempotency middleware: a partial run needs a fresh demo database.
    No database access here; the only bootstrap callback is the P1 institution seed.
    """
    validated = AnswerKey.model_validate(answer)
    if data["label"] != "DEMO" or data["simulation_status"] != "SIMULATED":
        raise ValueError("DEMO manifest required")
    if data["seed"] != validated.header.seed or data["ruleset_key"] != validated.header.ruleset_key:
        raise ValueError("manifest/answer header mismatch")
    if data["applications"] != answer["applications"] or len(data["scenarios"]) != len(data["applications"]):
        raise ValueError("manifest/answer applications mismatch")
    if [i["id"] for i in data["institutions"]] != [i.id for i in validated.institutions]:
        raise ValueError("manifest/answer institutions mismatch")
    if {s["application_id"] for s in data["scenarios"]} != {a["id"] for a in data["applications"]}:
        raise ValueError("scenario IDs mismatch")
    clock.move_to(data["generated_at_clock"])
    bootstrap_institutions(data["institutions"])
    apps = {a["id"]: a for a in data["applications"]}
    expected = {w.application_id: w for w in validated.workflow_expectations}
    receipt = dict(label="DEMO", seed=data["seed"], applications={}, deficiencies={}, items={}, responses={}, cases=[])
    for scenario in data["scenarios"]:
        logical_id = scenario["application_id"]
        app = apps[logical_id]
        configure_scenario(scenario)
        user = identity(data["seed"], "actor", logical_id)

        def request(method, path, role="BUREAU_OFFICER", body=None):
            headers = {"X-Demo-User": user, "X-Demo-Role": role,
                       "X-Demo-Institution": app["institution_id"]}
            response = client.request(method, "/api" + path, headers=headers,
                                      **({"json": body} if body is not None else {}))
            if response.status_code not in (200, 201):
                raise RuntimeError(f"DEMO replay {logical_id}: {method} {path}: {response.status_code} {response.text}")
            return response.json()

        created = request("POST", "/applications", "INSTITUTION", dict(institution_id=app["institution_id"],
            category=app["category"], academic_year=scenario["academic_year"],
            items=[dict(item_key=key, document_ref=identity(data["seed"], "document", f"{logical_id}:{key}"))
                   for key in scenario["item_keys"]]))
        case_id = created["id"]
        receipt["applications"][logical_id] = case_id
        prefix = f"/cases/{case_id}"
        version = 1
        loop_index = 0
        for op in scenario["operations"]:
            clock.move_to(op["at_clock"])
            if op["kind"] == "action":
                action = op["action"]
                role = "INSTITUTION" if action in ("submit", "withdraw") else (
                    "SCRUTINY_COMMITTEE" if action == "record_deficiency" else "BUREAU_OFFICER")
                result = request("POST", prefix + "/actions", role,
                    dict(action=action, expected_version=version, reason_code="DEMO_REASON" if action in
                         ("reject", "withdraw", "record_deficiency") else None, payload=op["payload"]))
            elif op["kind"] in ("compliance", "review"):
                rounds = request("GET", prefix + "/deficiencies")["rounds"]
                current = rounds[-1]
                loop = expected[logical_id].deficiency_loops[loop_index]
                receipt["deficiencies"][loop.id] = current["id"]
                if len(current["items"]) != len(loop.items):
                    raise RuntimeError("deficiency item count differs from answer key")
                for logical_item, runtime_item in zip(loop.items, current["items"], strict=True):
                    receipt["items"][logical_item.id] = runtime_item["id"]
                if op["kind"] == "compliance":
                    responses = [dict(item_id=item["id"], response_ref=op["response_ref"]) for item in current["items"]]
                    result = request("POST", prefix + "/actions", "INSTITUTION",
                        dict(action="submit_compliance", expected_version=version, payload=dict(responses=responses)))
                    receipt["responses"][loop.response_id] = op["response_ref"]
                else:
                    result = request("POST", prefix + f"/deficiencies/{current['id']}/review", "SCRUTINY_COMMITTEE",
                        dict(expected_version=version, decisions=[dict(item_id=item["id"], state=op["state"],
                            reason_code="DEMO_RESPONSE_ACCEPTED" if op["state"] == "ACCEPTED" else "DEMO_RESPONSE_REJECTED")
                            for item in current["items"]]))
                    loop_index += 1
            else:
                raise ValueError("unknown scenario operation")
            version = result["version"]
        final = request("GET", prefix)
        outcome = expected[logical_id].route_outcome
        if validate_outcome and (final["stage"] is not None or final["status"] != outcome.expected_status.value):
            raise RuntimeError("final case does not match answer key")
        if validate_outcome and final["route"] != [s.model_dump(mode="json") for s in outcome.expected_stage_list]:
            raise RuntimeError("route differs from answer key")
        receipt["cases"].append(dict(application_id=logical_id, case_id=case_id, stage=final["stage"],
                                     status=final["status"], ruleset_key=final["ruleset_key"]))
    return receipt
