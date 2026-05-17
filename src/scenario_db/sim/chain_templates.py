from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from scenario_db.sim.bw_calc import compression_enabled
from scenario_db.sim.exploration import ExplorationCompileResult


DEFAULT_BUFFER_COLUMNS = ["x", "y", "width", "height", "format", "bitwidth", "compression", "comp_ratio"]


def normalize_chain_template(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a compact chain template into an explicit compiler contract."""

    if not isinstance(payload, dict):
        raise ValueError("chain template payload must be a mapping")
    if payload.get("kind") != "scenario.chain_template":
        raise ValueError("chain template kind must be scenario.chain_template")
    template_id = _required_str(payload, "id")
    version = _required_str(payload, "version")
    schema_version = payload.get("schema_version")
    if schema_version in (None, ""):
        raise ValueError("chain template schema_version is required")

    source = _normalize_source(payload.get("source") or {})
    buffer_columns = [str(item) for item in payload.get("buffer_columns") or DEFAULT_BUFFER_COLUMNS]
    buffers = _normalize_buffers(payload.get("buffers") or {}, buffer_columns)
    blocks = _normalize_blocks(payload.get("blocks") or [])
    links = _normalize_links(payload.get("links") or [])
    _validate_link_endpoints(links, source_node_id=source["node_id"], block_ids={block["id"] for block in blocks}, buffer_ids=set(buffers))

    normalized = {
        "kind": "scenario.chain_template",
        "id": template_id,
        "version": version,
        "schema_version": schema_version,
        "project_ref": _required_str(payload, "project_ref"),
        "scenario_id": payload.get("scenario_id") or f"uc-{template_id}",
        "variant_id": payload.get("variant_id") or f"{_safe_id(template_id)}-{_safe_id(version)}",
        "soc_ref": payload.get("soc_ref"),
        "name": payload.get("name") or template_id.replace("-", " ").title(),
        "category": list(payload.get("category") or ["camera", "exploration"]),
        "source": source,
        "buffer_columns": buffer_columns,
        "buffers": buffers,
        "blocks": blocks,
        "links": links,
        "mapping_profile": deepcopy(payload.get("mapping_profile")),
        "design_conditions": deepcopy(payload.get("design_conditions") or {}),
        "tags": list(payload.get("tags") or ["exploration", "chain_template"]),
    }
    normalized["normalized_hash"] = _stable_hash(normalized)
    return normalized


def compile_chain_template(payload: dict[str, Any]) -> ExplorationCompileResult:
    """Compile a chain template directly into a scenario import bundle."""

    template = normalize_chain_template(payload)
    source_node = _source_node(template["source"])
    nodes = [source_node]
    node_configs: dict[str, Any] = {}
    mapping_trace: list[dict[str, Any]] = []

    block_by_id = {block["id"]: block for block in template["blocks"]}
    for block in template["blocks"]:
        mapping = _mapping_for_block(template.get("mapping_profile"), block)
        ip_ref = block.get("ip_ref") or mapping.get("target_ip_ref") or mapping.get("source_ip_ref")
        if not ip_ref:
            ip_ref = f"ip-{_safe_id(block.get('template') or block['id'])}"
        role = block.get("role") or mapping.get("target_role") or mapping.get("source_role") or block.get("template") or block["id"]
        nodes.append(
            {
                "id": block["id"],
                "ip_ref": str(ip_ref),
                "role": str(role),
                "instance_index": int(block.get("instance_index") or 0),
            }
        )
        node_configs[block["id"]] = {
            "selected_mode": block.get("selected_mode") or mapping.get("mode") or "Normal",
            "sim": _sim_block_for_template_node(block, template, mapping),
        }
        mapping_trace.append(
            {
                "node_id": block["id"],
                "template": block.get("template"),
                "ip_ref": str(ip_ref),
                "role": str(role),
                "mapping_confidence": mapping.get("confidence"),
                "source_ip_ref": mapping.get("source_ip_ref"),
                "source_role": mapping.get("source_role"),
                "scale": mapping.get("scale", 1.0),
            }
        )

    edges = _scenario_edges(template["links"], template["buffers"], block_by_id, source_node["id"])
    design_conditions = {
        "fps": template["source"]["fps"],
        "resolution_size": f"{template['source']['width']}x{template['source']['height']}",
        "format": template["source"].get("format"),
        "template_ref": f"{template['id']}@{template['version']}",
        "template_schema_version": template["schema_version"],
        "template_normalized_hash": template["normalized_hash"],
        **template["design_conditions"],
    }
    if template.get("soc_ref"):
        design_conditions.setdefault("soc_ref", template["soc_ref"])

    scenario = {
        "id": template["scenario_id"],
        "schema_version": "2.2",
        "kind": "scenario.usecase",
        "project_ref": template["project_ref"],
        "metadata": {
            "name": template["name"],
            "category": template["category"],
            "domain": template["category"],
        },
        "pipeline": {
            "nodes": nodes,
            "edges": edges,
            "buffers": _scenario_buffers(template["buffers"]),
        },
        "variants": [
            {
                "id": template["variant_id"],
                "severity": "medium",
                "design_conditions": design_conditions,
                "node_configs": node_configs,
                "tags": template["tags"],
            }
        ],
    }
    import_bundle = {
        "kind": "scenario.import_bundle",
        "documents": [scenario],
        "import_report": {
            "ok": True,
            "generated": {
                "scenario_usecase": 1,
                "scenario_variant": 1,
                "chain_template": 1,
            },
            "template": {
                "id": template["id"],
                "version": template["version"],
                "schema_version": template["schema_version"],
                "normalized_hash": template["normalized_hash"],
            },
            "messages": [],
        },
    }
    return ExplorationCompileResult(
        scenario=scenario,
        import_bundle=import_bundle,
        warnings=[],
        mapping_trace=mapping_trace,
    )


def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ValueError("source must be a mapping")
    width = _positive_int(source.get("width"), "source.width")
    height = _positive_int(source.get("height"), "source.height")
    fps = float(source.get("fps") or 30.0)
    if fps <= 0:
        raise ValueError("source.fps must be positive")
    return {
        "type": str(source.get("type") or "sensor"),
        "node_id": str(source.get("node_id") or "sensor_src"),
        "ip_ref": str(source.get("ip_ref") or "ip-exploration-sensor"),
        "width": width,
        "height": height,
        "fps": fps,
        "format": source.get("format") or "RAW_BAYER",
        "bitwidth": int(source.get("bitwidth") or 12),
        "compression": source.get("compression") or "disable",
    }


def _normalize_buffers(raw_buffers: dict[str, Any], columns: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_buffers, dict):
        raise ValueError("buffers must be a mapping")
    buffers: dict[str, dict[str, Any]] = {}
    pending = dict(raw_buffers)
    while pending:
        progressed = False
        for name, value in list(pending.items()):
            if isinstance(value, dict) and value.get("derive_from") and value["derive_from"] not in buffers:
                if value["derive_from"] not in raw_buffers:
                    raise ValueError(f"{name}.derive_from references unknown buffer: {value['derive_from']}")
                continue
            buffers[str(name)] = _normalize_buffer(str(name), value, columns, buffers)
            del pending[name]
            progressed = True
        if not progressed:
            missing = ", ".join(str(value.get("derive_from")) for value in pending.values() if isinstance(value, dict))
            raise ValueError(f"derive_from references unknown buffer: {missing}")
    return buffers


def _normalize_buffer(
    name: str,
    value: Any,
    columns: list[str],
    buffers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if isinstance(value, list):
        if len(value) > len(columns):
            raise ValueError(f"buffer {name} has more values than buffer_columns")
        item = {columns[index]: value[index] for index in range(len(value))}
    elif isinstance(value, dict):
        if value.get("derive_from"):
            return _derive_buffer(name, value, buffers)
        item = dict(value)
    else:
        raise ValueError(f"buffer {name} must be a list or mapping")

    x = int(item.get("x") or 0)
    y = int(item.get("y") or 0)
    width = _positive_int(item.get("width"), f"buffers.{name}.width")
    height = _positive_int(item.get("height"), f"buffers.{name}.height")
    compression = item.get("compression") or item.get("comp_mode") or "disable"
    result = {
        "roi": [x, y, width, height],
        "width": width,
        "height": height,
        "format": item.get("format"),
        "bitwidth": int(item.get("bitwidth") or item.get("bitdepth") or 8),
        "compression": compression,
    }
    if compression_enabled(str(compression)) and item.get("comp_ratio") is not None:
        result["comp_ratio"] = float(item["comp_ratio"])
    return result


def _derive_buffer(name: str, value: dict[str, Any], buffers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base_name = str(value["derive_from"])
    if base_name not in buffers:
        raise ValueError(f"{name}.derive_from references unknown buffer: {base_name}")
    base = buffers[base_name]
    scale = float(value.get("scale") or 1.0)
    if scale <= 0:
        raise ValueError(f"buffers.{name}.scale must be positive")
    width = int(round(float(value.get("width") or base["width"]) * (scale if value.get("width") is None else 1.0)))
    height = int(round(float(value.get("height") or base["height"]) * (scale if value.get("height") is None else 1.0)))
    result = {
        "roi": [int(value.get("x") or 0), int(value.get("y") or 0), width, height],
        "width": width,
        "height": height,
        "format": value.get("format", base.get("format")),
        "bitwidth": int(value.get("bitwidth") or value.get("bitdepth") or base.get("bitwidth") or 8),
        "compression": value.get("compression", base.get("compression") or "disable"),
    }
    comp_ratio = value.get("comp_ratio", base.get("comp_ratio"))
    if compression_enabled(str(result["compression"])) and comp_ratio is not None:
        result["comp_ratio"] = float(comp_ratio)
    return result


def _normalize_blocks(raw_blocks: list[Any]) -> list[dict[str, Any]]:
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise ValueError("blocks must be a non-empty list")
    blocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            raise ValueError("each block must be a mapping")
        block_id = _required_str(raw, "id")
        if block_id in seen:
            raise ValueError(f"duplicate block id: {block_id}")
        seen.add(block_id)
        blocks.append(
            {
                "id": block_id,
                "template": str(raw.get("template") or block_id),
                "role": raw.get("role"),
                "ip_ref": raw.get("ip_ref"),
                "selected_mode": raw.get("selected_mode") or "Normal",
                "instance_index": raw.get("instance_index") or 0,
                "ip_params": deepcopy(raw.get("ip_params") or {}),
            }
        )
    return blocks


def _normalize_links(raw_links: list[Any]) -> list[dict[str, str]]:
    if not isinstance(raw_links, list) or not raw_links:
        raise ValueError("links must be a non-empty list")
    return [_normalize_link(item) for item in raw_links]


def _normalize_link(item: Any) -> dict[str, str]:
    if isinstance(item, str):
        if "->" not in item:
            raise ValueError(f"compact link must contain ->: {item}")
        path, _, type_part = item.partition("|")
        left, right = path.split("->", 1)
        link_type = type_part.strip() or "OTF"
        return {"from": left.strip(), "to": right.strip(), "type": link_type}
    if isinstance(item, dict):
        return {
            "from": _required_str(item, "from"),
            "to": _required_str(item, "to"),
            "type": str(item.get("type") or "OTF"),
        }
    raise ValueError("each link must be a compact string or mapping")


def _validate_link_endpoints(
    links: list[dict[str, str]],
    *,
    source_node_id: str,
    block_ids: set[str],
    buffer_ids: set[str],
) -> None:
    nodes = {source_node_id, *block_ids}
    for link in links:
        for key in ("from", "to"):
            endpoint = link[key]
            node_id, _ = _split_endpoint(endpoint)
            if node_id not in nodes and node_id not in buffer_ids:
                raise ValueError(f"link {key} endpoint references unknown node or buffer: {endpoint}")


def _source_node(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": source["node_id"],
        "ip_ref": source["ip_ref"],
        "role": source["type"],
        "instance_index": 0,
    }


def _sim_block_for_template_node(block: dict[str, Any], template: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    inputs, outputs = _ports_for_node(block["id"], template["links"], template["buffers"])
    ip_params = {**(mapping.get("ip_params") or {}), **(block.get("ip_params") or {})}
    if mapping.get("scale", 1.0) != 1.0 and ip_params.get("unit_power_mw_mp") is not None:
        ip_params["unit_power_mw_mp"] = float(ip_params["unit_power_mw_mp"]) * float(mapping["scale"])
    result: dict[str, Any] = {
        "inherit_shape": True,
        "inputs": inputs,
        "outputs": outputs,
        "mapping_source": {
            "confidence": mapping.get("confidence"),
            "source_ip_ref": mapping.get("source_ip_ref"),
            "source_role": mapping.get("source_role"),
            "scale": mapping.get("scale", 1.0),
        },
    }
    if ip_params:
        result["ip_params"] = ip_params
    return result


def _ports_for_node(node_id: str, links: list[dict[str, str]], buffers: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    seen_inputs: set[tuple[Any, ...]] = set()
    seen_outputs: set[tuple[Any, ...]] = set()
    for link in links:
        from_node, from_port = _split_endpoint(link["from"])
        to_node, to_port = _split_endpoint(link["to"])
        if from_node == node_id:
            buffer = buffers.get(to_node)
            port = _port_config(from_port, direction="output", link_type=link["type"], buffer=buffer)
            _append_unique(outputs, port, seen_outputs)
        if to_node == node_id:
            buffer = buffers.get(from_node)
            port = _port_config(to_port, direction="input", link_type=link["type"], buffer=buffer)
            _append_unique(inputs, port, seen_inputs)
    return inputs, outputs


def _port_config(port_name: str | None, *, direction: str, link_type: str, buffer: dict[str, Any] | None) -> dict[str, Any]:
    port = port_name or ("RDMA" if direction == "input" else "WDMA")
    if buffer is not None:
        port_type = "DMA_READ" if direction == "input" else "DMA_WRITE"
    else:
        port_type = "OTF_IN" if direction == "input" else "OTF_OUT"
    result: dict[str, Any] = {"port": port, "port_type": port_type}
    if buffer:
        result.update(
            {
                "width": buffer["width"],
                "height": buffer["height"],
                "format": buffer.get("format"),
                "bitwidth": buffer.get("bitwidth"),
                "compression": buffer.get("compression"),
            }
        )
        if buffer.get("comp_ratio") is not None:
            result["comp_ratio"] = buffer["comp_ratio"]
    elif link_type == "M2M":
        result["port_type"] = "DMA_READ" if direction == "input" else "DMA_WRITE"
    return result


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any], seen: set[tuple[Any, ...]]) -> None:
    key = (item.get("port"), item.get("port_type"), item.get("width"), item.get("height"), item.get("format"))
    if key in seen:
        return
    seen.add(key)
    items.append(item)


def _scenario_edges(
    links: list[dict[str, str]],
    buffers: dict[str, dict[str, Any]],
    block_by_id: dict[str, dict[str, Any]],
    source_node_id: str,
) -> list[dict[str, Any]]:
    node_ids = {source_node_id, *block_by_id}
    direct: list[dict[str, Any]] = []
    buffer_writers: dict[str, list[str]] = {}
    buffer_readers: dict[str, list[str]] = {}
    for link in links:
        from_node, _ = _split_endpoint(link["from"])
        to_node, _ = _split_endpoint(link["to"])
        if from_node in node_ids and to_node in node_ids:
            direct.append({"from": from_node, "to": to_node, "type": link["type"]})
        elif from_node in node_ids and to_node in buffers:
            buffer_writers.setdefault(to_node, []).append(from_node)
        elif from_node in buffers and to_node in node_ids:
            buffer_readers.setdefault(from_node, []).append(to_node)

    edges = list(direct)
    for buffer_id, writers in buffer_writers.items():
        readers = buffer_readers.get(buffer_id) or []
        for writer in writers:
            for reader in readers:
                edges.append({"from": writer, "to": reader, "type": "M2M", "buffer": buffer_id})
    return _dedupe_edges(edges)


def _scenario_buffers(buffers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, buffer in buffers.items():
        item = {
            "size": buffer["roi"],
            "format": buffer.get("format"),
            "bitdepth": buffer.get("bitwidth"),
            "compression": buffer.get("compression"),
        }
        if buffer.get("comp_ratio") is not None:
            item["comp_ratio"] = buffer["comp_ratio"]
        result[name] = item
    return result


def _mapping_for_block(profile: dict[str, Any] | None, block: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    role_mappings = profile.get("role_mappings") or {}
    if not isinstance(role_mappings, dict):
        return {}
    for key in (block.get("template"), block.get("role"), block.get("id")):
        value = role_mappings.get(key) if key else None
        if isinstance(value, dict):
            return value
    return {}


def _split_endpoint(endpoint: str) -> tuple[str, str | None]:
    if ":" not in endpoint:
        return endpoint.strip(), None
    node, port = endpoint.split(":", 1)
    return node.strip(), port.strip()


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for edge in edges:
        key = (edge.get("from"), edge.get("to"), edge.get("type"), edge.get("buffer"))
        if key in seen:
            continue
        seen.add(key)
        result.append(edge)
    return result


def _required_str(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if value in (None, ""):
        raise ValueError(f"{key} is required")
    return str(value)


def _positive_int(value: Any, path: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be a positive integer") from exc
    if number <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return number


def _safe_id(value: Any) -> str:
    text = str(value).lower().replace(".", "p")
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text).strip("-")


def _stable_hash(payload: dict[str, Any]) -> str:
    copy = deepcopy(payload)
    copy.pop("normalized_hash", None)
    data = json.dumps(copy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]
