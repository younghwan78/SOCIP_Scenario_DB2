"""Verified DT mode-index to reusable CIS timing references."""
from copy import deepcopy
import hashlib
import json
from scenario_db.models.sensor import SensorTiming, SensorTimingBinding
from scenario_db.sim.sensor_timing import calculate_sensor_timing, catalog_mode_timing


def timing_mode_hash(mode):
    normalized = SensorTiming.model_validate(mode).model_dump(mode="json", exclude_none=True)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def resolve_timing_binding(catalog, mode, profile):
    binding = SensorTimingBinding.model_validate(mode["timing_binding"])
    if profile is None or profile["id"] != binding.profile_ref:
        raise ValueError("referenced CIS timing profile is missing")
    if profile["sensor_name"] != catalog["sensor_name"]:
        raise ValueError("CIS timing sensor differs from DT sensor")
    if profile["revision"] != binding.profile_revision:
        raise ValueError("CIS timing revision changed; review DT binding again")
    timing = profile["modes"].get(binding.mode_label)
    if timing is None or timing_mode_hash(timing) != binding.mode_sha256:
        raise ValueError("CIS timing mode is missing or its inputs changed")
    decoded = mode["decoded"]
    if decoded.get("mode_index") != binding.mode_index:
        raise ValueError("DT mode index differs from reviewed binding")
    if decoded.get("size") != [timing["active_width"], timing["active_height"]]:
        raise ValueError("DT/CIS readout dimensions differ")
    # v1 bindings describe a basic setfile readout, not runtime seamless changes.
    if decoded.get("ex_mode") != "EX_NONE" or mode.get("option", {}).get("ex_mode_extra"):
        raise ValueError("extended DT mode needs an explicit runtime readout contract")
    images = [v for channels in mode.get("vc", {}).values() for v in channels.values()
              if v.get("data_class") == "image"]
    if len(images) != 1:
        raise ValueError("timing binding requires a single image readout")
    cis_bits = timing["source"].get("bits_per_pixel")
    if cis_bits is not None and images[0].get("bits_per_pixel") != cis_bits:
        raise ValueError("DT image bit depth differs from CIS timing mode")
    return {**deepcopy(timing), "source": {**timing["source"],
            "timing_profile_id": profile["id"], "revision": profile["revision"],
            "mode_label": binding.mode_label, "mode_sha256": binding.mode_sha256,
            "dt_mode_index": binding.mode_index, "mapping_evidence": binding.source}}


def catalog_timing(db, catalog_row, mode_label):
    from scenario_db.db.models.sensor import SensorTimingProfile
    mode = catalog_row.document["modes"][mode_label]
    if not mode.get("timing_binding"):
        result = catalog_mode_timing(mode)
        if mode.get("timing"):
            result["inputs"] = mode["timing"]
        result["binding_status"] = "inline" if mode.get("timing") else "unmapped"
        result["binding_reason"] = mode.get("timing_binding_note", "No reviewed DT-to-CIS timing mapping is imported for this mode.")
        return result
    profile = db.get(SensorTimingProfile, mode["timing_binding"]["profile_ref"])
    try:
        timing = resolve_timing_binding(catalog_row.document, mode, profile.document if profile else None)
    except ValueError as exc:
        return {"status": "invalid_binding", "binding_status": "invalid", "binding_reason": str(exc),
                "valid_time_ms": None, "csis_frame_window_ms": None}
    timing["source"]["timing_profile_sha256"] = profile.yaml_sha256
    timing["source"].update(catalog_id=catalog_row.id, catalog_sha256=catalog_row.yaml_sha256, dt_mode_label=mode_label)
    return {**calculate_sensor_timing(timing), "binding_status": "verified_mode_index",
            "nominal_dt_fps": mode["decoded"].get("fps"), "inputs": timing,
            "binding_note": mode["timing_binding"]["source"].get("selection", "Reviewed basic setfile readout; runtime transitions require explicit selection.")}
