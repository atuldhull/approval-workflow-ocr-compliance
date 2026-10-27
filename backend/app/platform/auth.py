"""Who is calling, and may they do this?

Demo auth reads X-Demo-* headers so the UI can switch roles. It is switched off with DEMO_AUTH=false,
and Keycloak (identity) + Cerbos (policy) replace it.
"""
from uuid import UUID

from fastapi import Header, HTTPException

from app.platform.settings import settings
from contracts.enums import Role
from contracts.errors import Forbidden
from contracts.types import Principal, ResourceRef

OFFICERS = {Role.SCRUTINY_COMMITTEE, Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD}
EVERYONE = set(Role)

# action -> roles allowed. Object-level rules are applied in Authz.check.
POLICY: dict[str, set[Role]] = {
    "evc.schedule.propose": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
    "evc.expert.register": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
    "evc.availability.set": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
    "evc.coi.record": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
    "evc.expert.read": {Role.RO_OFFICER, Role.BUREAU_OFFICER, Role.BUREAU_HEAD, Role.SCRUTINY_COMMITTEE, Role.AUDITOR},
    "institution.list": EVERYONE,
    "ruleset.read": EVERYONE,
    "application.create": {Role.INSTITUTION},
    "application.submit": {Role.INSTITUTION},
    "application.read": EVERYONE,
    "deadline.read": EVERYONE,
    "case.timeline": EVERYONE,
    "ledger.verify": {Role.AUDITOR, Role.BUREAU_OFFICER, Role.BUREAU_HEAD},
    "sim.clock": EVERYONE,
    "committee.create": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "committee.task.assign": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "committee.observation.add": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "committee.report.add": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "committee.read": EVERYONE,
    # Case actions are further constrained by the pinned YAML stage/guards.
    "case.submit": {Role.INSTITUTION},
    "case.advance": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "case.record_deficiency": {Role.SCRUTINY_COMMITTEE},
    "case.submit_compliance": {Role.INSTITUTION},
    "case.start_rescrutiny": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "case.advance_to_evc": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "case.complete_evc": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "case.advance_to_shc": {Role.SCRUTINY_COMMITTEE, Role.BUREAU_OFFICER},
    "case.issue_loa": {Role.BUREAU_OFFICER},
    "case.issue_eoa": {Role.BUREAU_OFFICER},
    "case.issue_lod": {Role.BUREAU_OFFICER},
    "case.reject": {Role.BUREAU_OFFICER},
    "case.withdraw": {Role.INSTITUTION},
    "case.revert": {Role.BUREAU_OFFICER},
}


class Authz:
    def check(self, principal: Principal, action: str, resource: ResourceRef) -> None:
        allowed = POLICY.get(action)
        if allowed is None:
            raise Forbidden(f"unknown action {action}")
        if principal.role not in allowed:
            raise Forbidden(f"{principal.role} may not {action}")
        # an institution only ever sees and acts on its own records
        if principal.role == Role.INSTITUTION and resource.owner_institution_id is not None:
            if principal.institution_id != resource.owner_institution_id:
                raise Forbidden("institution may only access its own records")
        if principal.role == Role.RO_OFFICER and resource.id is not None and resource.type == "application":
            if resource.region is not None or action.startswith("case."):
                if not principal.region or principal.region != resource.region:
                    raise Forbidden("regional officer may only access their own region")


def current_principal(
    x_demo_user: UUID | None = Header(default=None),
    x_demo_role: Role | None = Header(default=None),
    x_demo_institution: UUID | None = Header(default=None),
    x_demo_region: str | None = Header(default=None),
) -> Principal:
    if not settings.demo_auth:
        raise HTTPException(status_code=401, detail="identity provider not configured")
    if x_demo_user is None or x_demo_role is None:
        raise HTTPException(status_code=401, detail="X-Demo-User and X-Demo-Role headers are required")
    if x_demo_role == Role.INSTITUTION and x_demo_institution is None:
        raise HTTPException(status_code=401, detail="institution users need X-Demo-Institution")
    return Principal(user_id=x_demo_user, role=x_demo_role, region=x_demo_region,
                     institution_id=x_demo_institution)
