"""Delivery channels. Each provider either returns (delivered) or raises DeliveryError with a category.

Categories:
- TRANSIENT: nothing was delivered and a retry may work (connection refused, 4xx SMTP reply).
- PERMANENT: retrying cannot help (unknown template, no recipient, 5xx SMTP reply, not configured).
- AMBIGUOUS: the provider may or may not have delivered (timeout after the message was handed over). It is
  retried, so the recipient may get it twice: email and SMS delivery are at-least-once, never exactly-once.
"""
import json
from hashlib import sha256
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import NamedTuple, Protocol
from uuid import UUID

TRANSIENT, PERMANENT, AMBIGUOUS = "TRANSIENT", "PERMANENT", "AMBIGUOUS"

class Template(NamedTuple):
    """Fixed wording. `lines` name the case, the rule and the due date from the message context; a line is left out
    when the context lacks one of its fields, and `generic` is used when the first line cannot be filled.
    Context values are short case references, rule names, kinds and dates - never names, addresses or free text."""
    subject: str
    generic: str
    lines: tuple[str, ...]
    action: str


TEMPLATES: dict[str, Template] = {
    "deadline.reminder": Template(
        "Deadline reminder", "A deadline on a case you handle is approaching.",
        ("Case {case}: {rule} is due on {due} (IST).", "Document: {document}."),
        "Act on the case before the due date, then acknowledge this alert on the Alerts screen."),
    "deadline.breached": Template(
        "Deadline missed", "A deadline on a case you handle has passed.",
        ("Case {case}: {rule} was due on {due} (IST) and has passed.", "Document: {document}."),
        "Act on the case now and acknowledge this alert on the Alerts screen."),
    "deadline.escalated": Template(
        "Deadline escalated", "An overdue case has been escalated to you.",
        ("Case {case}: {rule}, due on {due} (IST), is overdue and has been escalated to you.",
         "Document: {document}."),
        "Review the case and acknowledge this alert on the Alerts screen."),
    "deadline.missed": Template(
        "Deadline missed on your case", "A deadline your role is responsible for has passed.",
        ("Case {case}: {rule} was due on {due} (IST) and has passed.", "Document: {document}."),
        "Act on the case now; until then the alert ladder escalates it."),
    "obligation.due": Template(
        "Compliance item due", "A compliance item for your institution is due.",
        ("Case {case}: the {obligation} is due on {due} (IST) under {rule}.", "Document: {document}."),
        "Submit the evidence on the Compliance screen before the due date."),
    "case.update": Template(
        "Case updated", "A case you follow has changed.",
        ("Case {case}: {change}.",),
        "Open the case to see what changed."),
    "case.deficiency_recorded": Template(
        "Deficiencies recorded", "Deficiencies were recorded on one of your applications.",
        ("Case {case}: {items} deficiency item(s) recorded in round {round}.", "Due date: {due} (IST), set by {rule}."),
        "Answer each item and submit your compliance on the case before the due date."),
    "evc.visit_scheduled": Template(
        "Expert visit scheduled", "An expert visit has been scheduled for a case.",
        ("Case {case}: the expert visit is scheduled for {visit} ({slot}).", "Due date: {due} (IST), set by {rule}."),
        "Prepare for the visit; the case's EVC panel shows the schedule."),
    "compliance.evidence_accepted": Template(
        "Evidence accepted", "Evidence your institution submitted was accepted.",
        ("Case {case}: the evidence for the {obligation} was accepted.",),
        "Nothing more is needed for this item."),
    "compliance.evidence_rejected": Template(
        "Evidence rejected", "Evidence your institution submitted was rejected.",
        ("Case {case}: the evidence for the {obligation} was rejected ({reason}).", "It is due on {due} (IST)."),
        "Submit new evidence on the Compliance screen before the due date."),
    "letter.registered": Template(
        "Letter registered", "A letter was registered for one of your applications.",
        ("Case {case}: {letter} dated {issued} has been registered.",),
        "See the letter and any obligations it creates on the Compliance screen."),
}


class DeliveryError(Exception):
    """per_recipient: the failure concerns this one recipient (e.g. mailbox refused), not the message or provider.
    Only such failures mark a recipient as refused; anything else stops the run for the whole message."""

    def __init__(self, category: str, reason: str, per_recipient: bool = False):
        super().__init__(f"{category}: {reason}")
        self.category, self.reason, self.per_recipient = category, reason, per_recipient


@dataclass(frozen=True)
class Message:
    outbox_id: UUID
    alert_id: UUID | None
    channel: str
    template: str
    addresses: tuple[str, ...]
    attempt: int
    source_event_id: UUID | None = None
    context: dict | None = None

    @property
    def reference(self) -> UUID | None:
        return self.alert_id or self.source_event_id


def _fill(line: str, context: dict) -> str | None:
    try:
        return line.format_map(context)
    except (KeyError, ValueError, IndexError):
        return None


def describe(template: str, context: dict | None = None) -> tuple[str, str, str]:
    """(subject, what happened, what to do) for a template and the message's context."""
    try:
        t = TEMPLATES[template]
    except KeyError:
        raise DeliveryError(PERMANENT, "UNKNOWN_TEMPLATE") from None
    filled = [_fill(line, context) for line in t.lines] if context else [None]
    text = " ".join(f for f in filled if f) if filled[0] else t.generic
    return t.subject, text, t.action


def render(template: str, reference: UUID | None, context: dict | None = None) -> tuple[str, str]:
    subject, text, action = describe(template, context)
    return subject, f"{text}\n{action}\nSign in to the approval portal to see it. Reference: {reference}\n"


class Provider(Protocol):
    name: str

    def send(self, msg: Message) -> str | None: ...  # provider reference, if any


class SmtpProvider:
    name = "smtp"

    def __init__(self, host: str, port: int, sender: str, starttls: bool = False, timeout: float = 10.0):
        self.host, self.port, self.sender, self.starttls, self.timeout = host, port, sender, starttls, timeout

    def send(self, msg: Message) -> str | None:
        if not self.host:
            raise DeliveryError(PERMANENT, "NOT_CONFIGURED")
        if len(msg.addresses) != 1:
            # one message per recipient, so no recipient ever sees another's address (the notifier splits them)
            raise ValueError("SmtpProvider sends to exactly one recipient per message")
        (to,) = msg.addresses
        subject, body = render(msg.template, msg.reference, msg.context)
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = self.sender, to, subject
        # Stable per (message, recipient) across retries, so receiving systems can drop duplicates; not all do.
        email["Message-ID"] = f"<{msg.outbox_id}.{sha256(to.encode()).hexdigest()[:12]}@awoc.example.invalid>"
        email.set_content(body)
        handed_over = False
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                if self.starttls:
                    s.starttls(context=ssl.create_default_context())
                handed_over = True  # from here on a failure may be after the server accepted the message
                s.send_message(email)
        except smtplib.SMTPRecipientsRefused:
            raise DeliveryError(PERMANENT, "RECIPIENT_REFUSED", per_recipient=True) from None
        except smtplib.SMTPResponseException as e:
            raise DeliveryError(PERMANENT if 500 <= e.smtp_code < 600 else TRANSIENT, f"SMTP_{e.smtp_code}") from None
        except (socket.timeout, TimeoutError, smtplib.SMTPServerDisconnected):
            raise DeliveryError(AMBIGUOUS if handed_over else TRANSIENT, "TIMEOUT_OR_DISCONNECT") from None
        except OSError:
            raise DeliveryError(TRANSIENT, "CONNECTION_FAILED") from None
        return email["Message-ID"]


class MockSmsProvider:
    """Never contacts a gateway. Appends what would have been sent to a local JSONL file (or keeps it in memory)."""
    name = "sms-mock"

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        self.sent: list[dict] = []

    def send(self, msg: Message) -> str | None:
        _, body = render(msg.template, msg.reference, msg.context)
        record = {"outbox_id": str(msg.outbox_id), "to": [a[:-4] + "****" for a in msg.addresses],
                  "text": body.strip()}
        self.sent.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        return f"mock-{msg.outbox_id}"


class FakeProvider:
    """Deterministic provider for tests: plays back a scripted list of outcomes per send.
    None = delivered; "REFUSED" = this recipient refused; TRANSIENT / PERMANENT / AMBIGUOUS = message-level."""

    def __init__(self, name: str = "fake", script: list[str | None] | None = None):
        self.name = name
        self.script = list(script or [])
        self.sent: list[Message] = []

    def send(self, msg: Message) -> str | None:
        render(msg.template, msg.reference, msg.context)
        outcome = self.script.pop(0) if self.script else None
        if outcome == "REFUSED":   # this recipient is refused; other recipients are unaffected
            raise DeliveryError(PERMANENT, "SCRIPTED_REFUSED", per_recipient=True)
        if outcome is not None:
            raise DeliveryError(outcome, f"SCRIPTED_{outcome}")
        self.sent.append(msg)
        return f"fake-{len(self.sent)}"
