"""Shared vocabularies. Every module uses these values; nobody invents their own copies."""
from enum import StrEnum


class Role(StrEnum):
    INSTITUTION = "INSTITUTION"
    SCRUTINY_COMMITTEE = "SCRUTINY_COMMITTEE"
    RO_OFFICER = "RO_OFFICER"
    BUREAU_OFFICER = "BUREAU_OFFICER"
    BUREAU_HEAD = "BUREAU_HEAD"
    AUDITOR = "AUDITOR"
    SYSTEM = "SYSTEM"


class Stage(StrEnum):
    SELF_DISCLOSURE = "SELF_DISCLOSURE"
    SCRUTINY = "SCRUTINY"
    RESCRUTINY = "RESCRUTINY"
    DEFICIENT = "DEFICIENT"
    EVC = "EVC"
    SHC = "SHC"
    EC = "EC"
    COUNCIL = "COUNCIL"
    SAC = "SAC"  # Standing Appellate Committee: hears an appeal against an LoD (APH cl. 1.11, 2.24)


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_PROCESS = "IN_PROCESS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClockKind(StrEnum):
    LEGAL = "LEGAL"        # set by the handbook or a letter; never paused by workflow actions
    INTERNAL = "INTERNAL"  # processing timer; may pause while the other side holds the case


class ClockOwner(StrEnum):
    AICTE = "AICTE"
    INSTITUTION = "INSTITUTION"
    COMMITTEE = "COMMITTEE"


class DeadlineStatus(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    MET = "MET"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"
    EXTENDED = "EXTENDED"


class FactState(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class ObligationKind(StrEnum):
    UNDERTAKING = "UNDERTAKING"
    AFFIDAVIT = "AFFIDAVIT"
    LETTER_CONDITION = "LETTER_CONDITION"
    DEPOSIT = "DEPOSIT"
    DOCUMENT_VALIDITY = "DOCUMENT_VALIDITY"
    RECURRING_FILING = "RECURRING_FILING"


class LetterType(StrEnum):
    LOA = "LOA"
    EOA = "EOA"
    LOD = "LOD"
    LOR = "LOR"
    CORRIGENDUM = "CORRIGENDUM"


# Every event_type starts with one of these prefixes, e.g. "wf.application_submitted".
MODULE_PREFIXES = frozenset({"wf", "evc", "doc", "cmp", "dl", "plat"})
