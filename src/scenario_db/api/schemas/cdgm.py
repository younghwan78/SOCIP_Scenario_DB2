from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from scenario_db.models.common import DocumentId


class CdgmResolveRequest(BaseModel):
    scenario_id: str
    variant_id: str
    soc_ref: DocumentId | None = None
    dvfs_table_ref: DocumentId | None = None
    dvfs_version: int | None = None
    cdgm_profile_ref: DocumentId | None = None
    cdgm_profile_version: int | None = None


class CdgmResolveResponse(BaseModel):
    scenario_id: str
    variant_id: str
    soc_ref: str | None = None
    dvfs_table_ref: str | None = None
    cdgm_profile_ref: str | None = None
    arch_info_rows: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)

