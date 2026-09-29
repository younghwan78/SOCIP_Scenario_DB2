"""Validation of compiled canonical documents (no database required).

Level 0: pydantic schema per kind (same models the ETL mappers use)
Level 1: referential integrity across documents
Level 2: pipeline graph (data-flow cycle, edge buffers, size anchors)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from scenario_db.graph_checks import find_data_flow_cycle
from scenario_db.integrity_checks import (
    IpModeCatalog,
    VariantOverlayTarget,
    operating_mode_ids_from_capabilities,
    validate_variant_overlay_targets,
)
from scenario_db.models import sensor as sensor_models
from scenario_db.models.capability.hw import IpCatalog, SocCdgmProfile, SocDvfsTable, SocPlatform
from scenario_db.models.capability.power_model import PowerModelParams
from scenario_db.models.capability.sim_config import SimConfigProfile
from scenario_db.models.capability.sw import SwComponent, SwProfile
from scenario_db.models.definition.project import Project
from scenario_db.models.definition.usecase import Usecase

MODEL_BY_KIND: dict[str, type[BaseModel]] = {
    "ip": IpCatalog,
    "soc": SocPlatform,
    "soc.dvfs_table": SocDvfsTable,
    "soc.cdgm_profile": SocCdgmProfile,
    "power_model_params": PowerModelParams,
    "sw_profile": SwProfile,
    "sw_component": SwComponent,
    "sim.config_profile": SimConfigProfile,
    "project": Project,
    "scenario.usecase": Usecase,
    "sensor.catalog": sensor_models.SensorCatalog,
    "sensor.timing_profile": sensor_models.SensorTimingProfile,
    "sensor.board_lineup": sensor_models.SensorBoardLineup,
}


def validate_documents(docs: list[Any]) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    by_kind: dict[str, list[dict]] = {}
    for d in docs:
        data = d.data
        if not isinstance(data, dict) or "kind" not in data:
            continue
        by_kind.setdefault(data["kind"], []).append(data)
        model = MODEL_BY_KIND.get(data["kind"])
        if model is None:
            warnings.append(f"{d.rel}: no model for kind {data['kind']}")
            continue
        try:
            model.model_validate(data)
        except ValidationError as exc:
            first = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
            errors.append(f"{d.rel}: schema: {first}")

    ids = {k: {x["id"] for x in v if "id" in x} for k, v in by_kind.items()}
    ip_ids = ids.get("ip", set())
    soc_ids = ids.get("soc", set())
    project_ids = ids.get("project", set())

    for soc in by_kind.get("soc", []):
        for ref in soc.get("ips") or []:
            if isinstance(ref, dict) and ref.get("ref") not in ip_ids:
                errors.append(f"{soc['id']}: ips ref '{ref.get('ref')}' not found")
    for proj in by_kind.get("project", []):
        meta = proj.get("metadata") or {}
        if meta.get("soc_ref") not in soc_ids:
            errors.append(f"{proj['id']}: soc_ref '{meta.get('soc_ref')}' not found")
        for key in ("sensor_module_ref", "display_module_ref"):
            if meta.get(key) and meta[key] not in ip_ids:
                errors.append(f"{proj['id']}: {key} '{meta[key]}' not found")
    for cfg in by_kind.get("sim.config_profile", []):
        if cfg.get("project_ref") not in project_ids:
            errors.append(f"{cfg['id']}: project_ref '{cfg.get('project_ref')}' not found")
        if cfg.get("soc_ref") and cfg["soc_ref"] not in soc_ids:
            errors.append(f"{cfg['id']}: soc_ref '{cfg['soc_ref']}' not found")

    for pmp in by_kind.get("power_model_params", []):
        if pmp.get("soc_ref") not in soc_ids:
            errors.append(f"{pmp['id']}: soc_ref '{pmp.get('soc_ref')}' not found")

    ip_modes = IpModeCatalog({
        ip["id"]: operating_mode_ids_from_capabilities(ip.get("capabilities") or {})
        for ip in by_kind.get("ip", []) if "id" in ip
    })
    targets = [
        VariantOverlayTarget(
            scenario_id=uc["id"], variant_id=v["id"], base_pipeline=uc.get("pipeline") or {},
            node_configs=v.get("node_configs") or {}, buffer_overrides=v.get("buffer_overrides") or {},
            topology_patch=v.get("topology_patch") or {},
        )
        for uc in by_kind.get("scenario.usecase", []) for v in (uc.get("variants") or [])
    ]
    for issue in validate_variant_overlay_targets(targets, ip_modes):
        line = f"{issue.document_id}: {issue.code}: {issue.message}"
        (errors if issue.severity == "error" else warnings).append(line)

    for uc in by_kind.get("scenario.usecase", []):
        uid = uc["id"]
        if uc.get("project_ref") not in project_ids:
            errors.append(f"{uid}: project_ref '{uc.get('project_ref')}' not found")
        pipe = uc.get("pipeline") or {}
        nodes = pipe.get("nodes") or []
        for n in nodes:
            if n.get("ip_ref") not in ip_ids:
                errors.append(f"{uid}: node '{n.get('id')}' ip_ref '{n.get('ip_ref')}' not found")
        cycle = find_data_flow_cycle(nodes, pipe.get("edges") or [])
        if cycle:
            errors.append(f"{uid}: data-flow cycle {' -> '.join(cycle)}")
        buffers = set((pipe.get("buffers") or {}).keys())
        for e in pipe.get("edges") or []:
            if e.get("buffer") and e["buffer"] not in buffers:
                warnings.append(f"{uid}: edge {e.get('from')}->{e.get('to')} buffer '{e['buffer']}' "
                                "not in pipeline.buffers")
        anchors = set(((uc.get("size_profile") or {}).get("anchors") or {}).keys())
        for v in uc.get("variants") or []:
            anchors |= set((v.get("size_overrides") or {}).keys())
        for name, buf in (pipe.get("buffers") or {}).items():
            ref = buf.get("size_ref") if isinstance(buf, dict) else None
            if ref and ref not in anchors:
                warnings.append(f"{uid}: buffer '{name}' size_ref '{ref}' not a known anchor")
    return {"errors": errors, "warnings": warnings}
