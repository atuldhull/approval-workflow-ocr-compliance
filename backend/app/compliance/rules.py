"""Which obligations a registered letter creates.

Each obligation names the deadline rule (rulesets/<ruleset>/<rev>/deadlines.yaml) that times it; the rule's
source status travels onto the obligation, so a demo assumption is never shown as handbook fact.
"""
from collections.abc import Callable
from dataclasses import dataclass

from app.compliance.vocab import StateOrigin
from contracts.enums import LetterType, ObligationKind
from contracts.types import LetterIn


@dataclass(frozen=True)
class ObligationTemplate:
    kind: ObligationKind
    rule_id: str
    origin: StateOrigin
    applies: Callable[[LetterIn], bool] = lambda letter: True


OBLIGATIONS_BY_LETTER: dict[LetterType, tuple[ObligationTemplate, ...]] = {
    # cl. 2.25(f): the security deposit and Affidavit 3 within 15 days of the LoA; Affidavit 3 item 5 (p.205): the
    # remaining requirements within one month of it. (These replace the earlier demo rule LOA_DEPOSIT_AFFIDAVIT_15D.)
    LetterType.LOA: (
        ObligationTemplate(ObligationKind.DEPOSIT, "DEPOSIT_15D", StateOrigin.RULE_DEFAULT),
        ObligationTemplate(ObligationKind.AFFIDAVIT, "DEPOSIT_15D", StateOrigin.RULE_DEFAULT),
        ObligationTemplate(ObligationKind.UNDERTAKING, "AFFIDAVIT3_REMAINING_1M", StateOrigin.RULE_DEFAULT),
    ),
    # "comply within six months from the date of issue" is printed only on EoAs that list deficiencies. The
    # registering bureau officer confirms that the letter lists them, so the condition is officer-confirmed.
    LetterType.EOA: (
        ObligationTemplate(ObligationKind.LETTER_CONDITION, "EOA_DEFICIENCY_6M", StateOrigin.OFFICER_CONFIRMED,
                           applies=lambda letter: letter.lists_deficiencies),
    ),
}

# The LoA's own validity is a clock on the letter, not something the institution has to evidence.
LETTER_VALIDITY_RULES: dict[LetterType, str] = {LetterType.LOA: "LOA_VALIDITY_2Y"}


def obligations_for(letter: LetterIn) -> tuple[ObligationTemplate, ...]:
    return tuple(t for t in OBLIGATIONS_BY_LETTER.get(letter.letter_type, ()) if t.applies(letter))


# ---- document validity (APH cl. 6.17) ----

@dataclass(frozen=True)
class ValidityDocument:
    clause: str                     # the APH clause that requires the document to be valid
    lease: bool = False             # land lease: EoA stop year (2.1(e)) and live lease at submission (6.17(a))
    period_rule: str | None = None  # a validity period the APH sets, counted from the document's issue date


# Document types (checklist item codes) whose expiry is tracked, by the clause that requires them to be valid. The
# expiry date is read from the document; only the structural stability certificate has an APH period.
VALIDITY_DOCUMENTS: dict[str, ValidityDocument] = {
    "LEASE_DEED": ValidityDocument("6.17(a)", lease=True),
    "LAND_DEED": ValidityDocument("6.17(a)", lease=True),   # ownership or registered lease; only a lease expires
    "BUILDING_COMPLETION": ValidityDocument("6.17(g)"),     # occupancy / completion certificate
    "STRUCTURAL_STABILITY": ValidityDocument("6.17(h)", period_rule="STRUCTURAL_STABILITY_VALIDITY"),
    "FIRE_NOC": ValidityDocument("6.17(i)"),                # fire safety certificate
}
VALIDITY_RULE = "DOCUMENT_EXPIRY"
LEASE_STOP_RULE = "LEASE_EOA_STOP"
# confirmed facts that give the date a document is valid until, and the issue date an APH period counts from
LEASE_END_FIELD, VALID_UNTIL_FIELD, ISSUE_DATE_FIELD = "lease_end_date", "valid_until", "certificate_issue_date"
# an officer records other obligations against a rule that allows it, or with the date the undertaking states
RECORDED_DUE_DATE_RULE = "UNDERTAKING_DUE_DATE"
