"""Vocabularies owned by the compliance module.

The rejection reasons are this module's proposed list, pending team approval of the shared reason-code
vocabulary. They are stable codes: explanatory text goes to the note store, never into a code.
"""
from enum import StrEnum


class Decision(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectionReason(StrEnum):
    DOCUMENT_ILLEGIBLE = "DOCUMENT_ILLEGIBLE"
    DOCUMENT_INCOMPLETE = "DOCUMENT_INCOMPLETE"
    WRONG_DOCUMENT = "WRONG_DOCUMENT"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    DATE_MISMATCH = "DATE_MISMATCH"
    DOCUMENT_EXPIRED = "DOCUMENT_EXPIRED"
    SIGNATURE_OR_ATTESTATION_MISSING = "SIGNATURE_OR_ATTESTATION_MISSING"
    OTHER_SEE_NOTE = "OTHER_SEE_NOTE"  # only with a note explaining it


class ObligationStatus(StrEnum):
    OPEN = "OPEN"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    MET = "MET"  # an officer accepted evidence; acknowledging a letter is never enough


class StateOrigin(StrEnum):
    OFFICER_CONFIRMED = "OFFICER_CONFIRMED"  # a human officer confirmed the fact that creates it
    RULE_DEFAULT = "RULE_DEFAULT"  # created by the configured rules for this letter type
