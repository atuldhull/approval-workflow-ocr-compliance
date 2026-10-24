"""DEMO ONLY: recipient groups and synthetic contacts for the demo accounts, plus optional sample alerts.

    python -m app.platform.demo_seed                 # directory only (safe to rerun)
    python -m app.platform.demo_seed --sample-alerts # also queue a few synthetic alerts for the delivery demo

Refuses to run unless DEMO_MODE=true. Addresses use the reserved .invalid domain and 0000 numbers, so nothing can
reach a real person even if a provider were misconfigured.
"""
import argparse
import sys
from uuid import UUID, uuid4

from app.platform.registry import port
from contracts.enums import Role
from contracts.ports import OutboxPort
from contracts.types import OutboundMessage, Principal

SUNRISE = UUID("00000000-0000-4000-8000-000000000001")
NORTHFIELD = UUID("00000000-0000-4000-8000-000000000002")
U = lambda n: UUID(f"00000000-0000-4000-9000-{n:012d}")  # noqa: E731

# (user, role, region, institution, username)
DEMO_PEOPLE = [
    (U(1), Role.INSTITUTION, None, SUNRISE, "inst.sunrise"),
    (U(4), Role.INSTITUTION, None, NORTHFIELD, "inst.northfield"),
    (U(2), Role.SCRUTINY_COMMITTEE, None, None, "scrutiny"),
    (U(5), Role.RO_OFFICER, "Southern", None, "ro.southern"),
    (U(6), Role.BUREAU_OFFICER, None, None, "bureau.officer"),
    (U(7), Role.BUREAU_HEAD, None, None, "bureau.head"),
    (U(3), Role.AUDITOR, None, None, "auditor"),
]


def seed_directory() -> int:
    from app.platform.db import new_session
    from app.platform.models import UserContact
    from app.platform.recipients import directory, group_ref
    from sqlalchemy import select

    with new_session() as s:
        for i, (user, role, region, inst, name) in enumerate(DEMO_PEOPLE, start=1):
            directory.add_member(s, group_ref(role, region, inst), user)
            if s.scalar(select(UserContact).where(UserContact.user_id == user)) is None:
                directory.set_contact(s, user, "email", f"{name}@awoc.example.invalid")
                directory.set_contact(s, user, "sms", f"+91000000{i:04d}")
        s.commit()
    return len(DEMO_PEOPLE)


def sample_alerts() -> int:
    from app.platform.db import unit_of_work
    from app.platform.recipients import group_ref

    system = Principal(UUID(int=0), Role.SYSTEM)
    southern_ro = group_ref(Role.RO_OFFICER, "Southern")
    sunrise = group_ref(Role.INSTITUTION, institution_id=SUNRISE)
    with unit_of_work(system) as uow:
        for template, ref in (("deadline.reminder", sunrise), ("deadline.breached", southern_ro),
                              ("deadline.escalated", group_ref(Role.BUREAU_HEAD))):
            alert = uuid4()
            for channel in ("in_app", "email", "sms"):
                port(OutboxPort).enqueue(uow, OutboundMessage(alert, channel, template, ref))
    return 3


def main() -> int:
    from app.main import create_app
    from app.platform.settings import settings

    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-alerts", action="store_true")
    args = ap.parse_args()
    if not settings.demo_mode:
        print("refusing: DEMO_MODE is not enabled")
        return 1
    create_app()
    print(f"seeded recipient directory for {seed_directory()} demo accounts")
    if args.sample_alerts:
        print(f"queued {sample_alerts()} synthetic alerts on 3 channels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
