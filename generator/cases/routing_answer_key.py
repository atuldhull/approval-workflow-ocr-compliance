"""Routing answer key for the analytics scorecard, transcribed from the frozen docs/p1/expected_routes.csv.

The CSV is the route oracle used by the acceptance tests; it is never derived from routes.yaml. This script only
reshapes it into the routing.json format that app.analytics.scorecard reads from ANSWER_KEYS_DIR
(default generator/answer_keys). Stage names are compared as listed; an "as applicable" stage (SHC?) is kept as
a stage name and also listed under as_applicable_stages.

    python -m generator.cases.routing_answer_key           # write generator/answer_keys/routing.json
    python -m generator.cases.routing_answer_key --check    # fail if the file is out of date
"""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "docs" / "p1" / "expected_routes.csv"
OUTPUT = ROOT / "generator" / "answer_keys" / "routing.json"
SOURCE = ("Frozen docs/p1/expected_routes.csv: a manual transcription of APH 2024-27 Table 2.3 (21 categories) and "
          "Chapter I (NEW_INSTITUTION). DEMO ASSUMPTION ACCEPTANCE_SOURCE_UNVERIFIED: the primary source was not "
          "available, so no row is verified against the official handbook (PRIMARY_SOURCE_UNAVAILABLE).")


def build(csv_path: Path = CSV_PATH) -> dict:
    raw = csv_path.read_bytes()
    rows = list(csv.DictReader(raw.decode("utf-8").splitlines()))
    cases = []
    for row in rows:
        stages = row["stages"].split(";")
        cases.append({
            "category": row["route_id"],
            "expected_stages": [stage.rstrip("?") for stage in stages],
            "as_applicable_stages": [stage.rstrip("?") for stage in stages if stage.endswith("?")],
            "evc": row["evc"] == "YES",
            "source_table": row["source_table"],
            "source_verification": row["source_verification"],
            "assumption_ref": row["assumption_ref"],
        })
    return {
        "source": SOURCE,
        "source_status": "DEMO_ASSUMPTION",
        "source_verification": "PRIMARY_SOURCE_UNAVAILABLE",
        "assumption_ref": "ACCEPTANCE_SOURCE_UNVERIFIED",
        "generated_from": "docs/p1/expected_routes.csv",
        "generated_from_sha256": sha256(raw).hexdigest(),
        "cases": cases,
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if routing.json differs from the CSV")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else None
        if current != text:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; run python -m generator.cases.routing_answer_key")
            return 1
        print("routing answer key ok")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(build()['cases'])} categories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
