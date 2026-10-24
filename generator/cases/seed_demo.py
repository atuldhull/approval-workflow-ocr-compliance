"""Seeds fictional DEMO institutions. Synthetic data only - never real institutions or people.

Run from the repo root:  python generator/cases/seed_demo.py
"""
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.main import load_models  # noqa: E402
from app.intake.models import Institution  # noqa: E402
from app.platform.db import new_session  # noqa: E402

DEMO_INSTITUTIONS = [
    (UUID("00000000-0000-4000-8000-000000000001"), "Sunrise Institute of Technology (DEMO)", "Southern"),
    (UUID("00000000-0000-4000-8000-000000000002"), "Northfield College of Engineering (DEMO)", "Northern"),
    (UUID("00000000-0000-4000-8000-000000000003"), "Riverbend Institute of Management (DEMO)", "Western"),
]


def seed() -> int:
    load_models()
    with new_session() as session:
        for iid, name, region in DEMO_INSTITUTIONS:
            session.execute(insert(Institution).values(id=iid, name=name, ro_region=region, is_demo=True)
                            .on_conflict_do_nothing(index_elements=["id"]))
        session.commit()
    return len(DEMO_INSTITUTIONS)


if __name__ == "__main__":
    print(f"seeded {seed()} demo institutions")
