"""Explicit in-process DEMO harness, not production wiring or a policy adapter."""
import os
import sys

from generator.cases.scale_generator import LogicalClock, ROOT, instant
from generator.cases.scale_loader import load_seed
from generator.cases.verification import utc


class DeadlineObserver:
    """Record successful real port calls; replay failure never becomes a PASS."""

    def __init__(self, delegate, clock):
        self.delegate, self.clock, self.calls = delegate, clock, []

    def _call(self, name, uow, subject, rule_id, *args):
        result = getattr(self.delegate, name)(uow, subject, rule_id, *args)
        self.calls.append(dict(application_id=str(subject.id), operation={"open": "OPEN", "close": "CLOSE",
            "pause_internal": "PAUSE", "resume_internal": "RESUME"}[name], rule_id=rule_id, at_clock=instant(self.clock.now())))
        return result

    def open(self, uow, subject, rule_id, anchor, ruleset_key):
        return self._call("open", uow, subject, rule_id, anchor, ruleset_key)

    def close(self, uow, subject, rule_id, outcome):
        return self._call("close", uow, subject, rule_id, outcome)

    def pause_internal(self, uow, subject, rule_id):
        return self._call("pause_internal", uow, subject, rule_id)

    def resume_internal(self, uow, subject, rule_id):
        return self._call("resume_internal", uow, subject, rule_id)


def preflight() -> None:
    """No database creation/deletion/reset; require an explicit disposable target."""
    from sqlalchemy.engine import make_url

    if any(os.environ.get(name, "").lower() not in {"true", "1", "yes"} for name in ("DEMO_MODE", "DEMO_AUTH")):
        raise ValueError("explicit DEMO_MODE=true and DEMO_AUTH=true required")
    url = os.environ.get("DATABASE_URL")
    if not url or not (make_url(url).database or "").endswith("_verify"):
        raise ValueError("explicit DATABASE_URL must name a dedicated *_verify database")


def collect(client, receipt: dict, calls: list[dict], seed: int) -> dict:
    """API-only reads of actual P1/P3 state; never inspect other owners' tables."""
    auth = {"X-Demo-User": "00000000-0000-4000-9000-000000000001", "X-Demo-Role": "AUDITOR"}

    def get(path):
        response = client.get("/api" + path, headers=auth)
        if response.status_code != 200:
            raise RuntimeError(f"verification GET {path}: {response.status_code} {response.text}")
        return response.json()

    cases = {}
    for logical, runtime_id in receipt["applications"].items():
        prefix = f"/cases/{runtime_id}"
        timeline = get(prefix + "/timeline")
        letters, seen = [], set()
        for event in timeline:
            payload = event["payload"]
            if event["event_type"] == "wf.letter_issuance_triggered":
                letters.append(dict(letter_id=payload.get("letter_id"), type=payload.get("letter_type"),
                    at_clock=utc(event["at"]), lists_deficiencies=payload.get("lists_deficiencies")))
                seen.add(payload.get("letter_id"))
        for event in timeline:
            payload = event["payload"]
            ref = payload.get("letter_ref")
            if event["event_type"] == "wf.transition_applied" and ref and ref not in seen:
                # Existing transition event exposes the ID and action, but no deficiency flag.
                # Do not invent that flag; a positive expectation must report the missing evidence.
                letters.append(dict(letter_id=ref, type={"issue_loa": "LOA", "issue_eoa": "EOA", "issue_lod": "LOD"}.get(payload.get("action")),
                    at_clock=utc(event["at"]), lists_deficiencies=None))
                seen.add(ref)
        cases[logical] = dict(state=get(prefix), timeline=timeline,
                              deficiencies=get(prefix + "/deficiencies"), letters=letters)
    inverse = {v: k for k, v in receipt["applications"].items()}
    normalized = [dict(call, application_id=inverse.get(call["application_id"], "UNMAPPED:" + call["application_id"])) for call in calls]
    return dict(label="DEMO", seed=seed, replay_complete=True, cases=cases,
                clock_calls=normalized, ledger_verify=get("/ledger/verify"))


def replay(data: dict, answer: dict) -> tuple[dict, dict]:
    preflight()
    sys.path.insert(0, str(ROOT / "backend"))
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.platform.registry import port, provide
    from app.workflow import guards
    from app.workflow.commands import GuardFacts
    from contracts.ports import ClockPort, DeadlinePort
    from generator.cases.seed_demo import seed_scale_institutions

    clock = LogicalClock(data["generated_at_clock"])
    scenario = {}

    def facts(uow, case, command):
        return GuardFacts(has_assignment=True, applicability={"SHC": scenario["shc_applicable"]},
                          live_clock_rules=frozenset({"AICTE_PROCESSING"}), second_approval_required=False)

    app = create_app()
    provide(ClockPort, clock)  # startup loader metadata must also use the logical clock
    guards.register_fact_loader(facts)
    try:
        with TestClient(app) as client:
            auth = {"X-Demo-User": "00000000-0000-4000-9000-000000000001", "X-Demo-Role": "BUREAU_OFFICER"}
            response = client.get("/api/institutions", headers=auth)
            if response.status_code != 200:
                raise RuntimeError("cannot read DEMO institution master data")
            existing = {row["id"] for row in response.json()}
            if existing & {row["id"] for row in data["institutions"]}:
                raise ValueError("seed already exists; use a fresh migrated *_verify database")
            observer = DeadlineObserver(port(DeadlinePort), clock)
            provide(DeadlinePort, observer)
            receipt = load_seed(data, answer, client, clock, bootstrap_institutions=seed_scale_institutions,
                configure_scenario=lambda value: (scenario.clear(), scenario.update(value)), validate_outcome=False)
            actual = collect(client, receipt, observer.calls, data["seed"])
            return receipt, actual
    finally:
        guards.register_fact_loader(None)
