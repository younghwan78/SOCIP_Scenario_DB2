from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IpResolution(BaseModel):
    node_id: str
    ip_ref: str | None = None
    requested: dict = {}
    matched_mode: str | None = None
    capability_max: dict = {}
    headroom: dict = {}
    violations: list[dict] = []
    status: Literal["PASS", "WARN", "FAIL"] = "PASS"


class ResolverResult(BaseModel):
    scenario_id: str
    variant_id: str
    ip_resolutions: dict[str, IpResolution] = {}
    sw_resolutions: dict = {}
    memory_resolutions: dict = {}
    unresolved_requirements: list[dict] = []
    warnings: list[str] = []

    @property
    def has_failures(self) -> bool:
        return any(r.status == "FAIL" for r in self.ip_resolutions.values())

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings) or any(r.status == "WARN" for r in self.ip_resolutions.values())

