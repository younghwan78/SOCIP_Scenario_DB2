from __future__ import annotations

from typing import Any


def scenario_description_rows(evidence: dict[str, Any]) -> dict[str, str]:
    sensor = _first_external(evidence, "sensor")
    kpi = _dict(evidence.get("kpi"))
    return {
        "Scenario": _text(evidence.get("scenario_ref")),
        "Variant": _text(evidence.get("variant_ref")),
        "Sensor": _text(sensor.get("name") or sensor.get("ip_ref") or sensor.get("node_id")),
        "Resolution": _size_text(sensor),
        "FPS": _number_text(sensor.get("fps") or kpi.get("fps")),
        "Format": _text(sensor.get("format")),
        "Timeline End": _ms(kpi.get("timeline_end_ms")),
    }


def basic_conditions_rows(evidence: dict[str, Any]) -> dict[str, str]:
    context = _dict(evidence.get("execution_context"))
    run_info = _dict(evidence.get("run_info"))
    ambient = _number(context.get("ambient_temp_c"))
    return {
        "Silicon Rev": _text(context.get("silicon_rev")),
        "SW Baseline": _text(evidence.get("sw_baseline_ref") or context.get("sw_baseline_ref")),
        "Thermal": _text(context.get("thermal")),
        "Ambient": "-" if ambient is None else f"{ambient:g} C",
        "Tool": _text(run_info.get("tool")),
        "Timestamp": _text(run_info.get("timestamp")),
        "Params Hash": _text(evidence.get("params_hash")),
    }


def dvfs_guide_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    seen: set[str] = set()
    for item in _list(evidence.get("dvfs_breakdown")):
        group = _text(item.get("dvfs_group"))
        if not group or group == "-" or group in seen:
            continue
        seen.add(group)
        rows.append(
            {
                "DVFS Domain": group,
                "Set Clock (MHz)": _fixed(item.get("set_clock_mhz"), 1),
                "DVFS Level": _text(item.get("dvfs_level")),
                "Set Voltage (mV)": _fixed(item.get("set_voltage_mv"), 2),
            }
        )
    if _dict(evidence.get("kpi")).get("total_bw_mbs") is not None:
        rows.append(
            {
                "DVFS Domain": "MIF",
                "Set Clock (MHz)": "-",
                "DVFS Level": "derived from total BW",
                "Set Voltage (mV)": "-",
            }
        )
    return rows


def power_summary_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    vdd_power = _dict(evidence.get("vdd_power"))
    for vdd, values in sorted(vdd_power.items()):
        value_map = _dict(values)
        rows.append(
            {
                "VDD": str(vdd),
                "Core Power (mW)": _fixed(value_map.get("core_mw"), 2),
                "BW Power (mW)": _fixed(value_map.get("bw_mw"), 2),
                "Total Power (mW)": _fixed(value_map.get("total_mw"), 2),
            }
        )
    kpi = _dict(evidence.get("kpi"))
    rows.append(
        {
            "VDD": "Total",
            "Core Power (mW)": _fixed(kpi.get("core_power_mw"), 2),
            "BW Power (mW)": _fixed(kpi.get("bw_power_mw"), 2),
            "Total Power (mW)": _fixed(kpi.get("total_power_mw"), 2),
            "Total Current (mA)": _fixed(kpi.get("total_power_ma"), 2),
        }
    )
    return rows


def ip_detail_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    timing_by_node = {str(item.get("node_id")): item for item in _list(evidence.get("timing_breakdown"))}
    kpi = _dict(evidence.get("kpi"))
    rows = []
    for item in _list(evidence.get("dvfs_breakdown")):
        timing = timing_by_node.get(str(item.get("node_id"))) or {}
        rows.append(
            {
                "Node": _text(item.get("node_id")),
                "IP Ref": _text(item.get("ip_ref")),
                "HW": _text(item.get("hw_name")),
                "Mode": _text(item.get("mode")),
                "PPC": _number_text(item.get("ppc")),
                "Unit Power": _fixed(item.get("unit_power_mw_mp"), 3),
                "Input Res": _resolution_text(item),
                "VDD": _text(item.get("vdd")),
                "DVFS": _text(item.get("dvfs_group")),
                "Req Freq": _fixed(item.get("required_clock_mhz"), 1),
                "Set Freq": _fixed(item.get("set_clock_mhz"), 1),
                "Set Volt": _fixed(item.get("set_voltage_mv"), 2),
                "Power(mW)": _fixed(item.get("total_power_mw"), 2),
                "Current(mA)": _fixed(item.get("total_power_ma"), 2),
                "HW Time(ms)": _fixed(timing.get("hw_time_ms") or kpi.get("hw_time_max_ms"), 3),
            }
        )
    return rows


def dma_report_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in _list(evidence.get("dma_breakdown")):
        rows.append(
            {
                "Node": _text(item.get("node_id")),
                "HW": _text(item.get("hw_name")),
                "Name": _text(item.get("port")),
                "In/Out": _text(item.get("direction")).title(),
                "WxH": _wh(item),
                "Format": _text(item.get("format")),
                "Bitwidth": _text(item.get("bitwidth")),
                "Comp": _text(item.get("compression")),
                "BW (MB/s)": _fixed(item.get("bw_mbs"), 1),
                "BW Power (mW)": _fixed(item.get("bw_power_mw"), 2),
                "BW Current (mA)": _fixed(item.get("bw_power_ma"), 2),
                "LLC": _text(item.get("llc_enabled")),
            }
        )
    return rows


def timeline_report_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in _list(evidence.get("timeline_events")):
        rows.append(
            {
                "Frame": _text(item.get("frame_index")),
                "Task": _text(item.get("task_id")),
                "Node": _text(item.get("node_id")),
                "Resource": _text(item.get("resource_id")),
                "Type": _text(item.get("task_type")),
                "Edge": _text(item.get("edge_type")),
                "Start(ms)": _fixed(item.get("start_ms"), 3),
                "End(ms)": _fixed(item.get("end_ms"), 3),
                "Duration(ms)": _fixed(item.get("duration_ms"), 3),
                "Slack(ms)": _fixed(item.get("slack_ms"), 3),
                "Critical": _text(item.get("critical")),
            }
        )
    return rows


def external_device_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in _list(evidence.get("external_devices")):
        rows.append(
            {
                "Type": _text(item.get("device_type")),
                "Node": _text(item.get("node_id")),
                "Name": _text(item.get("name") or item.get("ip_ref")),
                "Role": _text(item.get("role")),
                "Size": _size_text(item),
                "Format": _text(item.get("format")),
                "FPS": _number_text(item.get("fps")),
                "V Valid(ms)": _fixed(item.get("v_valid_ms"), 3),
                "Refresh(Hz)": _number_text(item.get("refresh_hz")),
                "Scanout(ms)": _fixed(item.get("scanout_ms"), 3),
            }
        )
    return rows


def _first_external(evidence: dict[str, Any], device_type: str) -> dict[str, Any]:
    for item in _list(evidence.get("external_devices")):
        if str(item.get("device_type") or "").lower() == device_type:
            return item
    return {}


def _size_text(row: dict[str, Any]) -> str:
    value = row.get("active_size") or row.get("catalog_size") or row.get("size")
    if isinstance(value, str) and value:
        return value
    return _wh(row)


def _resolution_text(row: dict[str, Any]) -> str:
    width = _number(row.get("width"))
    height = _number(row.get("height"))
    if width and height:
        return f"{int(width)}x{int(height)}"
    mp = _number(row.get("input_resolution_mp"))
    return "-" if mp is None else f"{mp:.3f} MP"


def _wh(row: dict[str, Any]) -> str:
    width = _number(row.get("width"))
    height = _number(row.get("height"))
    return "-" if not width or not height else f"{int(width)}x{int(height)}"


def _ms(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.3f} ms"


def _fixed(value: Any, digits: int) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.{digits}f}"


def _number_text(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:g}"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]
