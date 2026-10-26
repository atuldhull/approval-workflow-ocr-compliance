"""Replay and verify a P1 DEMO seed against actual workflow/clock observations."""
import argparse
from pathlib import Path
import tempfile

from generator.cases.scale_generator import canonical, generate
from generator.cases.verification import compare


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--institutions", type=int, default=300)
    parser.add_argument("--applications", type=int, default=600)
    parser.add_argument("--regions", type=int, default=9)
    parser.add_argument("--out", type=Path, help="new output directory; defaults to a seed directory in the OS temp folder")
    args = parser.parse_args(argv)
    out = args.out or Path(tempfile.gettempdir()) / f"sih26262-verify-seed-{args.seed}"
    try:
        from generator.cases.verification_runtime import preflight, replay

        preflight()
        data, answer = generate(args.seed, args.institutions, args.applications, args.regions)
        if out.exists():
            raise ValueError(f"output directory already exists: {out}")
        out.mkdir(parents=True)
        for name, value in (("seed_data.json", data), ("answer_key.json", answer)):
            (out / name).write_bytes(canonical(value))
        receipt, actual = replay(data, answer)
        result = compare(answer, receipt, actual)
        for name, value in (("receipt.json", receipt), ("observations.json", actual), ("verification.json", result)):
            (out / name).write_bytes(canonical(value))
        print(f"DEMO seed {args.seed}: {result['status']} — {result['mismatch_count']} mismatches; "
              f"{len(receipt['applications'])} applications")
        for mismatch in result["mismatches"]:
            print(canonical(mismatch).decode("utf-8").rstrip())
        print(f"Letters: {result['coverage']['letters']}; P2/P3 extensions: NOT_SUPPLIED; artifacts: {out}")
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(f"DEMO seed {args.seed}: ERROR — {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
