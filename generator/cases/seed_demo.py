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


def seed_scale_institutions(rows: list[dict]) -> int:
    """Bootstrap only P1 master data; applications/actions must use the API.

    No public institution-create endpoint exists. Call explicitly in a disposable
    demo environment after migration; never use this as a general import API.
    """
    from app.platform.settings import settings

    if not settings.demo_mode:
        raise ValueError("scale institution bootstrap requires demo mode")
    for row in rows:
        if row["label"] != "DEMO" or not row["name"].startswith("DEMO ") or not row["region"].startswith("DEMO_REGION_"):
            raise ValueError("only fictional DEMO institutions are allowed")
        UUID(row["id"])
    load_models()
    with new_session() as session, session.begin():
        for row in rows:
            session.execute(insert(Institution).values(id=UUID(row["id"]), name=row["name"],
                ro_region=row["region"], is_demo=True).on_conflict_do_nothing(index_elements=["id"]))
    return len(rows)


if __name__ == "__main__":
    print(f"seeded {seed()} demo institutions")
