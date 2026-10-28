from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.platform.auth import current_principal
from app.platform.db import new_session
from app.platform.idempotency import idempotency_key, idempotent_response
from app.platform.registry import port
from app.workflow.loader import sync_at_startup
from app.workflow import appeal, case_service, summary
from app.workflow import deficiency
from app.workflow import committee
from app.workflow.commands import WorkflowValidationFailed
from app.workflow.case_api_models import ActionIn, CaseActionOut, CaseErrorOut, CaseOut, CasePageOut, ERROR_RESPONSES
from app.workflow.models import Ruleset
from contracts.enums import ApplicationStatus, Stage
from contracts.errors import NotFound
from contracts.ports import AuthzPort, RulesetPort
from contracts.types import Principal, ResourceRef

router = APIRouter()


def _json(model: BaseModel):
    return model.model_dump(mode="json")


router.include_router(committee.router)
router.add_event_handler("startup", sync_at_startup)


@router.get("/cases/{application_id}/deficiencies", response_model=deficiency.DeficienciesOut,
            tags=["deficiencies"], responses=ERROR_RESPONSES)
def get_deficiencies(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return deficiency.read(session, application_id, principal)


@router.get("/cases/{application_id}/rescrutiny", response_model=deficiency.RescrutinyOut,
            tags=["deficiencies"], responses=ERROR_RESPONSES)
def get_rescrutiny(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return deficiency.rescrutiny(session, application_id, principal)


@router.post("/cases/{application_id}/deficiencies/{deficiency_id}/review", response_model=deficiency.DeficienciesOut,
             tags=["deficiencies"], responses=ERROR_RESPONSES, description="Optional Idempotency-Key (replay/422/409).")
def review_deficiency(application_id: UUID, deficiency_id: UUID, body: deficiency.ReviewIn,
                      principal: Principal = Depends(current_principal), key: str | None = Depends(idempotency_key)):
    return idempotent_response(principal, key, "POST", "/cases/{application_id}/deficiencies/{deficiency_id}/review",
        {"application_id": str(application_id), "deficiency_id": str(deficiency_id)}, body.model_dump(mode="json"),
        lambda uow: deficiency.review(uow, application_id, deficiency_id, body), _json)


class StageOut(BaseModel):
    stage: str
    when: str


class RouteOut(BaseModel):
    category: str
    label: str
    stages: list[StageOut]


class RulesetOut(BaseModel):
    key: str
    status: str
    banner: str | None
    is_default: bool
    routes: list[RouteOut]


@router.get("/rulesets/{key}", response_model=RulesetOut, tags=["rulesets"])
def get_ruleset(key: str, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    registry = port(RulesetPort)
    rs = registry.get(key)
    return RulesetOut(
        key=rs.key, status=rs.status, banner=rs.banner, is_default=rs.key == registry.default_key(),
        routes=[RouteOut(category=r.category, label=r.label,
                         stages=[StageOut(stage=s.stage, when=s.when) for s in r.stages])
                for r in rs.routes.values()],
    )


class ChecklistItemOut(BaseModel):
    item_key: str
    mandatory: bool


class ChecklistOut(BaseModel):
    ruleset_key: str
    category: str
    status: Literal["DEMO_ASSUMPTION"]
    label: Literal["DEMO ASSUMPTION"]
    assumption_refs: list[str]
    dsc_required: bool
    items: list[ChecklistItemOut]


@router.get("/rulesets/{key}/checklists/{category}", response_model=ChecklistOut, tags=["rulesets"],
            responses={404: {"model": CaseErrorOut}},
            description="Read-only document checklist of one category, as pinned when the ruleset was loaded. "
                        "Items are DEMO ASSUMPTION stand-ins for Annexure 2, not an official list.")
def get_checklist(key: str, category: str, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    with new_session() as session:
        metadata = session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == key))
    if metadata is None:
        raise NotFound(f"ruleset {key} is not loaded")
    checklist = (metadata.get("intake") or {}).get(category)
    if checklist is None:
        raise NotFound(f"category {category} has no checklist in {key}")
    return ChecklistOut(ruleset_key=key, category=category, status=checklist["status"], label=checklist["label"],
                        assumption_refs=checklist["assumption_refs"], dsc_required=checklist["dsc_required"],
                        items=[ChecklistItemOut(**item) for item in checklist["items"]])


class DeficiencyVocabularyOut(BaseModel):
    ruleset_key: str
    item_keys: list[str]
    reason_codes: list[str]
    response_rule_id: str
    source_status: Literal["DEMO_ASSUMPTION"]
    assumption_code: str


@router.get("/rulesets/{key}/deficiency-vocabulary", response_model=DeficiencyVocabularyOut, tags=["rulesets"],
            responses={404: {"model": CaseErrorOut}},
            description="Coded deficiency item kinds and reason codes a deficiency may use under this ruleset, as pinned "
                        "when it was loaded (DEMO ASSUMPTION stand-ins, not an official list). 404 when the ruleset is not "
                        "loaded or has no deficiency configuration.")
def get_deficiency_vocabulary(key: str, principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    with new_session() as session:
        metadata = session.scalar(select(Ruleset.source_metadata).where(Ruleset.key == key))
    if metadata is None:
        raise NotFound(f"ruleset {key} is not loaded")
    config = metadata.get("deficiency")
    if config is None:
        raise NotFound(f"ruleset {key} has no deficiency configuration")
    return DeficiencyVocabularyOut(ruleset_key=key, item_keys=list(config["item_keys"]),
        reason_codes=list(config["reason_codes"]), response_rule_id=config["response_rule_id"],
        source_status=config["source_status"], assumption_code=config["assumption_code"])


@router.get("/rulesets", response_model=list[str], tags=["rulesets"])
def list_rulesets(principal: Principal = Depends(current_principal)):
    port(AuthzPort).check(principal, "ruleset.read", ResourceRef("ruleset"))
    return port(RulesetPort).available()


@router.post("/cases/{application_id}/actions", response_model=CaseActionOut, tags=["cases"], responses=ERROR_RESPONSES,
             description="Apply one versioned action atomically. Optional Idempotency-Key: a retry with the same key and "
                         "body replays the stored response with Idempotent-Replayed: true; the same key with a different "
                         "body is 422, and 409 while the first request still holds the key. Without a key, reusing a "
                         "consumed expected_version returns 409. Guard facts come only from trusted server records; "
                         "unavailable facts reject the action.")
def case_action(application_id: UUID, body: ActionIn, principal: Principal = Depends(current_principal),
                key: str | None = Depends(idempotency_key)):
    try:
        return idempotent_response(principal, key, "POST", "/cases/{application_id}/actions",
            {"application_id": str(application_id)}, body.model_dump(mode="json"),
            lambda uow: case_service.apply_action(uow, application_id, body), _json)
    except WorkflowValidationFailed as exc:
        if exc.reason_code != "MANDATORY_ITEMS_MISSING":
            raise
        return JSONResponse(status_code=422, content={"error": "ValidationFailed", "detail": exc.reason_code,
            "reason_code": exc.reason_code, "missing_item_keys": list(exc.missing_item_keys)})


@router.get("/cases", response_model=CasePageOut, tags=["cases"], responses=ERROR_RESPONSES)
def cases(region: str | None = Query(default=None, min_length=1, max_length=100), stage: Stage | None = None,
          status: ApplicationStatus | None = None, offset: int = Query(default=0, ge=0),
          limit: int = Query(default=50, ge=1, le=100), principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return case_service.list_cases(session, principal, region=region, stage=stage, status=status, offset=offset, limit=limit)


@router.get("/cases/{application_id}/summary", response_model=summary.CaseSummaryOut, tags=["cases"],
            responses=ERROR_RESPONSES,
            description="Electronic case summary for review and printing: identity, route and its citation, stage "
                        "visits with outcomes and reason codes, deficiency rounds, committees with report versions "
                        "(fingerprints only), EVC requests and published visits, open deadlines, obligations, letters "
                        "and the appeal. Scoped like the case; sections the role may not read are listed in withheld.")
def case_summary(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return summary.read(session, application_id, principal)


@router.get("/cases/{application_id}/appeal", response_model=appeal.CaseAppealOut, tags=["cases"],
            responses=ERROR_RESPONSES,
            description="The appeal against the case's LoD (APH cl. 1.11 / 2.24), or null when none was opened: window "
                        "clock and days left, filing, SAC recommendation and the Council's decision. Grounds and the "
                        "speaking order appear as note hashes only. Scoped like the case.")
def case_appeal(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return appeal.read(session, application_id, principal)


@router.get("/cases/{application_id}", response_model=CaseOut, tags=["cases"], responses=ERROR_RESPONSES)
def case_detail(application_id: UUID, principal: Principal = Depends(current_principal)):
    with new_session() as session:
        return case_service.read_case(session, application_id, principal)
