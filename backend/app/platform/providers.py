"""Delivery channels. Each provider either returns (delivered) or raises DeliveryError with a category.

Categories:
- TRANSIENT: nothing was delivered and a retry may work (connection refused, 4xx SMTP reply).
- PERMANENT: retrying cannot help (unknown template, no recipient, 5xx SMTP reply, not configured).
- AMBIGUOUS: the provider may or may not have delivered (timeout after the message was handed over). It is
  retried, so the recipient may get it twice: email and SMS delivery are at-least-once, never exactly-once.
"""
import json
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol
from uuid import UUID

TRANSIENT, PERMANENT, AMBIGUOUS = "TRANSIENT", "PERMANENT", "AMBIGUOUS"

# Fixed texts only. Messages never carry names, case details or free text - just a reference to sign in and see.
TEMPLATES: dict[str, tuple[str, str]] = {
    "deadline.reminder": ("Deadline reminder", "A deadline on a case you handle is approaching."),
    "deadline.breached": ("Deadline missed", "A deadline on a case you handle has passed."),
    "deadline.escalated": ("Deadline escalated", "An overdue case has been escalated to you."),
    "obligation.due": ("Compliance item due", "A compliance item for your institution is due."),
    "case.update": ("Case updated", "A case you follow has changed."),
}


class DeliveryError(Exception):
    def __init__(self, category: str, reason: str):
        super().__init__(f"{category}: {reason}")
        self.category, self.reason = category, reason


@dataclass(frozen=True)
class Message:
    outbox_id: UUID
    alert_id: UUID
    channel: str
    template: str
    addresses: tuple[str, ...]
    attempt: int


def render(template: str, alert_id: UUID) -> tuple[str, str]:
    try:
        subject, line = TEMPLATES[template]
    except KeyError:
        raise DeliveryError(PERMANENT, "UNKNOWN_TEMPLATE") from None
    return subject, f"{line}\nSign in to the approval portal to see it. Reference: {alert_id}\n"


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
        subject, body = render(msg.template, msg.alert_id)
        email = EmailMessage()
        email["From"], email["To"], email["Subject"] = self.sender, ", ".join(msg.addresses), subject
        # The same Message-ID on every retry lets receiving systems drop duplicates; not all of them do.
        email["Message-ID"] = f"<{msg.outbox_id}@awoc.example.invalid>"
        email.set_content(body)
        handed_over = False
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as s:
                if self.starttls:
                    s.starttls(context=ssl.create_default_context())
                handed_over = True  # from here on a failure may be after the server accepted the message
                s.send_message(email)
        except smtplib.SMTPRecipientsRefused:
            raise DeliveryError(PERMANENT, "RECIPIENT_REFUSED") from None
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
        _, body = render(msg.template, msg.alert_id)
        record = {"outbox_id": str(msg.outbox_id), "to": [a[:-4] + "****" for a in msg.addresses],
                  "text": body.strip()}
        self.sent.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        return f"mock-{msg.outbox_id}"


class FakeProvider:
    """Deterministic provider for tests: plays back a scripted list of outcomes (None = delivered)."""

    def __init__(self, name: str = "fake", script: list[str | None] | None = None):
        self.name = name
        self.script = list(script or [])
        self.sent: list[Message] = []

    def send(self, msg: Message) -> str | None:
        render(msg.template, msg.alert_id)
        outcome = self.script.pop(0) if self.script else None
        if outcome is not None:
            raise DeliveryError(outcome, f"SCRIPTED_{outcome}")
        self.sent.append(msg)
        return f"fake-{len(self.sent)}"
