from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from scenario_db.legacy_import.read_legacy import read_yaml
from scenario_db.legacy_import.report import ImportReport


def load_legacy_hw(path: Path, report: ImportReport) -> list[dict[str, Any]]:
    raw = read_yaml(path)
    if not isinstance(raw, list):
        report.error(
            "legacy_hw_not_list",
            "Legacy HW config must be a YAML list of IP blocks.",
            str(path),
        )
        return []
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            report.warning(
                "legacy_hw_item_not_object",
                f"Skipping non-object HW entry at index {index}.",
                str(path),
            )
            continue
        blocks.append(item)
    return blocks


def convert_hw_catalog(
    blocks: list[dict[str, Any]],
    *,
    project_ref: str,
    schema_version: str,
    report: ImportReport,
) -> list[dict[str, Any]]:
    project_slug = _project_slug(project_ref)
    docs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, block in enumerate(blocks):
        source = f"hw[{index}]"
        name = block.get("name")
        if not isinstance(name, str) or not name:
            report.error("legacy_hw_missing_name", "HW block is missing name.", source)
            continue
        if str(block.get("type") or "").upper() not in {"IP", "CPU"}:
            report.warning(
                "legacy_hw_unknown_type",
                f"HW block {name} has unexpected type {block.get('type')!r}; importing as catalog anyway.",
                source,
            )

        doc_id = _ip_id(name, project_slug)
        if doc_id in seen_ids:
            report.error("duplicate_ip_id", f"Duplicate generated IP id: {doc_id}", source)
            continue
        seen_ids.add(doc_id)

        modules = _list_of_dicts(block.get("modules"), report, f"{source}.modules")
        internal_edges = _internal_edges(block.get("edges"), report, f"{source}.edges")
        dma_ports = [deepcopy(module) for module in modules if str(module.get("type") or "").upper() == "DMA"]
        supported_compressions = _supported_compressions(dma_ports)
        supported_modes = block.get("supported_modes") or ["Normal"]
        if not isinstance(supported_modes, list):
            report.warning(
                "legacy_hw_modes_not_list",
                f"HW block {name} supported_modes is not a list; defaulting to Normal.",
                source,
            )
            supported_modes = ["Normal"]

        properties = {
            "legacy_name": name,
            "legacy_type": block.get("type"),
            "ip_group": block.get("ip_group"),
            "hierarchy_group": block.get("hierarchy_group"),
            "min_size": block.get("min_size"),
            "max_size": block.get("max_size"),
            "supports_crop": block.get("supports_crop"),
            "supports_scale": block.get("supports_scale"),
            "supports_rotate": block.get("supports_rotate"),
            "modules": modules,
            "internal_edges": internal_edges,
            "dma_ports": dma_ports,
        }
        doc = {
            "id": doc_id,
            "schema_version": schema_version,
            "kind": "ip",
            "category": _category_for(block),
            "hierarchy": {"type": "simple"},
            "capabilities": {
                "operating_modes": [
                    {"id": str(mode)}
                    for mode in supported_modes
                    if mode is not None
                ],
                "supported_features": {
                    "compression": supported_compressions,
                    **_optional_bool("crop", block.get("supports_crop")),
                    **_optional_bool("scale", block.get("supports_scale")),
                    **_optional_bool("rotate", block.get("supports_rotate")),
                },
                "properties": _drop_none(properties),
            },
            "compatible_soc": [],
        }
        docs.append(doc)
        report.increment("ip_catalog")
    return docs


def _list_of_dicts(value: Any, report: ImportReport, source: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        report.warning("legacy_list_expected", f"Expected list at {source}; dropping value.", source)
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            report.warning("legacy_list_item_not_object", f"Skipping non-object entry at {source}[{index}].", source)
            continue
        items.append(deepcopy(item))
    return items


def _internal_edges(value: Any, report: ImportReport, source: str) -> list[dict[str, Any]]:
    edges = _list_of_dicts(value, report, source)
    normalized: list[dict[str, Any]] = []
    for edge in edges:
        src = edge.get("src") or edge.get("from")
        dst = edge.get("dst") or edge.get("to")
        if not src or not dst:
            report.warning("legacy_edge_missing_endpoint", f"Dropping internal edge without src/dst: {edge}", source)
            continue
        normalized.append({"from": src, "to": dst})
    return normalized


def _supported_compressions(dma_ports: list[dict[str, Any]]) -> list[str]:
    values: set[str] = set()
    for port in dma_ports:
        for item in port.get("supported_compressions") or []:
            values.add(str(item))
    return sorted(values)


def _category_for(block: dict[str, Any]) -> str:
    text = " ".join(
        str(block.get(key) or "")
        for key in ("name", "ip_group", "hierarchy_group", "type")
    ).lower()
    if any(token in text for token in ("mfc", "codec", "encoder", "decoder")):
        return "codec"
    if any(token in text for token in ("dpu", "display", "decon", "panel")):
        return "display"
    if any(token in text for token in ("llc", "dram", "memory", "mif")):
        return "memory"
    if any(token in text for token in ("cpu", "cluster")):
        return "cpu"
    return "camera"


def _project_slug(project_ref: str) -> str:
    value = project_ref.removeprefix("proj-")
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "legacy"


def _ip_id(name: str, project_slug: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"ip-{slug}-{project_slug}"


def _optional_bool(key: str, value: Any) -> dict[str, bool]:
    return {key: value} if isinstance(value, bool) else {}


def _drop_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}

