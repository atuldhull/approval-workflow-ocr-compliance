from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_key: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]
    state: Literal["PROVIDED", "MISSING"] = "PROVIDED"
    document_ref: UUID | None = None

    @model_validator(mode="after")
    def reference_matches_state(self):
        if (self.state == "PROVIDED") != (self.document_ref is not None):
            raise ValueError("PROVIDED requires a document_ref; MISSING requires null")
        return self


class ItemsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ItemIn] = Field(min_length=1)


class SubmissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dsc_present: Annotated[bool, Field(strict=True)] = False


class SubmissionErrorOut(BaseModel):
    error: Literal["ValidationFailed"]
    detail: Literal["MANDATORY_ITEMS_MISSING"]
    reason_code: Literal["MANDATORY_ITEMS_MISSING"]
    missing_item_keys: list[str]


class SubmissionInputErrorOut(BaseModel):
    detail: list[dict]


class ItemOut(BaseModel):
    item_key: str
    mandatory: bool
    state: Literal["PROVIDED", "MISSING"]
    document_ref: UUID | None


class ItemsOut(BaseModel):
    application_id: UUID
    items: list[ItemOut]
    dsc_required: bool
    assumptions: list[str]
