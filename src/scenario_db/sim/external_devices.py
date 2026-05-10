from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph


def apply_source_sink_constraints(
    graph: CanonicalScenarioGraph,
    tasks: list[dict[str, Any]],
    source_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    panel = selected_panel_properties(graph)
    node_by_id = {str(node.get("id")): node for node in source_nodes if node.get("id")}
    result: list[dict[str, Any]] = []
    for task in tasks:
        updated = dict(task)
        node = node_by_id.get(str(task.get("id"))) or {}
        sensor_mode = selected_sensor_mode(graph, node)
        if sensor_mode and _is_sensor_timeline_task(task, node):
            _apply_sensor_constraint(updated, sensor_mode)
        if panel and _is_display_sink_task(task, node):
            _apply_panel_constraint(updated, panel, graph)
        result.append(updated)
    return result


def external_devices(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for node in graph.pipeline_nodes:
        ip_ref = str(node.get("ip_ref") or "")
        ip_row = graph.ip_catalog.get(ip_ref)
        if ip_row is None:
            continue
        category = str(getattr(ip_row, "category", "") or "").lower()
        text = _task_node_text({}, node)
        properties = _capability_properties(ip_row)
        panel_like = (
            category == "panel"
            or "panel" in text
            or str(properties.get("role") or "").lower() == "panel"
        )
        if category == "sensor" or "sensor" in text:
            mode = selected_sensor_mode(graph, node) or {}
            device = _sensor_device_info(graph, node, ip_row, mode)
            if device:
                devices.append(device)
        elif panel_like:
            panel = selected_panel_properties(graph) or {}
            device = _display_device_info(graph, node, ip_row, panel)
            if device:
                devices.append(device)
    return devices


def active_sensor_nodes(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in graph.pipeline_nodes:
        ip_ref = str(node.get("ip_ref") or "")
        ip_row = graph.ip_catalog.get(ip_ref)
        category = str(getattr(ip_row, "category", "") or "").lower() if ip_row is not None else ""
        if category == "sensor" or "sensor" in _task_node_text({}, node):
            result.append(node)
    return result


def selected_sensor_mode(graph: CanonicalScenarioGraph, node: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = _selected_sensor_row(graph, node)
    if row is None:
        return None
    design = graph.variant.design_conditions or {}
    selected_mode = design.get("sensor_mode") or design.get("sensor_mode_ref") or design.get("sensor")
    properties = _capability_properties(row)
    modes = properties.get("modes") if isinstance(properties.get("modes"), dict) else {}
    if not modes:
        return None
    if selected_mode and selected_mode in modes and isinstance(modes[selected_mode], dict):
        return _annotated_sensor_mode(row, selected_mode, modes[selected_mode], graph)
    preferred = _preferred_sensor_mode(modes, graph)
    if preferred:
        mode_id, mode = preferred
        return _annotated_sensor_mode(row, mode_id, mode, graph)
    mode_id, mode = next((key, value) for key, value in modes.items() if isinstance(value, dict))
    return _annotated_sensor_mode(row, str(mode_id), mode, graph)


def selected_panel_properties(graph: CanonicalScenarioGraph) -> dict[str, Any] | None:
    for row in graph.ip_catalog.values():
        category = str(getattr(row, "category", "") or "").lower()
        properties = _capability_properties(row)
        if "refresh_rates" in properties or "refresh_rate" in properties or "panel" in str(getattr(row, "id", "")).lower():
            if category in {"display", "panel"}:
                return dict(properties)
    return None


def _selected_sensor_row(graph: CanonicalScenarioGraph, node: dict[str, Any] | None = None) -> Any | None:
    candidates = [
        row
        for row in graph.ip_catalog.values()
        if str(getattr(row, "category", "") or "").lower() == "sensor"
    ]
    if not candidates:
        return None
    if node and node.get("ip_ref"):
        row = graph.ip_catalog.get(str(node.get("ip_ref")))
        if row is not None and str(getattr(row, "category", "") or "").lower() == "sensor":
            return row
    design = graph.variant.design_conditions or {}
    sensor_place = str(design.get("sensor_place") or design.get("sensor_places") or "").lower()
    if sensor_place:
        for row in candidates:
            properties = _capability_properties(row)
            place = str(properties.get("place") or "").lower()
            row_id = str(getattr(row, "id", "") or "").lower()
            if place and place in sensor_place:
                return row
            if place and place in row_id and place in sensor_place:
                return row
    return candidates[0]


def _preferred_sensor_mode(modes: dict[str, Any], graph: CanonicalScenarioGraph) -> tuple[str, dict[str, Any]] | None:
    fps = _variant_fps(graph)
    design = graph.variant.design_conditions or {}
    design_text = " ".join(str(value or "").lower() for value in design.values())
    video = "video" in design_text or "rec" in str(graph.scenario_id).lower()
    if video:
        video_modes = [
            (str(key), value)
            for key, value in modes.items()
            if isinstance(value, dict)
            and ("wide" in str(key).lower() or "video" in str(key).lower() or _is_16_9_size(value.get("sensor_size")))
        ]
        if video_modes:
            return min(
                video_modes,
                key=lambda item: abs((_float_or_none(item[1].get("sensor_fps")) or fps) - fps),
            )
    best = _mode_by_fps(modes, fps)
    if best:
        for key, value in modes.items():
            if value is best:
                return str(key), best
    return None


def _annotated_sensor_mode(row: Any, mode_id: str, mode: dict[str, Any], graph: CanonicalScenarioGraph) -> dict[str, Any]:
    properties = _capability_properties(row)
    result = dict(mode)
    result["mode_id"] = mode_id
    result["ip_ref"] = getattr(row, "id", None)
    result["place"] = properties.get("place")
    result["sensor_phy_type"] = result.get("sensor_phy_type") or properties.get("phy_type")
    active_size, source = _active_sensor_size(result, graph)
    if active_size:
        result["active_size"] = list(active_size)
        result["active_size_source"] = source
    return result


def _sensor_device_info(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    ip_row: Any,
    mode: dict[str, Any],
) -> dict[str, Any]:
    v_valid_ms = _float_or_none(mode.get("v_valid_ms")) or _calc_v_valid_ms(mode)
    active_size = mode.get("active_size")
    sensor_size = mode.get("sensor_size")
    size = active_size if isinstance(active_size, list) and len(active_size) >= 2 else sensor_size
    return {
        "device_type": "sensor",
        "node_id": node.get("id"),
        "ip_ref": getattr(ip_row, "id", None),
        "role": node.get("role"),
        "place": mode.get("place") or _capability_properties(ip_row).get("place"),
        "mode": mode.get("mode_id") or mode.get("sensor_mode") or mode.get("sensor_name"),
        "name": mode.get("sensor_name"),
        "size": _size_text(size),
        "catalog_size": _size_text(sensor_size),
        "active_size": _size_text(active_size),
        "active_size_source": mode.get("active_size_source"),
        "format": mode.get("sensor_format"),
        "bitwidth": mode.get("sensor_bitwidth"),
        "fps": mode.get("sensor_fps") or _variant_fps(graph),
        "v_valid_ms": v_valid_ms,
        "v_valid_source": _v_valid_source(mode),
        "pclk": mode.get("sensor_pclk"),
        "line_length_pck": mode.get("sensor_line_length_pck"),
        "phy_type": mode.get("sensor_phy_type"),
        "mipi_speed": mode.get("sensor_mipi_speed"),
        "sbwc": mode.get("sensor_sbwc"),
    }


def _display_device_info(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    ip_row: Any,
    panel: dict[str, Any],
) -> dict[str, Any]:
    refresh_hz = _selected_refresh_hz(panel, _variant_fps(graph))
    display_size = panel.get("display_size") or panel.get("layout_size")
    return {
        "device_type": "display",
        "node_id": node.get("id"),
        "ip_ref": getattr(ip_row, "id", None),
        "role": node.get("role"),
        "layout": panel.get("layout") or panel.get("panel_layout"),
        "size": _size_text(display_size),
        "format": panel.get("format") or panel.get("pixel_format"),
        "fps": _variant_fps(graph),
        "refresh_hz": refresh_hz,
        "scanout_ms": (1000.0 / refresh_hz) if refresh_hz and refresh_hz > 0 else None,
        "panel_type": panel.get("panel_type"),
        "ppi": panel.get("ppi"),
    }


def _active_sensor_size(mode: dict[str, Any], graph: CanonicalScenarioGraph) -> tuple[tuple[int, int] | None, str | None]:
    for key in ("active_size", "sensor_active_size", "video_size", "crop_size"):
        size = _size_tuple(mode.get(key))
        if size:
            return size, key
    catalog_size = _size_tuple(mode.get("sensor_size"))
    if not catalog_size:
        return None, None
    design = graph.variant.design_conditions or {}
    design_size = _design_size(graph)
    design_text = " ".join(str(value or "").lower() for value in design.values())
    video = "video" in design_text or "rec" in str(graph.scenario_id).lower()
    if video and design_size and _is_16_9_tuple(design_size) and not _is_16_9_tuple(catalog_size):
        width, height = catalog_size
        cropped_height = int(round(width * 9 / 16))
        if 0 < cropped_height <= height:
            return (width, _make_even(cropped_height)), "derived_16_9_crop_from_catalog_width"
        cropped_width = int(round(height * 16 / 9))
        if 0 < cropped_width <= width:
            return (_make_even(cropped_width), height), "derived_16_9_crop_from_catalog_height"
    return catalog_size, "catalog_sensor_size"


def _size_text(value: Any) -> str | None:
    size = _size_tuple(value)
    if not size:
        return None
    return f"{size[0]}x{size[1]}"


def _size_tuple(value: Any) -> tuple[int, int] | None:
    if isinstance(value, str) and "x" in value.lower():
        left, right = value.lower().split("x", 1)
        try:
            return int(left), int(right)
        except ValueError:
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0] or 0), int(value[1] or 0)
        except (TypeError, ValueError):
            return None
    return None


def _is_16_9_size(value: Any) -> bool:
    size = _size_tuple(value)
    return bool(size and _is_16_9_tuple(size))


def _is_16_9_tuple(size: tuple[int, int]) -> bool:
    width, height = size
    return width > 0 and height > 0 and abs((width / height) - (16 / 9)) < 0.02


def _make_even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def _apply_sensor_constraint(task: dict[str, Any], sensor_mode: dict[str, Any]) -> None:
    sensor_fps = _float_or_none(sensor_mode.get("sensor_fps"))
    v_valid_ms = _float_or_none(sensor_mode.get("v_valid_ms")) or _calc_v_valid_ms(sensor_mode)
    task["constraint_type"] = "source"
    if sensor_fps and sensor_fps > 0:
        task["source_fps"] = sensor_fps
        task["release_period_ms"] = 1000.0 / sensor_fps
    if v_valid_ms and v_valid_ms > 0:
        task["v_valid_ms"] = v_valid_ms
        task["source_valid_ms"] = v_valid_ms
        if not float(task.get("duration_ms") or 0.0):
            task["duration_ms"] = v_valid_ms


def _apply_panel_constraint(task: dict[str, Any], panel: dict[str, Any], graph: CanonicalScenarioGraph) -> None:
    refresh_hz = _selected_refresh_hz(panel, _variant_fps(graph))
    if not refresh_hz or refresh_hz <= 0:
        return
    scanout_ms = 1000.0 / refresh_hz
    task["constraint_type"] = "sink"
    task["refresh_hz"] = refresh_hz
    task["scanout_ms"] = scanout_ms
    task["deadline_ms"] = scanout_ms


def _is_sensor_timeline_task(task: dict[str, Any], node: dict[str, Any]) -> bool:
    text = _task_node_text(task, node)
    return "sensor" in text


def _is_display_sink_task(task: dict[str, Any], node: dict[str, Any]) -> bool:
    text = _task_node_text(task, node)
    return "panel" in text or "dpu" in text or "display" in text


def _task_node_text(task: dict[str, Any], node: dict[str, Any]) -> str:
    return " ".join(
        str(value or "").lower()
        for value in (
            task.get("id"),
            task.get("node_id"),
            task.get("hw_name"),
            node.get("id"),
            node.get("role"),
            node.get("label"),
            node.get("ip_ref"),
        )
    )


def _capability_properties(ip_row: Any) -> dict[str, Any]:
    capabilities = ip_row.capabilities or {}
    properties = capabilities.get("properties") if isinstance(capabilities, dict) else None
    return properties if isinstance(properties, dict) else {}


def _mode_by_fps(modes: dict[str, Any], fps: float) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for mode in modes.values():
        if not isinstance(mode, dict):
            continue
        sensor_fps = _float_or_none(mode.get("sensor_fps"))
        if sensor_fps is None:
            continue
        score = abs(sensor_fps - fps)
        if best is None or score < best[0]:
            best = (score, mode)
    return best[1] if best else None


def _selected_refresh_hz(panel: dict[str, Any], fps: float) -> float | None:
    raw = panel.get("refresh_rates") or panel.get("refresh_rate")
    rates = raw if isinstance(raw, list) else [raw]
    values = sorted(value for value in (_float_or_none(item) for item in rates) if value and value > 0)
    if not values:
        return None
    for value in values:
        if value >= fps:
            return value
    return values[-1]


def _calc_v_valid_ms(mode: dict[str, Any]) -> float | None:
    size = mode.get("active_size") or mode.get("sensor_size")
    pclk = _float_or_none(mode.get("sensor_pclk"))
    line_length = _float_or_none(mode.get("sensor_line_length_pck"))
    height = _size_tuple(size)[1] if _size_tuple(size) else None
    if height and pclk and line_length:
        return round(line_length * 1000.0 / pclk * height, 6)
    sensor_fps = _float_or_none(mode.get("sensor_fps"))
    if sensor_fps and sensor_fps > 0:
        return round(1000.0 / sensor_fps, 6)
    return None


def _v_valid_source(mode: dict[str, Any]) -> str | None:
    if mode.get("v_valid_ms") is not None:
        return "explicit_v_valid_ms"
    if mode.get("sensor_pclk") and mode.get("sensor_line_length_pck"):
        return "sensor_line_length_pck * 1000 / sensor_pclk * height"
    if mode.get("sensor_fps"):
        return "frame_period_fallback_no_vblank"
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _variant_fps(graph: CanonicalScenarioGraph) -> float:
    design = graph.variant.design_conditions or {}
    return float(design.get("fps") or 30.0)


def _design_size(graph: CanonicalScenarioGraph) -> tuple[int, int]:
    design = graph.variant.design_conditions or {}
    for key in ("size", "resolution_size", "output_size"):
        value = design.get(key)
        if isinstance(value, str) and "x" in value.lower():
            left, right = value.lower().split("x", 1)
            return int(left), int(right)
    value = design.get("resolution")
    mapping = {
        "FHD": (1920, 1080),
        "QHD": (2560, 1440),
        "UHD": (3840, 2160),
        "4K": (3840, 2160),
        "8K": (7680, 4320),
    }
    return mapping.get(str(value).upper(), (0, 0))
