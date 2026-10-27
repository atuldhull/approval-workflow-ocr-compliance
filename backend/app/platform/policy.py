"""Who may do what, to which records.

This table is the single source of truth for both policy engines: the local engine (auth.Authz) evaluates it
directly, and scripts/gen_cerbos_policies.py turns it into the Cerbos policies in infra/cerbos/policies/.
Anything not listed is denied.
"""
from contracts.enums import Role
from contracts.types import Principal, ResourceRef

R = Role
EVERYONE = frozenset(Role)
OFFICERS = frozenset({R.SCRUTINY_COMMITTEE, R.RO_OFFICER, R.BUREAU_OFFICER, R.BUREAU_HEAD})
OVERSIGHT = frozenset({R.AUDITOR, R.BUREAU_OFFICER, R.BUREAU_HEAD})

# action -> roles allowed. Object-level scope rules are in decide().
POLICY: dict[str, frozenset[Role]] = {
    "institution.list": EVERYONE,
    "ruleset.read": EVERYONE,
    "application.create": frozenset({R.INSTITUTION}),
    "application.submit": frozenset({R.INSTITUTION}),
    "application.read": EVERYONE,
    "deadline.read": EVERYONE,
    "case.timeline": EVERYONE,
    "ledger.verify": OVERSIGHT,
    "sim.clock": EVERYONE,
    "auth.me": EVERYONE,
    "audit.checkpoint.read": OVERSIGHT,
    "audit.checkpoint.create": frozenset({R.AUDITOR, R.BUREAU_HEAD}),
    "audit.replay": frozenset({R.AUDITOR, R.BUREAU_HEAD}),
    "notification.inbox": EVERYONE,
    "notification.ops": OVERSIGHT,
    "notification.retry": frozenset({R.BUREAU_HEAD}),
    "analytics.dashboard": OFFICERS | {R.AUDITOR},
    "analytics.scorecard": OVERSIGHT,
    "analytics.report": OFFICERS | {R.AUDITOR},
    "analytics.export": OVERSIGHT,
    # application documents (Person 2's endpoints). Facts are extracted by OCR and only proposals until an
    # officer reviews and confirms them; institutions upload and see their own documents' facts.
    "document.upload": frozenset({R.INSTITUTION}),
    # retrying a scan that never got an answer changes no content, so the officers handling the case may ask too
    "document.rescan": frozenset({R.INSTITUTION, R.RO_OFFICER, R.BUREAU_OFFICER, R.BUREAU_HEAD}),
    "document.facts.read": OFFICERS | {R.INSTITUTION, R.AUDITOR},
    "document.fact.review": frozenset({R.SCRUTINY_COMMITTEE, R.RO_OFFICER}),
    "document.fact.confirm": OFFICERS,
    # approval letters, the obligations they create and the evidence that meets them (Person 2's compliance
    # module). Letters are registered by the bureau; institutions submit evidence for their own obligations and
    # only a human officer decides whether it is accepted.
    "compliance.letter.register": frozenset({R.BUREAU_OFFICER, R.BUREAU_HEAD}),
    "compliance.read": OFFICERS | {R.INSTITUTION, R.AUDITOR},
    "compliance.evidence.submit": frozenset({R.INSTITUTION}),
    "compliance.evidence.verify": OFFICERS,
    # deadline alerts (Person 2). Institutions see and acknowledge only alerts about their own records; the
    # deadlines module also requires the acknowledging role to be the one the alert is addressed to.
    "alert.read": OFFICERS | {R.INSTITUTION, R.AUDITOR},
    "alert.ack": OFFICERS | {R.INSTITUTION},
}

# Resource kinds the policy knows. Any other kind is denied.
KINDS = frozenset({"institution", "ruleset", "application", "deadline", "ledger", "clock", "principal",
                   "audit", "notification", "analytics", "document", "compliance", "alert"})

# Records that belong to a regional office. A regional officer may touch them only when the caller states the
# region (resource.region) and it is the officer's own - including list queries, which must filter by it.
REGION_SCOPED_KINDS = frozenset({"application", "deadline", "analytics", "document", "compliance", "alert"})

DEMO_ONLY_ACTIONS = frozenset({"sim.clock"})


def precheck(action: str, resource: ResourceRef, demo_mode: bool) -> str | None:
    """Denials that do not depend on who is asking. Returns the reason, or None."""
    if action not in POLICY:
        return f"unknown action {action}"
    if resource.type not in KINDS:
        return f"unknown resource kind {resource.type}"
    if action in DEMO_ONLY_ACTIONS and not demo_mode:
        return f"{action} is only available in demo mode"
    return None


# Committee members should only touch the cases assigned to them. Assignment data does not exist yet (Person 1,
# contract change C3), so with AUTHZ_REQUIRE_ASSIGNMENT on (the production default) their case access is refused
# rather than assumed. Off in development so the demo keeps working - see docs/SECURITY.md.
ASSIGNMENT_SCOPED = {R.SCRUTINY_COMMITTEE: frozenset({"application", "deadline", "document", "compliance", "alert"})}


def assignment_guard(principal: Principal, resource: ResourceRef, require_assignment: bool) -> str | None:
    if require_assignment and resource.type in ASSIGNMENT_SCOPED.get(principal.role, ()):
        return "case assignments are not available yet, so committee access to cases is refused"
    return None


def decide(principal: Principal, action: str, resource: ResourceRef, demo_mode: bool,
           require_assignment: bool = False) -> str | None:
    """Returns why the request is denied, or None if it is allowed."""
    reason = precheck(action, resource, demo_mode) or assignment_guard(principal, resource, require_assignment)
    if reason:
        return reason
    if principal.role not in POLICY[action]:
        return f"{principal.role} may not {action}"

    if principal.role == R.INSTITUTION:
        # an institution only ever sees and acts on its own records
        if principal.institution_id is None:
            return "institution user has no institution"
        if resource.owner_institution_id is not None:
            if resource.owner_institution_id != principal.institution_id:
                return "institution may only access its own records"
        elif resource.id is not None:
            return "record owner unknown"

    if principal.role == R.RO_OFFICER:
        if not principal.region:
            return "regional officer has no region"
        if resource.type in REGION_SCOPED_KINDS or resource.region is not None:
            if resource.region != principal.region:
                return "regional officers may only access their own region"
    return None
