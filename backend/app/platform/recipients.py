"""Who an alert goes to.

Person 2 decides that an alert exists and for which role; the outbox row carries only an opaque `recipient_ref`.
Person 3 resolves that ref to people and addresses at delivery time, so alerts, events and replays never hold
contact details (see docs/NOTIFICATIONS.md for the proposed RecipientPort).

A recipient_ref is either one user's id or a role group. Role-group ids are deterministic, so the same
(role, region, institution) always maps to the same id - replay-safe and independent of who holds the post.
"""
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.platform.models import PersonalData, RecipientMember, UserContact
from contracts.enums import Role
from contracts.types import ResourceRef

_NAMESPACE = uuid5(NAMESPACE_URL, "urn:awoc:recipient-group")


def group_ref(role: Role, region: str | None = None, institution_id: UUID | None = None) -> UUID:
    return uuid5(_NAMESPACE, f"{role}|{region or '*'}|{institution_id or '*'}")


class RecipientDirectory:
    def resolve(self, role: Role, resource: ResourceRef) -> UUID:
        """The recipient group for `role` with respect to a record (proposed RecipientPort.resolve)."""
        if role == Role.INSTITUTION:
            return group_ref(role, institution_id=resource.owner_institution_id)
        if role == Role.RO_OFFICER:
            return group_ref(role, region=resource.region)
        return group_ref(role)

    def has_members(self, session: Session, recipient_ref: UUID) -> bool:
        """False means the post is vacant - the alert's owner can escalate instead (proposed RecipientPort)."""
        return session.scalar(select(exists().where(
            (RecipientMember.recipient_ref == recipient_ref) | (RecipientMember.user_id == recipient_ref)))) or False

    def members(self, session: Session, recipient_ref: UUID) -> list[UUID]:
        users = session.scalars(select(RecipientMember.user_id).where(RecipientMember.recipient_ref == recipient_ref)).all()
        return sorted(set(users)) or [recipient_ref]  # a ref with no group members is treated as a single user

    def addresses(self, session: Session, recipient_ref: UUID, channel: str) -> list[str]:
        rows = session.execute(
            select(PersonalData.data).join(UserContact, UserContact.personal_ref == PersonalData.id)
            .where(UserContact.user_id.in_(self.members(session, recipient_ref)), UserContact.channel == channel,
                   PersonalData.erased_at.is_(None))
        ).scalars().all()
        return sorted({d["address"] for d in rows if d and d.get("address")})

    def groups_of(self, session: Session, user_id: UUID) -> list[UUID]:
        return [user_id, *session.scalars(select(RecipientMember.recipient_ref).where(RecipientMember.user_id == user_id))]

    def add_member(self, session: Session, recipient_ref: UUID, user_id: UUID) -> None:
        session.execute(insert(RecipientMember).values(recipient_ref=recipient_ref, user_id=user_id)
                        .on_conflict_do_nothing())

    def set_contact(self, session: Session, user_id: UUID, channel: str, address: str) -> None:
        row = PersonalData(data={"address": address}, purpose=f"notification:{channel}")
        session.add(row)
        session.flush()
        session.execute(insert(UserContact).values(user_id=user_id, channel=channel, personal_ref=row.id)
                        .on_conflict_do_update(index_elements=["user_id", "channel"], set_={"personal_ref": row.id}))


directory = RecipientDirectory()
