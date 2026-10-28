"""Inbox for every signed-in user, and delivery operations for oversight roles. No contact details are exposed."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.platform import notifier
from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.models import DeliveryAttempt, Notification, Outbox
from app.platform.providers import TEMPLATES, describe
from app.platform.recipients import directory
from app.platform.registry import port
from contracts.errors import NotFound
from contracts.ports import AuthzPort, ClockPort
from contracts.types import Principal, ResourceRef

router = APIRouter(prefix="/notifications", tags=["notifications"])
NOTIFICATIONS = ResourceRef("notification")


class InboxLinks(BaseModel):
    """Records the message is about, for the screen to open. Present only when the record was found."""
    application_id: UUID | None = None
    obligation_id: UUID | None = None
    evc_request_id: UUID | None = None


class InboxItem(BaseModel):
    id: UUID
    alert_id: UUID | None = Field(description="the deadline alert this message is about, if it is an alert")
    source_event_id: UUID | None = Field(default=None, description="the recorded event this message is about, "
                                                                     "if it is not an alert")
    template: str
    subject: str
    text: str = Field(description="what happened: the case, the rule in words and the due date (IST) when known")
    action: str = Field(description="what to do about it")
    case_ref: str | None = Field(default=None, description="short case reference (first 8 characters of its id)")
    links: InboxLinks
    created_at: datetime
    read_at: datetime | None


class OutboxItem(BaseModel):
    id: UUID
    alert_id: UUID | None
    source_event_id: UUID | None = None
    channel: str
    template: str
    status: str
    attempts: int
    last_error: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None
    dead_at: datetime | None


class AttemptItem(BaseModel):
    attempt_no: int
    worker: str
    provider: str
    started_at: datetime
    finished_at: datetime
    outcome: str
    error_category: str | None


def _item(n: Notification) -> InboxItem:
    context = n.context or {}
    if n.template in TEMPLATES:
        subject, said, action = describe(n.template, context)
    else:
        subject, said, action = "Notification", "A notification from the approval system.", "Sign in to see it."
    return InboxItem(id=n.id, alert_id=n.alert_id, source_event_id=n.source_event_id, template=n.template,
                     subject=subject, text=said, action=action, case_ref=context.get("case"),
                     links=InboxLinks(**{k: context[k] for k in InboxLinks.model_fields if context.get(k)}),
                     created_at=n.created_at, read_at=n.read_at)


@router.get("/inbox", response_model=list[InboxItem])
def inbox(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "notification.inbox", NOTIFICATIONS)
    with new_session() as s:
        rows = s.scalars(select(Notification).where(Notification.recipient_ref.in_(directory.groups_of(s, principal.user_id)))
                         .order_by(Notification.created_at.desc()).limit(200)).all()
        return [_item(n) for n in rows]


@router.post("/inbox/{notification_id}/read", response_model=InboxItem)
def mark_read(notification_id: UUID, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "notification.inbox", NOTIFICATIONS)
    with new_session() as s:
        n = s.get(Notification, notification_id)
        if n is None or n.recipient_ref not in directory.groups_of(s, principal.user_id):
            raise NotFound("notification not found")  # someone else's notification looks the same as a missing one
        if n.read_at is None:
            n.read_at = port(ClockPort).now()
            s.commit()
        return _item(n)


@router.get("/health")
def delivery_health(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "notification.ops", NOTIFICATIONS)
    return notifier.health(port(ClockPort).now())


@router.get("/outbox", response_model=list[OutboxItem])
def outbox(status: str | None = Query(default=None, pattern="^(PENDING|SENDING|DELIVERED|DEAD)$"),
           principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "notification.ops", NOTIFICATIONS)
    with new_session() as s:
        q = select(Outbox).order_by(Outbox.created_at.desc()).limit(200)
        if status:
            q = q.where(Outbox.status == status)
        return [OutboxItem.model_validate(o, from_attributes=True) for o in s.scalars(q).all()]


@router.get("/outbox/{outbox_id}/attempts", response_model=list[AttemptItem])
def attempts(outbox_id: UUID, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "notification.ops", NOTIFICATIONS)
    with new_session() as s:
        rows = s.scalars(select(DeliveryAttempt).where(DeliveryAttempt.outbox_id == outbox_id)
                         .order_by(DeliveryAttempt.finished_at)).all()
        return [AttemptItem.model_validate(a, from_attributes=True) for a in rows]


@router.post("/outbox/{outbox_id}/retry", response_model=dict)
def retry(outbox_id: UUID, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "notification.retry", NOTIFICATIONS)
    if not notifier.requeue(outbox_id, port(ClockPort).now()):
        raise NotFound("no dead-lettered message with that id")
    return {"requeued": str(outbox_id)}
