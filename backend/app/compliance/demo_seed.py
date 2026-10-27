"""DEMO ONLY: synthetic approval letters whose obligations fall due relative to the demo clock.

    python -m app.compliance.demo_seed      # needs DEMO_MODE=true; safe to rerun

Each letter gets its own new DEMO application for a fictional institution (generator/cases/seed_demo.py) and is
dated from ClockPort.now(), never from a fixed calendar date, so its obligations come out with due dates in the
future. One letter is deliberately dated far enough back that its obligations are already overdue, for the
escalation demo. The deadline rules themselves are not changed: each due date is still the rule's duration from
the letter's issue date. Every letter is labelled DEMO in its letter number.
"""
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from app.compliance.models import ApprovalLetter
from app.compliance.rules import OBLIGATIONS_BY_LETTER
from app.compliance.service import IST, register_letter
from app.platform.registry import port
from contracts.enums import LetterType, Role
from contracts.ports import ClockPort, RulesetPort
from contracts.types import LetterIn, Principal

SUNRISE = UUID("00000000-0000-4000-8000-000000000001")
NORTHFIELD = UUID("00000000-0000-4000-8000-000000000002")
U = lambda n: UUID(f"00000000-0000-4000-9000-{n:012d}")  # noqa: E731
INSTITUTION_USERS = {SUNRISE: U(1), NORTHFIELD: U(4)}
BUREAU = Principal(U(6), Role.BUREAU_OFFICER)
F_NO_PREFIX = "F.No. DEMO-SEED/"
OVERDUE_BY_DAYS = 5


@dataclass(frozen=True)
class DemoLetter:
    key: str
    institution_id: UUID
    overdue: bool  # False: issued two days ago, so its obligations are due in the future


DEMO_LETTERS = (
    DemoLetter("SOUTH-CURRENT", SUNRISE, overdue=False),
    DemoLetter("NORTH-CURRENT", NORTHFIELD, overdue=False),
    DemoLetter("SOUTH-OVERDUE", SUNRISE, overdue=True),
)


def academic_year(day: date) -> str:
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def longest_obligation_days() -> int:
    """The longest calendar-day duration of the obligations an LoA opens, read from the pinned deadline rules."""
    rules = port(RulesetPort).get(port(RulesetPort).default_key()).deadline_rules
    days = [rules[t.rule_id].duration.value for t in OBLIGATIONS_BY_LETTER[LetterType.LOA]
            if rules[t.rule_id].duration is not None and rules[t.rule_id].duration.unit == "calendar_days"]
    if not days:
        raise RuntimeError("no calendar-day LoA obligation rule to date the demo letters from")
    return max(days)


def issue_date_for(letter: DemoLetter, today: date) -> date:
    if letter.overdue:
        return today - timedelta(days=longest_obligation_days() + OVERDUE_BY_DAYS)
    return today - timedelta(days=2)


def seed_letters() -> list[UUID]:
    """Registers the demo letters that do not exist yet. Returns the ids of the letters created now."""
    from app.intake.rules import plan
    from app.intake.service import create_application, mark_items, submit_application
    from app.intake.shapes import ItemIn
    from app.platform.db import new_session, unit_of_work

    today = port(ClockPort).now().astimezone(IST).date()
    year = academic_year(today)
    created = []
    for letter in DEMO_LETTERS:
        f_no = f"{F_NO_PREFIX}{letter.key}/{year}"
        with new_session() as session:
            if session.scalar(select(ApprovalLetter.id).where(ApprovalLetter.f_no == f_no)) is not None:
                continue
        institution = Principal(INSTITUTION_USERS[letter.institution_id], Role.INSTITUTION,
                                institution_id=letter.institution_id)
        with unit_of_work(institution) as uow:
            app_id = create_application(uow, letter.institution_id, "NEW_PROGRAMME", year).id
        with unit_of_work(institution) as uow:
            # submission goes through intake: every mandatory checklist item provided (fictional DEMO document
            # references) and the DSC present
            checklist = plan(uow.session, "NEW_PROGRAMME", port(RulesetPort).default_key()).checklist
            mark_items(uow, app_id, [
                ItemIn(item_key=item["item_key"],
                       document_ref=uuid5(NAMESPACE_URL, f"DEMO:seed-document:{app_id}:{item['item_key']}"))
                for item in checklist["items"] if item["mandatory"]])
            submit_application(uow, app_id, dsc_present=True)
        with unit_of_work(BUREAU) as uow:
            row = register_letter(uow, LetterIn(
                application_id=app_id, institution_id=letter.institution_id, letter_type=LetterType.LOA,
                academic_year=year, issue_date=issue_date_for(letter, today), issue_date_source="PORTAL_EVENT",
                lists_deficiencies=False, f_no=f_no))
            created.append(row.id)
    return created


def main() -> int:
    from app.main import create_app
    from app.platform.settings import settings

    if not settings.demo_mode:
        print("refusing: DEMO_MODE is not enabled")
        return 1
    create_app()
    created = seed_letters()
    print(f"registered {len(created)} DEMO approval letter(s); "
          f"{len(DEMO_LETTERS) - len(created)} already existed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
