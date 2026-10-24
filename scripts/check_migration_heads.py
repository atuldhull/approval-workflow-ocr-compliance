"""Fails if any module's migration chain has more than one head, or a chain lacks its branch label.

Each module keeps its own chain on purpose; an accidental fork inside one module must be resolved.
"""
import sys
from collections import defaultdict
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
INI = ROOT / "backend" / "alembic.ini"


def main() -> int:
    script = ScriptDirectory.from_config(Config(str(INI)))
    heads, bases = defaultdict(list), defaultdict(list)
    for rev in script.walk_revisions():
        module = Path(rev.path).parent.name
        if rev.is_head:
            heads[module].append(rev.revision)
        if rev.is_base:
            bases[module].append(rev)

    problems = []
    for module, revs in heads.items():
        if len(revs) > 1:
            problems.append(f"{module}: {len(revs)} heads {revs} - merge them into one")
    for module, revs in bases.items():
        for rev in revs:
            if module not in (rev.branch_labels or ()):
                problems.append(f"{module}: base revision {rev.revision} needs branch_labels=('{module}',)")
        if len(revs) > 1:
            problems.append(f"{module}: {len(revs)} base revisions - a module has exactly one chain")

    for p in problems:
        print("ERROR", p)
    print(f"checked {len(heads)} migration chains")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
