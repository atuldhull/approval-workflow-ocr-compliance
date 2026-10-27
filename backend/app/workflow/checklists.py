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
    source_document: Code
    locator: Code
    clause: Code
    status: Literal["DEMO_ASSUMPTION"]
    assumption_ref: Code


def validate_checklists(raw: dict, categories: set[str]) -> dict:
    try:
        result = Document.model_validate(raw)
        if set(result.checklists) != categories:
            raise ValueError("checklist categories must exactly match routes")
        return {key: value.model_dump(mode="json") for key, value in sorted(result.checklists.items())}
    except (ValidationError, ValueError) as exc:
        raise ValidationFailed(f"invalid demo checklists: {exc}") from None
