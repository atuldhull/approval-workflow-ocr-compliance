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
    # cl. 1.12: security-deposit proof and the affidavit after an LoA (timing is a demo assumption)
    LetterType.LOA: (
        ObligationTemplate(ObligationKind.DEPOSIT, "LOA_DEPOSIT_AFFIDAVIT_15D", StateOrigin.RULE_DEFAULT),
        ObligationTemplate(ObligationKind.AFFIDAVIT, "LOA_DEPOSIT_AFFIDAVIT_15D", StateOrigin.RULE_DEFAULT),
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
