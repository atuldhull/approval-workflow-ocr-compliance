"""Strict validation for explicitly fictional Annexure-2 stand-ins."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from contracts.errors import ValidationFailed

Code = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(Record):
    item_key: Code
    mandatory: Annotated[bool, Field(strict=True)]


class Checklist(Record):
    status: Literal["DEMO_ASSUMPTION"]
    label: Literal["DEMO ASSUMPTION"]
    assumption_refs: list[Code] = Field(min_length=1)
    dsc_required: Annotated[bool, Field(strict=True)]
    items: list[Item] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [i.item_key for i in self.items]
        if len(keys) != len(set(keys)) or "DSC" in keys:
            raise ValueError("duplicate or reserved checklist key")
        return self


class Document(Record):
    schema_version: Literal[1]
    checklists: dict[Code, Checklist]


class Citation(Record):
    """Where a route comes from. VERIFIED: the clause (and Table 2.3 row) was checked against the handbook text on
    that PDF page. Anything else stays a DEMO_ASSUMPTION with the assumption it rests on."""
    source_document: Code
    locator: Code
    clause: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 .;()/_-]*$", max_length=40)]
    status: Literal["DEMO_ASSUMPTION", "VERIFIED"]
    row: Annotated[int, Field(strict=True, ge=1)] | None = None
    page: Annotated[int, Field(strict=True, ge=1)] | None = None
    assumption_ref: Code | None = None

    @model_validator(mode="after")
    def sourced(self):
        if self.status == "VERIFIED" and (self.page is None or self.assumption_ref is not None):
            raise ValueError("a verified citation names its page and rests on no assumption")
        if self.status == "DEMO_ASSUMPTION" and self.assumption_ref is None:
            raise ValueError("a demo-assumption citation names its assumption")
        return self


def validate_checklists(raw: dict, categories: set[str]) -> dict:
    try:
        result = Document.model_validate(raw)
        if set(result.checklists) != categories:
            raise ValueError("checklist categories must exactly match routes")
        return {key: value.model_dump(mode="json") for key, value in sorted(result.checklists.items())}
    except (ValidationError, ValueError) as exc:
        raise ValidationFailed(f"invalid demo checklists: {exc}") from None
