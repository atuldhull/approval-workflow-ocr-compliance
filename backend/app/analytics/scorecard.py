"""Scorecard: what the system can show about its own correctness, labelled by how it was measured.

Kinds:
- VERIFIED_NOW: computed from the live system at request time (ledger, replay).
- MEASURED_ON_DEMO_TRAFFIC: real measurements, but of synthetic demo activity.
- EVALUATED_ON_ANSWER_KEY: compared with an answer-key fixture in ANSWER_KEYS_DIR.
- NOT_EVALUATED: no answer key or no data yet. No number is shown.

Answer keys (JSON) in ANSWER_KEYS_DIR (default generator/answer_keys):
- routing.json  {"source": "...", "cases": [{"category": "NEW_PROGRAMME", "expected_stages": ["SCRUTINY", ...]}]}
- ocr.json      {"source": "...", "cases": [{"id": "...", "field": "...", "expected": "...", "predicted": "..."}]}
"""
import json
import os
from collections import defaultdict
from pathlib import Path

from app.platform import audit, notifier, replay
from app.platform.db import new_session
from app.platform.registry import port
from app.platform.settings import REPO_ROOT
from contracts.errors import ContractError
from contracts.ports import ClockPort, RulesetPort


def answer_keys_dir() -> Path:
    return Path(os.environ.get("ANSWER_KEYS_DIR", REPO_ROOT / "generator" / "answer_keys"))


def _load(name: str) -> dict | None:
    path = answer_keys_dir() / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _routing() -> dict:
    key = _load("routing.json")
    item = {"key": "routing", "title": "Workflow routing vs APH Table 2.3"}
    if key is None:
        return {**item, "kind": "NOT_EVALUATED", "note": "No routing answer key (routing.json) yet."}
    rules = port(RulesetPort)
    ruleset = rules.default_key()
    mismatches = []
    for case in key["cases"]:
        try:
            got = [str(s.stage) for s in rules.route_for(case["category"], ruleset).stages]
        except ContractError:
            got = None
        if got != case["expected_stages"]:
            mismatches.append({"category": case["category"], "expected": case["expected_stages"], "got": got})
    n = len(key["cases"])
    return {**item, "kind": "EVALUATED_ON_ANSWER_KEY", "source": key.get("source"), "ruleset": ruleset,
            "result": {"cases": n, "correct": n - len(mismatches),
                       "accuracy": round((n - len(mismatches)) / n, 3) if n else None, "mismatches": mismatches}}


def _ocr() -> dict:
    key = _load("ocr.json")
    item = {"key": "ocr", "title": "OCR field extraction"}
    if key is None:
        return {**item, "kind": "NOT_EVALUATED",
                "note": "Waiting for Person 2: ocr.json with expected and predicted values from the OCR pipeline."}
    per_field: dict[str, list[bool]] = defaultdict(list)
    for case in key["cases"]:
        per_field[case["field"]].append(case.get("predicted") == case["expected"])
    return {**item, "kind": "EVALUATED_ON_ANSWER_KEY", "source": key.get("source"),
            "result": {f: {"cases": len(v), "exact_match": round(sum(v) / len(v), 3)} for f, v in per_field.items()}}


def scorecard() -> dict:
    now = port(ClockPort).now()
    with new_session() as s:
        integrity = audit.verify(s, audit.configured_trusted_keys(), audit.configured_witness())
    rep = replay.replay()
    health = notifier.health(now)
    attempts = sum(health["attempts_24h"].values())
    return {"generated_at": now.isoformat(), "items": [
        {"key": "ledger_integrity", "title": "Ledger integrity", "kind": "VERIFIED_NOW",
         "result": {"status": integrity.status, "ok": integrity.ok, "entries_checked": integrity.checked}},
        {"key": "replay_consistency", "title": "Read models vs events (replay)", "kind": "VERIFIED_NOW",
         "result": {"ok": rep["ok"], "verdict": rep["verdict"], "gaps": len(rep["gaps"]), "projections": {p["name"]: p["status"] for p in rep["projections"]},
                    "unhandled_event_types": rep["unhandled_event_types"]}},
        {"key": "delivery_reliability", "title": "Alert delivery (last 24 hours)",
         "kind": "MEASURED_ON_DEMO_TRAFFIC" if attempts else "NOT_EVALUATED",
         "result": {"attempts": attempts, "first_try_success_rate": health["first_try_success_rate_24h"],
                    "dead_letters": health["by_status"]["DEAD"]} if attempts else None,
         "note": None if attempts else "No delivery attempts in the last 24 hours."},
        _routing(),
        _ocr(),
        {"key": "alerts", "title": "Alert generation (missed / duplicate / late)", "kind": "NOT_EVALUATED",
         "note": "Waiting for Person 2: alert generation and an expected-alerts answer key."},
    ]}
