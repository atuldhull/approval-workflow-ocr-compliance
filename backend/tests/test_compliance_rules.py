"""Database-free checks of which obligations a letter creates and how letter provenance is validated.

A confirmed issue-date fact cannot be produced in PostgreSQL yet (OCR needs a scanner-approved version), so the
CONFIRMED_FACT path is exercised here against an in-memory session.
"""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.compliance import service
from app.compliance.rules import obligations_for
from app.documents.models import DocumentVersion, Fact
from app.platform.registry import port
from contracts.enums import LetterType, ObligationKind
from contracts.errors import ValidationFailed
from contracts.ports import RulesetPort
from contracts.types import LetterIn

APP, INST = uuid4(), uuid4()
LETTER = LetterIn(application_id=APP, institution_id=INST, letter_type=LetterType.EOA, academic_year="2025-26",
                  issue_date=date(2025, 8, 31), issue_date_source="CONFIRMED_FACT", lists_deficiencies=True)


class Session:
    def __init__(self, *rows):
        self.rows = {(type_, key): row for type_, key, row in rows}

    def get(self, model, key, **_):
        return self.rows.get((model, key))


def uow(*rows):
    return SimpleNamespace(session=Session(*rows))


def fact_rows(state="CONFIRMED", value="2025-08-31", app=APP):
    version_id, fact_id = uuid4(), uuid4()
    version = SimpleNamespace(document_version_id=version_id, application_id=app, status="QUARANTINED")
    fact = SimpleNamespace(fact_id=fact_id, document_version_id=version_id, state=state, reviewed_value=value)
    return fact_id, version_id, [(DocumentVersion, version_id, version), (Fact, fact_id, fact)]


def kinds(letter):
    return [t.kind for t in obligations_for(letter)]


def test_obligation_templates_per_letter_type():
    assert kinds(replace(LETTER, letter_type=LetterType.LOA)) == [ObligationKind.DEPOSIT, ObligationKind.AFFIDAVIT]
    assert kinds(LETTER) == [ObligationKind.LETTER_CONDITION]
    assert kinds(replace(LETTER, lists_deficiencies=False)) == []
    for other in (LetterType.LOD, LetterType.LOR, LetterType.CORRIGENDUM):
        assert kinds(replace(LETTER, letter_type=other)) == []


def test_every_template_rule_exists_in_the_default_ruleset(client):
    rules = port(RulesetPort).get(port(RulesetPort).default_key()).deadline_rules
    for rule_id in ("LOA_DEPOSIT_AFFIDAVIT_15D", "NO_ADMISSION_AFFIDAVIT_7D", "LOA_VALIDITY_2Y", "EOA_DEFICIENCY_6M"):
        assert rules[rule_id].duration is not None
    for rule_id in ("LOA_DEPOSIT_AFFIDAVIT_15D", "NO_ADMISSION_AFFIDAVIT_7D", "LOA_VALIDITY_2Y"):
        assert rules[rule_id].source_status == "demo_assumption"


def test_a_confirmed_fact_provides_the_issue_date():
    fact_id, version_id, rows = fact_rows()
    letter = replace(LETTER, issue_date_fact_id=fact_id, document_version_id=version_id, f_no=" F.No. X ")
    assert service._check_provenance(uow(*rows), letter) == "F.No. X"
    fact_id, _, rows = fact_rows(state="CORRECTED")  # an officer-corrected date counts as confirmed
    assert service._check_provenance(uow(*rows), replace(LETTER, issue_date_fact_id=fact_id)) is None


@pytest.mark.parametrize("problem", ["proposed", "rejected", "other_date", "other_application", "other_version"])
def test_an_unconfirmed_or_mismatched_fact_blocks_registration(problem):
    fact_id, version_id, rows = fact_rows(
        state={"proposed": "PROPOSED", "rejected": "REJECTED"}.get(problem, "CONFIRMED"),
        value="2025-09-01" if problem == "other_date" else "2025-08-31",
        app=uuid4() if problem == "other_application" else APP)
    letter = replace(LETTER, issue_date_fact_id=fact_id,
                     document_version_id=uuid4() if problem == "other_version" else None)
    if problem == "other_version":
        rows.append((DocumentVersion, letter.document_version_id,
                     SimpleNamespace(application_id=APP, status="QUARANTINED")))
    with pytest.raises(ValidationFailed):
        service._check_provenance(uow(*rows), letter)


def test_unknown_issue_date_source_is_refused():
    with pytest.raises(ValidationFailed):
        service._check_provenance(uow(), replace(LETTER, issue_date_source="EMAIL"))
