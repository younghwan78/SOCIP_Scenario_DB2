"""DT-declared wire payload estimates, independent of readout and DRAM timing."""
from math import isfinite
from typing import Any


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def calculate_sensor_transport(mode: dict[str, Any], wiring: dict[str, Any]) -> dict[str, Any]:
    decoded = mode.get("decoded") or {}
    option = mode.get("option") or {}
    nominal = decoded.get("fps")
    cap = option.get("max_fps")
    fps = min(nominal, cap) if positive(nominal) and positive(cap) else nominal
    fps = fps if positive(fps) else None
    phy = wiring.get("phy")
    lanes, speed = decoded.get("lanes"), decoded.get("mipi_speed_mbps")
    # Producer README cites is-hw-dvfs.c get_mbps for this conversion.
    capacity = (lanes * speed * (16 / 7 if phy == "CPHY" else 1)
                if phy in ("CPHY", "DPHY") and positive(lanes) and positive(speed) else None)
    rows, seen, incomplete = [], {}, False
    total, images = 0.0, 0
    for dma, channels in (mode.get("vc") or {}).items():
        for vc, data in channels.items():
            if data.get("data_class") == "none":
                continue
            size = data.get("size")
            bpp = data.get("bits_per_pixel")
            valid = (isinstance(size, (list, tuple)) and len(size) == 2
                     and all(positive(v) for v in size) and positive(bpp))
            payload = size[0] * size[1] * bpp / 8 if valid else None
            # One incoming VC/data type can be routed to multiple DMA outputs.
            identity = (data.get("map"), data.get("hwformat_base"))
            signature = (tuple(size or []), bpp, data.get("data_class"))
            known_identity = identity[0] is not None and identity[1] is not None
            duplicate = known_identity and identity in seen and seen[identity] == signature
            conflict = known_identity and identity in seen and seen[identity] != signature
            incomplete |= not valid or not known_identity or conflict
            if not duplicate:
                total += payload or 0
                images += data.get("data_class") == "image"
            if known_identity:
                seen[identity] = signature
            rows.append({"route": f"{dma}/{vc}", "wire_map": data.get("map"),
                         "format": data.get("hwformat_base"), "data_class": data.get("data_class"),
                         "size": size, "bits_per_pixel": bpp, "payload_bytes": payload,
                         "duplicate_route": duplicate, "conflicting_route": conflict})
    incomplete |= not rows
    declared = None if incomplete else total
    all_vc_rate = declared * fps if declared is not None and fps is not None else None
    multi = images > 1 or decoded.get("ex_mode") in ("EX_AEB", "EX_DCG")
    status = "missing_input" if incomplete or fps is None else "cadence_unresolved" if multi else "calculated"
    actual = all_vc_rate if status == "calculated" else None
    utilization = actual * 8 / (capacity * 1e6) * 100 if actual is not None and capacity else None
    return {
        "version": "sensor-transport-v1", "status": status,
        "value_source": "calculated_from_dt", "phy": phy,
        "nominal_fps": nominal, "max_fps": cap, "assumed_fps": fps,
        "link_capacity_mbps": capacity,
        "declared_unique_vc_payload_bytes": declared,
        "all_vcs_at_assumed_fps_bytes_s": all_vc_rate,
        "csis_payload_bytes_s": actual,
        "payload_link_utilization_pct": utilization,
        "link_status": ("unknown" if utilization is None else
                        "payload_exceeds_capacity" if utilization > 100 else "payload_within_capacity"),
        "dram_write_bytes_s": None, "dram_status": "routing_and_memory_format_required",
        "vc_rows": rows,
        "assumptions": [
            "Single-image mode: every declared unique VC repeats at min(DT fps, positive max_fps).",
            "Multiple image VC / AEB / DCG cadence is unresolved; nominal VC sum is diagnostic only.",
            "Payload excludes packet/PHY overhead and burst timing; within capacity does not prove feasibility.",
            "Payload/link transfer time is not sensor Valid Time or CSIS FS-FE duration.",
            "DRAM requires route, packing, stride, compression and vOTF decisions; no payload-to-DRAM copy is assumed.",
        ],
    }
