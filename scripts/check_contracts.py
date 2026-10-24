"""Validates the shared contracts.

- every event schema is valid JSON Schema, lives under a known module prefix and allows no free text
- every fake in contracts/fakes.py implements its port
- contracts/openapi.json matches the API the code actually serves (run with --write to refresh it)
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from jsonschema import Draft202012Validator  # noqa: E402

from contracts import fakes, ports  # noqa: E402
from contracts.enums import MODULE_PREFIXES  # noqa: E402

EVENTS = ROOT / "contracts" / "events"
OPENAPI = ROOT / "contracts" / "openapi.json"
NAME = re.compile(r"^[a-z][a-z0-9_]*\.v[1-9][0-9]*\.json$")

FAKE_FOR = {
    ports.LedgerPort: fakes.FakeLedger, ports.NotesPort: fakes.FakeNotes,
    ports.PersonalDataPort: fakes.FakePersonalData, ports.OutboxPort: fakes.FakeOutbox,
    ports.AuthzPort: fakes.AllowAllAuthz, ports.RulesetPort: fakes.FakeRulesets, ports.CasePort: fakes.FakeCases,
    ports.DeadlineRuleParserPort: fakes.FakeDeadlineRuleParser, ports.DeadlinePort: fakes.FakeDeadlines,
    ports.CompliancePort: fakes.FakeCompliance, ports.ClockPort: fakes.FakeClock,
}


def free_text(schema: dict, path: str) -> list[str]:
    found = []
    if schema.get("type") == "string" and not ({"enum", "format", "pattern", "const"} & schema.keys()):
        found.append(path)
    for key, sub in (schema.get("properties") or {}).items():
        found += free_text(sub, f"{path}.{key}")
    if isinstance(schema.get("items"), dict):
        found += free_text(schema["items"], f"{path}[]")
    return found


def check_events() -> list[str]:
    problems = []
    for f in sorted(EVENTS.rglob("*.json")):
        rel = f.relative_to(EVENTS).as_posix()
        prefix = f.parent.name
        if prefix not in MODULE_PREFIXES:
            problems.append(f"{rel}: unknown module prefix '{prefix}'")
        if not NAME.match(f.name):
            problems.append(f"{rel}: name must be <event_name>.v<N>.json")
        schema = json.loads(f.read_text(encoding="utf-8"))
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{rel}: invalid schema: {e}")
            continue
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            problems.append(f"{rel}: must be an object with additionalProperties: false")
        for p in free_text(schema, "payload"):
            problems.append(f"{rel}: {p} is free text - use enum, format or pattern (free text goes in case_note)")
    return problems


def check_fakes() -> list[str]:
    problems = []
    declared = {v for v in vars(ports).values()
                if isinstance(v, type) and getattr(v, "_is_protocol", False) and v.__module__ == ports.__name__}
    for port in declared - {ports.UnitOfWork}:
        fake = FAKE_FOR.get(port)
        if fake is None:
            problems.append(f"{port.__name__}: no fake in contracts/fakes.py")
        elif not isinstance(fake(), port):
            problems.append(f"{fake.__name__} does not implement {port.__name__}")
    return problems


def check_openapi(write: bool) -> list[str]:
    from app.main import create_app
    current = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if write:
        OPENAPI.write_text(current, encoding="utf-8")
        return []
    if not OPENAPI.exists() or OPENAPI.read_text(encoding="utf-8") != current:
        return ["contracts/openapi.json is out of date - run: python scripts/check_contracts.py --write"]
    return []


def main() -> int:
    problems = check_events() + check_fakes() + check_openapi("--write" in sys.argv)
    for p in problems:
        print("ERROR", p)
    print("contracts ok" if not problems else f"{len(problems)} contract problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
