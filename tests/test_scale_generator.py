"""Scale artifacts are deterministic; JSON schema and semantics are both checked."""
from collections import Counter
from datetime import datetime
import json
import subprocess
import sys

from jsonschema import Draft202012Validator, FormatChecker
import pytest

from generator.cases.answer_key_models import AnswerKey
from generator.cases.scale_generator import ROOT, LogicalClock, canonical, generate, sources, write_seed

FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def check_instant(value):
    if isinstance(value, str):
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    return True


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_default_counts_distribution_coverage_schema_and_repeatability(seed):
    data, answer = generate(seed)
    assert canonical(data) == canonical(generate(seed)[0])
    assert canonical(answer) == canonical(generate(seed)[1])
    assert len(data["institutions"]) == 300 and len(data["applications"]) == 600
    assert len({i["ro_id"] for i in data["institutions"]}) == 9
    assert all(i["label"] == "DEMO" and i["name"].startswith("DEMO ") for i in data["institutions"])
    counts = Counter(a["category"] for a in data["applications"])
    assert len(counts) == 22 and max(counts.values()) - min(counts.values()) <= 1
    assert all(abs(count - 600 / 22) < 1 for count in counts.values())
    workflows = answer["workflow_expectations"]
    assert {w["deficiency_loop_count"] for w in workflows} == {0, 1, 2, 3}
    assert answer["header"]["counts"]["late_responses"] > 0
    assert answer["header"]["counts"]["evc_delays"] > 0
    assert {w["route_outcome"]["expected_status"] for w in workflows} == {"REJECTED", "WITHDRAWN"}
    assert answer["p2_extensions"] == answer["p3_extensions"] == {}
    schema = json.loads((ROOT / "docs/p1/answer_key.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FORMATS).validate(answer)
    AnswerKey.model_validate(answer)
    raw, _, _ = sources()
    for app, workflow in zip(data["applications"], workflows, strict=True):
        stages = [dict(stage=s, when="always") if isinstance(s, str) else s for s in raw["routes"][app["category"]]["stages"]]
        assert workflow["route_outcome"]["expected_stage_list"] == stages
    assert canonical(data) != canonical(generate(seed + 1)[0])
    assert canonical(answer) != canonical(generate(seed + 1)[1])


def test_files_and_cli_are_byte_identical(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    write_seed(first, 1, 9, 22)
    subprocess.run([sys.executable, "-m", "generator.cases.scale_generator", "--seed", "1", "--out", str(second),
                    "--institutions", "9", "--applications", "22"], check=True, cwd=ROOT)
    for name in ("seed_data.json", "answer_key.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    with pytest.raises(FileExistsError):
        write_seed(first, 2)


@pytest.mark.parametrize("kwargs", [dict(seed=-1), dict(seed=True), dict(institutions=0), dict(applications=0),
    dict(regions=0), dict(regions=10), dict(institutions=2, regions=3)])
def test_invalid_sizes_fail_before_writing(kwargs):
    with pytest.raises(ValueError):
        generate(**({"seed": 1} | kwargs))


def test_logical_clock_cannot_rewind():
    clock = LogicalClock()
    clock.tick()
    with pytest.raises(ValueError):
        clock.move_to("2026-07-01T04:30:00Z")
    with pytest.raises(ValueError):
        clock.tick(-1)


def test_documented_mix_matches_default_allocation():
    data, _ = generate(1)
    document = (ROOT / "docs/p1/category_mix.md").read_text(encoding="utf-8")
    rows = {parts[1].strip(): int(parts[3].strip()) for line in document.splitlines()
            if line.startswith("| ") and (parts := line.split("|"))[2].strip() == "1"}
    assert rows == data["category_counts"]
