"""DEMO ONLY: recipient groups and synthetic contacts for the demo accounts, plus optional sample messages.

    python -m app.platform.demo_seed                 # directory only (safe to rerun)
    python -m app.platform.demo_seed --sample-alerts # also queue messages about records already in the log

Refuses to run unless DEMO_MODE=true. Addresses use the reserved .invalid domain and 0000 numbers, so nothing can
reach a real person even if a provider were misconfigured.
"""
import argparse
import sys
from uuid import UUID

from app.platform.registry import port
from contracts.enums import Role
from contracts.types import OutboundMessage

SUNRISE = UUID("00000000-0000-4000-8000-000000000001")
NORTHFIELD = UUID("00000000-0000-4000-8000-000000000002")
U = lambda n: UUID(f"00000000-0000-4000-9000-{n:012d}")  # noqa: E731

# (user, role, region, institution, username)
DEMO_PEOPLE = [
    (U(1), Role.INSTITUTION, None, SUNRISE, "inst.sunrise"),
    (U(4), Role.INSTITUTION, None, NORTHFIELD, "inst.northfield"),
    (U(2), Role.SCRUTINY_COMMITTEE, None, None, "scrutiny"),
    (U(5), Role.RO_OFFICER, "Southern", None, "ro.southern"),
    (U(8), Role.RO_OFFICER, "Northern", None, "ro.northern"),
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


def sample_alerts(limit: int = 3) -> int:
    """Messages for the delivery demo, every one about a real record, so its links lead somewhere.

    Queues what notifications.yaml maps for the events already recorded, and a "case updated" message on every
    channel for the latest submitted applications (to their institution and regional office). Nothing is invented:
    with an empty log, nothing is queued. Safe to rerun - each message is unique per event, recipient and channel.
    """
    from sqlalchemy import text

    from app.platform import event_notices
    from app.platform.db import new_session
    from app.platform.recipients import directory, group_ref
    from contracts.errors import NotFound
    from contracts.ports import CasePort, ClockPort

    now = port(ClockPort).now()
    written = 0
    with new_session() as s:
        written += event_notices.dispatch(s, now, limit=10_000)
        submitted = s.execute(text(
            "SELECT id, aggregate_id FROM plat.domain_event WHERE event_type = 'wf.application_submitted' "
            "ORDER BY seq DESC LIMIT :n"), {"n": limit}).all()
        for event_id, app_id in submitted:
            try:
                case = port(CasePort).lookup(s, app_id)
            except NotFound:
                continue
            for ref in (group_ref(Role.INSTITUTION, institution_id=case.institution_id),
                        group_ref(Role.RO_OFFICER, case.region)):
                if not directory.has_members(s, ref):
                    continue
                for channel in ("in_app", "email", "sms"):
                    written += event_notices.queue(
                        s, OutboundMessage(None, channel, "case.update", ref, source_event_id=event_id), now)
        s.commit()
    return written


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
        print(f"queued {sample_alerts()} messages about recorded events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
