"""Bounded inputs for prediction notes and append-only comments."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class PredictionNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    title: str = Field(default="", max_length=200)
    purpose: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=10000)
    assumptions: str = Field(default="", max_length=10000)
    conclusion: str = Field(default="", max_length=10000)
    tags: list[Tag] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def unique_tags(cls, tags: list[str]) -> list[str]:
        return list(dict.fromkeys(tags))


class PredictionCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    parent_id: str | None = Field(default=None, min_length=1, max_length=200)
