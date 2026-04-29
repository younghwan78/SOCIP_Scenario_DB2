from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from scenario_db.legacy_import.ids import catalog_id, ip_id
from scenario_db.legacy_import.read_legacy import read_yaml
from scenario_db.legacy_import.report import ImportReport


def load_legacy_scenario(path: Path, report: ImportReport) -> dict[str, Any]:
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        report.error("legacy_scenario_not_object", "Scenario config must be a YAML object.", str(path))
        return {}
    return raw


def convert_scenario_usecase(
    raw: dict[str, Any],
    *,
    project_ref: str,
    schema_version: str,
    report: ImportReport,
    source: str | None = None,
) -> dict[str, Any] | None:
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        report.error("legacy_scenario_missing_name", "Scenario is missing a valid name.", source)
        return None

    tasks, node_configs = _collect_tasks(raw, project_ref, report, source or name)
    task_ids = {task["id"] for task in tasks}
    edge_details = _collect_edges(raw, task_ids, report, source or name)
    buffers, buffer_overrides = _build_buffers(edge_details, node_configs)
    base_edges = [
        _base_edge(edge, buffer_id)
        for edge, buffer_id in zip(edge_details, _buffer_ids_for_edges(edge_details), strict=True)
    ]
    base_edges = [edge for edge in base_edges if edge is not None]

    anchors = _size_anchors(raw, node_configs)
    variant_id = _variant_id(name)
    design_conditions = _design_conditions(raw, anchors)
    usecase = {
        "id": f"uc-{_slug(name)}",
        "schema_version": schema_version,
        "kind": "scenario.usecase",
        "project_ref": project_ref,
        "metadata": {
            "name": _title(name),
            "category": ["camera", "codec"],
            "domain": ["camera"],
        },
        "pipeline": {
            "nodes": [
                {
                    "id": task["id"],
                    "ip_ref": task["ip_ref"],
                    **({"role": task["role"]} if task.get("role") else {}),
                }
                for task in tasks
            ],
            "edges": base_edges,
            "buffers": buffers,
            "architecture_graph": {
                "layout": "legacy-layered-lanes",
                "layer_order": ["app", "framework", "hal", "kernel", "hw", "memory"],
                "memory_below_hw": True,
                "source": "legacy_import",
            },
            "task_graph": {
                "layout": "legacy-vertical-topology",
                "source": "legacy_import",
                "nodes": [_task_graph_node(task, node_configs.get(task["id"]) or {}) for task in tasks],
                "edges": [_task_graph_edge(edge) for edge in edge_details],
            },
            "level1_graph": {
                "layout": "legacy-grouped-ip-detail",
                "source": "legacy_import",
                "nodes_from_task_graph": True,
            },
        },
        "size_profile": {"anchors": anchors},
        "design_axes": [
            {"name": "resolution", "enum": ["FHD", "UHD", "8K"]},
            {"name": "fps", "enum": [30, 60, 120]},
            {"name": "sensor", "enum": sorted({str(raw.get("sensor", {}).get("hw") or "")})},
            {"name": "sensor_mode", "enum": sorted({str(raw.get("sensor", {}).get("mode") or "")})},
        ],
        "variants": [
            {
                "id": variant_id,
                "severity": _severity(design_conditions),
                "design_conditions": design_conditions,
                "size_overrides": anchors,
                "node_configs": node_configs,
                "buffer_overrides": buffer_overrides,
                "tags": ["legacy_import", "recording"],
            }
        ],
        "inheritance_policy": {
            "max_depth": 3,
            "cycle_detection": "required",
        },
    }
    report.increment("scenario_usecase")
    report.increment("scenario_variant")
    return usecase


def _collect_tasks(
    raw: dict[str, Any],
    project_ref: str,
    report: ImportReport,
    source: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    configs: dict[str, Any] = {}
    seen: set[str] = set()

    sensor = raw.get("sensor") if isinstance(raw.get("sensor"), dict) else {}
    for item in _list_of_dicts(raw.get("tasks"), report, f"{source}.tasks"):
        task_id = str(item.get("id") or "")
        hw = str(item.get("hw") or sensor.get("hw") or "")
        if not task_id or not hw:
            report.warning("legacy_task_missing_id_or_hw", f"Skipping task without id/hw: {item}", source)
            continue
        _append_task(tasks, seen, {
            "id": task_id,
            "kind": "sensor" if hw == sensor.get("hw") else "hw",
            "hw": hw,
            "ip_ref": catalog_id("sensor", hw, project_ref) if hw == sensor.get("hw") else ip_id(hw, project_ref),
            "label": item.get("description") or hw,
            "role": "sensor" if hw == sensor.get("hw") else None,
        }, report, source)
        configs[task_id] = {
            "kind": "sensor",
            "hw": hw,
            "sensor_mode": sensor.get("mode"),
            "description": item.get("description"),
        }

    for index, block in enumerate(_list_of_dicts(raw.get("ip_blocks"), report, f"{source}.ip_blocks")):
        block_source = f"{source}.ip_blocks[{index}]"
        settings = block.get("ip_settings") if isinstance(block.get("ip_settings"), dict) else {}
        settings_hw = settings.get("hw")
        for item in _list_of_dicts(block.get("tasks"), report, f"{block_source}.tasks"):
            task_id = str(item.get("id") or "")
            hw = str(item.get("hw") or settings_hw or "")
            if not task_id or not hw:
                report.warning("legacy_task_missing_id_or_hw", f"Skipping task without id/hw: {item}", block_source)
                continue
            _append_task(tasks, seen, {
                "id": task_id,
                "kind": "hw",
                "hw": hw,
                "ip_ref": ip_id(hw, project_ref),
                "label": item.get("description") or hw,
                "role": _role_for_hw(hw),
            }, report, block_source)
            configs[task_id] = _drop_none({
                "kind": "hw",
                "hw": hw,
                "selected_mode": settings.get("mode"),
                "description": item.get("description"),
                "inputs": deepcopy(settings.get("inputs") or []),
                "outputs": deepcopy(settings.get("outputs") or []),
                "manual_clock": settings.get("manual_clock"),
            })
        for item in _list_of_dicts(block.get("sw_tasks"), report, f"{block_source}.sw_tasks"):
            task_id = str(item.get("id") or "")
            processor = str(item.get("processor") or "")
            if not task_id or not processor:
                report.warning("legacy_sw_task_missing_id_or_processor", f"Skipping SW task without id/processor: {item}", block_source)
                continue
            _append_task(tasks, seen, {
                "id": task_id,
                "kind": "sw",
                "hw": processor,
                "ip_ref": ip_id(processor, project_ref),
                "label": item.get("name") or task_id,
                "role": "sw_task",
            }, report, block_source)
            configs[task_id] = _drop_none({
                "kind": "sw_task",
                "name": item.get("name"),
                "group": item.get("group"),
                "processor": processor,
                "duration_ms": item.get("duration_ms"),
                "latency_ms": item.get("latency_ms"),
            })

    return tasks, configs


def _append_task(tasks: list[dict[str, Any]], seen: set[str], task: dict[str, Any], report: ImportReport, source: str) -> None:
    if task["id"] in seen:
        report.warning("legacy_duplicate_task_id", f"Skipping duplicate task id: {task['id']}", source)
        return
    seen.add(task["id"])
    tasks.append(task)


def _collect_edges(
    raw: dict[str, Any],
    task_ids: set[str],
    report: ImportReport,
    source: str,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for index, block in enumerate(_list_of_dicts(raw.get("ip_blocks"), report, f"{source}.ip_blocks")):
        for edge_index, edge in enumerate(_list_of_dicts(block.get("edges"), report, f"{source}.ip_blocks[{index}].edges")):
            src = edge.get("src") or edge.get("from")
            dst = edge.get("dst") or edge.get("to")
            if src not in task_ids or dst not in task_ids:
                report.warning(
                    "legacy_edge_unknown_task",
                    f"Skipping edge with unknown task endpoint: {src}->{dst}",
                    f"{source}.ip_blocks[{index}].edges[{edge_index}]",
                )
                continue
            edge_type = str(edge.get("type") or "M2M").upper()
            if edge_type not in {"OTF", "M2M"}:
                report.warning("legacy_edge_unknown_type", f"Defaulting edge type to M2M: {edge_type}", source)
                edge_type = "M2M"
            edges.append({
                "id": f"e{len(edges)}",
                "from": str(src),
                "to": str(dst),
                "type": edge_type,
                "src_port": edge.get("src_port"),
                "dst_port": edge.get("dst_port"),
            })
    return edges


def _build_buffers(
    edges: list[dict[str, Any]],
    node_configs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    buffers: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    for edge, buffer_id in zip(edges, _buffer_ids_for_edges(edges), strict=True):
        if edge["type"] != "M2M" or buffer_id is None:
            continue
        source_cfg = node_configs.get(edge["from"]) or {}
        port_desc = _find_port(source_cfg.get("outputs") or [], edge.get("src_port"))
        if not port_desc:
            target_cfg = node_configs.get(edge["to"]) or {}
            port_desc = _find_port(target_cfg.get("inputs") or [], edge.get("dst_port"))
        size = _port_size(port_desc)
        descriptor = _drop_none({
            "label": buffer_id.replace("_", " ").title(),
            "producer": edge["from"],
            "consumer": edge["to"],
            "source_port": edge.get("src_port"),
            "target_port": edge.get("dst_port"),
            "format": port_desc.get("format") if port_desc else None,
            "bitdepth": port_desc.get("bitwidth") if port_desc else None,
            "size": size,
            "size_ref": _size_ref(size),
            "compression": _compression(port_desc),
        })
        buffers[buffer_id] = descriptor
        overrides[buffer_id] = descriptor
    return buffers, overrides


def _buffer_ids_for_edges(edges: list[dict[str, Any]]) -> list[str | None]:
    ids: list[str | None] = []
    seen: dict[str, int] = {}
    for edge in edges:
        if edge["type"] != "M2M":
            ids.append(None)
            continue
        base = _upper_id("BUF", edge["from"], edge.get("src_port") or "OUT", edge["to"], edge.get("dst_port") or "IN")
        seen[base] = seen.get(base, 0) + 1
        ids.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return ids


def _base_edge(edge: dict[str, Any], buffer_id: str | None) -> dict[str, Any] | None:
    base = {
        "from": edge["from"],
        "to": edge["to"],
        "type": edge["type"],
    }
    if buffer_id:
        base["buffer"] = buffer_id
    return base


def _task_graph_node(task: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    size = _primary_size(config)
    label = f"{task['id']}\n({task.get('label') or task.get('hw')})"
    if size:
        label = f"{label}\n{size}"
    return _drop_none({
        "id": task["id"],
        "label": label,
        "layer": "kernel" if task.get("kind") == "sw" else "hw",
        "ip_ref": task.get("ip_ref"),
        "hw": task.get("hw"),
        "role": task.get("role"),
    })


def _task_graph_edge(edge: dict[str, Any]) -> dict[str, Any]:
    port_label = "->".join(str(value) for value in (edge.get("src_port"), edge.get("dst_port")) if value)
    return _drop_none({
        "id": edge["id"],
        "from": edge["from"],
        "to": edge["to"],
        "type": edge["type"],
        "label": f"{edge['type']}: {port_label}" if port_label else edge["type"],
        "src_port": edge.get("src_port"),
        "dst_port": edge.get("dst_port"),
    })


def _size_anchors(raw: dict[str, Any], node_configs: dict[str, Any]) -> dict[str, str]:
    sizes = [_primary_size(config) for config in node_configs.values()]
    sizes = [size for size in sizes if size]
    record_out = _find_named_size(node_configs, ["MFC_RDMA", "P0_WDMA"]) or _most_common_output_size(node_configs) or (sizes[-1] if sizes else "0x0")
    preview_out = _find_named_size(node_configs, ["DPU_RDMA", "P1_WDMA"]) or record_out
    sensor_full = _find_named_size(node_configs, ["DC_PHY", "LINK", "NFI_DEC"]) or (sizes[0] if sizes else record_out)
    return {
        "sensor_full": sensor_full,
        "record_out": record_out,
        "preview_out": preview_out,
    }


def _design_conditions(raw: dict[str, Any], anchors: dict[str, str]) -> dict[str, str | int | float]:
    name = str(raw.get("name") or "")
    sensor = raw.get("sensor") if isinstance(raw.get("sensor"), dict) else {}
    fps = _fps_from_name(name) or _fps_from_period(raw)
    return _drop_none({
        "resolution": _resolution_from_size(anchors.get("record_out") or ""),
        "fps": fps,
        "usecase": "recording" if "record" in name.lower() else _slug(name),
        "sensor": sensor.get("hw"),
        "sensor_mode": sensor.get("mode"),
    })


def _find_port(ports: list[Any], selected_port: str | None) -> dict[str, Any]:
    valid_ports = [port for port in ports if isinstance(port, dict)]
    if selected_port:
        for port in valid_ports:
            if port.get("port") == selected_port:
                return port
    return valid_ports[0] if valid_ports else {}


def _port_size(port: dict[str, Any]) -> str | None:
    size = port.get("size") if isinstance(port, dict) else None
    if isinstance(size, list) and len(size) >= 4:
        return f"{size[2]}x{size[3]}"
    if isinstance(size, list) and len(size) >= 2:
        return f"{size[0]}x{size[1]}"
    return None


def _primary_size(config: dict[str, Any]) -> str | None:
    for key in ("outputs", "inputs"):
        for port in config.get(key) or []:
            size = _port_size(port)
            if size and size != "0x0":
                return size
    return None


def _find_named_size(node_configs: dict[str, Any], ports: list[str]) -> str | None:
    for config in node_configs.values():
        for key in ("outputs", "inputs"):
            for port in config.get(key) or []:
                if isinstance(port, dict) and port.get("port") in ports:
                    size = _port_size(port)
                    if size and size != "0x0":
                        return size
    return None


def _most_common_output_size(node_configs: dict[str, Any]) -> str | None:
    counts: dict[str, int] = {}
    for config in node_configs.values():
        for port in config.get("outputs") or []:
            size = _port_size(port)
            if size:
                counts[size] = counts.get(size, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _size_ref(size: str | None) -> str | None:
    if not size:
        return None
    if size in {"4000x2252", "4080x2296"}:
        return "sensor_full"
    if size in {"1920x1080", "3840x2160"}:
        return "record_out"
    return None


def _compression(port: dict[str, Any]) -> str | None:
    if not port:
        return None
    value = str(port.get("comp") or "").lower()
    if value in {"enable", "enabled", "true", "1"}:
        return "enabled"
    if value in {"disable", "disabled", "false", "0"}:
        return "none"
    return None


def _list_of_dicts(value: Any, report: ImportReport, source: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        report.warning("legacy_list_expected", f"Expected list at {source}; dropping value.", source)
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _role_for_hw(hw: str) -> str:
    text = hw.lower()
    if any(token in text for token in ("mfc", "codec")):
        return "codec"
    if any(token in text for token in ("dpu", "display")):
        return "display"
    if "cpu" in text:
        return "sw_task"
    return "camera"


def _variant_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "legacy-scenario"


def _title(name: str) -> str:
    return re.sub(r"[_\-]+", " ", name).strip().title()


def _upper_id(*parts: str) -> str:
    text = "_".join(str(part) for part in parts if part)
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").upper()


def _fps_from_name(name: str) -> int | None:
    match = re.search(r"(?i)(\d+)\s*fps|fhd(\d+)|uhd(\d+)|8k(\d+)", name)
    if not match:
        return None
    for group in match.groups():
        if group:
            return int(group)
    return None


def _fps_from_period(raw: dict[str, Any]) -> int | None:
    period_ms = raw.get("output_period_ms")
    if isinstance(period_ms, (int, float)) and period_ms:
        return round(1000 / period_ms)
    return None


def _resolution_from_size(size: str) -> str:
    if size.startswith("7680x") or size.startswith("8192x"):
        return "8K"
    if size.startswith("3840x"):
        return "UHD"
    return "FHD"


def _severity(design_conditions: dict[str, Any]) -> str:
    fps = design_conditions.get("fps")
    resolution = design_conditions.get("resolution")
    if resolution == "8K" or (resolution == "UHD" and isinstance(fps, int) and fps >= 60):
        return "heavy"
    return "medium"


def _drop_none(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}
