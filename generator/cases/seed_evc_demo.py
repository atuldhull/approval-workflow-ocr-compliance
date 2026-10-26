"""Deterministic fictional EVC master data; no real people or selector decisions."""
import argparse
from datetime import timedelta
import sys
from uuid import NAMESPACE_URL, UUID, uuid5

from contracts.ports import ClockPort
from generator.cases.scale_generator import EPOCH, LogicalClock, ROOT


def demo_rows(clock: ClockPort, institution_refs: list[UUID]) -> dict:
    """Thirty DEMO experts, sixty days of AM/PM availability, three COIs."""
    if len(institution_refs) < 3 or len(set(institution_refs)) != len(institution_refs):
        raise ValueError("at least three distinct DEMO institution references are required")
    now = clock.now()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("logical clock must be timezone-aware")
    start = now.date()
    experts, availability, conflicts = [], [], []
    for index in range(30):
        expert = uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:expert:{index}")
        experts.append(dict(id=expert, user_ref=uuid5(NAMESPACE_URL, f"SIH26262:DEMO:EVC:user:{index}"),
            region=f"DEMO_REGION_{index % 9 + 1:02d}", expertise_tags=["DEMO", f"DEMO_DOMAIN_{index % 3 + 1:02d}"], active=True))
        for day in range(60):
            for part in ("AM", "PM"):
                availability.append(dict(expert_id=expert, date=start + timedelta(days=day), slot_part=part,
                                         available=(index + day) % 7 != 0))
        if index < 3:
            conflicts.append(dict(expert_id=expert, institution_ref=institution_refs[index],
                                  reason_code="DEMO_PRIOR_AFFILIATION", source="DEMO_SEEDED"))
    return dict(label="DEMO", simulation_status="SIMULATED", experts=experts, availability=availability, coi=conflicts)


def seed(session, clock: ClockPort, institution_refs: list[UUID]) -> dict[str, int]:
    """Idempotent bootstrap into evc only, in the caller's single transaction.

    Refuse conflicting pre-existing rows rather than overwriting curated data.
    Not a runtime expert-management/assignment command; it creates no schedules.
    """
    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy import select, tuple_
    from app.evc.models import Availability, Coi, Expert
    from app.platform.settings import settings
    from generator.cases.seed_demo import DEMO_INSTITUTIONS

    if not settings.demo_mode:
        raise ValueError("EVC bootstrap requires demo mode")
    rows = demo_rows(clock, institution_refs)
    if set(institution_refs) != {row[0] for row in DEMO_INSTITUTIONS}:
        raise ValueError("COIs require the three known fictional DEMO institution references")
    for model, name, key in ((Expert, "experts", ("id",)),
                             (Availability, "availability", ("expert_id", "date", "slot_part")),
                             (Coi, "coi", ("expert_id", "institution_ref", "reason_code", "source"))):
        values = rows[name]
        # Batches avoid excessive bind parameters; never access another owner's schema.
        for offset in range(0, len(values), 500):
            batch = values[offset:offset + 500]
            session.execute(insert(model).values(batch).on_conflict_do_nothing(index_elements=list(key)))
            identities = [tuple(row[k] for k in key) for row in batch]
            predicate = (getattr(model, key[0]).in_([i[0] for i in identities]) if len(key) == 1 else
                         tuple_(*(getattr(model, k) for k in key)).in_(identities))
            stored = {tuple(getattr(row, k) for k in key): row for row in session.scalars(select(model).where(predicate))}
            for identity, row in zip(identities, batch, strict=True):
                if any(getattr(stored[identity], field) != value for field, value in row.items()):
                    raise ValueError(f"conflicting DEMO bootstrap row in {name}")
    return {name: len(rows[name]) for name in ("experts", "availability", "coi")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--at", default=EPOCH, help="explicit timezone-aware logical instant")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import load_models
    from app.platform.db import new_session
    from generator.cases.seed_demo import DEMO_INSTITUTIONS

    load_models()
    with new_session() as session, session.begin():
        counts = seed(session, LogicalClock(args.at), [row[0] for row in DEMO_INSTITUTIONS])
    print(f"DEMO / SIMULATED EVC bootstrap: {counts}")


if __name__ == "__main__":
    main()
