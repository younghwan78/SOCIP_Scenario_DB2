"""Build scenario-aware Level 2 expand choices for Pipeline Viewer."""
from __future__ import annotations

from dataclasses import dataclass

from scenario_db.api.schemas.view import NodeElement, ViewResponse


@dataclass(frozen=True)
class Level2ExpandOption:
    label: str
    value: str
    kind: str


CUSTOM_EXPAND_OPTION = Level2ExpandOption("Custom node/IP id", "__custom__", "custom")


def build_level2_expand_options(level1_view: ViewResponse | None) -> list[Level2ExpandOption]:
    """Return Level 2 choices that are valid for the active scenario shape."""

    candidates = _active_level1_ip_nodes(level1_view)
    options: list[Level2ExpandOption] = []

    if any(_is_camera_candidate(node) for node in candidates):
        options.append(Level2ExpandOption("Camera pipeline (active ISP blocks)", "camera", "alias"))
    if any(_is_video_candidate(node) for node in candidates):
        options.append(Level2ExpandOption("Video encode/decode (active codec blocks)", "video", "alias"))
    if any(_is_display_candidate(node) for node in candidates):
        options.append(Level2ExpandOption("Display output (active DPU blocks)", "display", "alias"))

    seen_values = {option.value for option in options}
    for node in candidates:
        value = _pipeline_node_id(node)
        if not value or value in seen_values:
            continue
        seen_values.add(value)
        options.append(Level2ExpandOption(_node_option_label(node), value, "node"))

    options.append(CUSTOM_EXPAND_OPTION)
    return options


def default_level2_expand_value(options: list[Level2ExpandOption]) -> str:
    for option in options:
        if option.value != CUSTOM_EXPAND_OPTION.value:
            return option.value
    return CUSTOM_EXPAND_OPTION.value


def has_concrete_level2_options(options: list[Level2ExpandOption]) -> bool:
    return any(option.value != CUSTOM_EXPAND_OPTION.value for option in options)


def selected_level2_expand_value(
    options: list[Level2ExpandOption],
    *,
    previous_value: str | None,
    previous_context: str | None,
    current_context: str,
) -> str:
    option_values = {option.value for option in options}
    if previous_context != current_context:
        return default_level2_expand_value(options)
    if previous_value in option_values:
        return str(previous_value)
    return default_level2_expand_value(options)


def custom_level2_expand_default(
    *,
    previous_value: str | None,
    previous_context: str | None,
    current_context: str,
) -> str:
    if previous_context != current_context:
        return ""
    return str(previous_value or "")


def level2_expand_request_target(selected_value: str | None, custom_value: str | None) -> str | None:
    if selected_value == CUSTOM_EXPAND_OPTION.value:
        target = str(custom_value or "").strip()
        return target or None
    target = str(selected_value or "").strip()
    return target or None


def _active_level1_ip_nodes(level1_view: ViewResponse | None) -> list[NodeElement]:
    if level1_view is None:
        return []
    nodes: list[NodeElement] = []
    for node in level1_view.nodes:
        data = node.data
        if data.type != "ip":
            continue
        if not data.id.startswith("ip-"):
            continue
        if data.layer in {"external", "memory", "meta"}:
            continue
        nodes.append(node)
    return nodes


def _is_camera_candidate(node: NodeElement) -> bool:
    data = node.data
    return data.hierarchy_group == "ISP"


def _is_video_candidate(node: NodeElement) -> bool:
    data = node.data
    text = _node_text(node)
    return data.hierarchy_group == "CODEC" or data.ip_group in {"MFC", "APV"} or "mfc" in text or "codec" in text


def _is_display_candidate(node: NodeElement) -> bool:
    data = node.data
    text = _node_text(node)
    return data.ip_group == "DPU" or "dpu" in text or "decon" in text


def _pipeline_node_id(node: NodeElement) -> str:
    return node.data.id.removeprefix("ip-")


def _node_option_label(node: NodeElement) -> str:
    data = node.data
    group = data.ip_group or data.hierarchy_group or data.layer
    label = str(data.label).splitlines()[0]
    return f"{label} ({group})"


def _node_text(node: NodeElement) -> str:
    data = node.data
    return " ".join(
        str(item or "")
        for item in (data.id, data.label, data.ip_ref, data.hierarchy_group, data.ip_group, data.role_hw_name)
    ).lower()
