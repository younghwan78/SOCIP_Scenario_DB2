from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph


@dataclass(frozen=True, slots=True)
class SimulationSocProfile:
    soc_id: str
    default_dvfs_groups: dict[str, str] = field(default_factory=dict)
    clock_policy: str = "otf_group_max_required_clock"
    power_domain_policy: str = "align_by_vdd_leader"
    external_device_policy: str = "catalog_external_modes"

    def as_dict(self) -> dict[str, Any]:
        return {
            "soc_id": self.soc_id,
            "default_dvfs_groups": dict(self.default_dvfs_groups),
            "clock_policy": self.clock_policy,
            "power_domain_policy": self.power_domain_policy,
            "external_device_policy": self.external_device_policy,
        }


_PROFILES: dict[str, SimulationSocProfile] = {
    "soc-exynos2600": SimulationSocProfile(
        soc_id="soc-exynos2600",
        default_dvfs_groups={
            "CSIS": "CSIS",
            "ISP": "CAM",
            "MCSC": "MCSC",
            "LME": "CAM",
            "MFC": "MFC",
            "DPU": "DISP",
            "CPU": "CPU",
        },
    ),
    "soc-exynos2500": SimulationSocProfile(
        soc_id="soc-exynos2500",
        default_dvfs_groups={
            "CSIS": "CAM",
            "ISP": "CAM",
            "MFC": "INT",
            "DPU": "INT",
            "LLC": "INT",
        },
    ),
}


def profile_for_graph(graph: CanonicalScenarioGraph) -> SimulationSocProfile:
    soc_id = getattr(graph.soc, "id", None)
    if not soc_id and graph.project is not None:
        metadata = getattr(graph.project, "metadata_", None) or {}
        globals_ = getattr(graph.project, "globals_", None) or {}
        soc_id = metadata.get("soc_ref") or globals_.get("soc_ref")
    return profile_for_soc_id(str(soc_id or "generic"))


def profile_for_soc_id(soc_id: str) -> SimulationSocProfile:
    return _PROFILES.get(soc_id, SimulationSocProfile(soc_id=soc_id))

