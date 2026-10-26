"""Pinned Sensor Catalog experiments using the existing projection validator.

Only detached scenario inputs are reshaped. Installation is validated on the
named source board; target-board wiring and measured sensor power remain unknown.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from scenario_db.db.models.capability import IpCatalog
from scenario_db.db.models.sensor import SensorBoardLineup, SensorCatalog
from scenario_db.sim.external_devices import _active_sensor_size, active_sensor_nodes, selected_sensor_mode
from scenario_db.sim.sensor_projection import resolve_sensor_modes
from scenario_db.sim.sensor_transport import calculate_sensor_transport


# Kernel board catalogs use the chip ID; project/platform records use the
# public SoC ID. Keep this correspondence explicit rather than guessing from
# board names or IP suffixes, which could admit an unrelated source platform.
_SOURCE_SOC_IDS = {"soc-exynos2600": frozenset({"soc-exynos2600", "s5e9965"})}


def _same_source_soc(source_soc: Any, target_soc: str | None) -> bool:
    return bool(target_soc and source_soc in _SOURCE_SOC_IDS.get(target_soc, {target_soc}))


class SensorPowerSample(BaseModel):
    """An exact operating-point sample, never an inferred FPS power curve."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    status: Literal["measured"]
    power_mw: float = Field(ge=0)
    fps: float = Field(gt=0)
    source: str | dict[str, Any] = Field(min_length=1)
    conditions: dict[str, Any] = Field(default_factory=dict)


def _active_sensors(graph):
    return [node for node in active_sensor_nodes(graph)
            if ((graph.variant.node_configs or {}).get(str(node["id"]), {}).get("sim") or {}).get("active") is not False]


def _soc(graph) -> str | None:
    project = getattr(graph, "project", None)
    return str(getattr(getattr(graph, "soc", None), "id", None) or
               (getattr(project, "metadata_", None) or {}).get("soc_ref") or
               (getattr(project, "globals_", None) or {}).get("soc_ref") or "") or None


def _sensor_ips(db, graph) -> dict[str, Any]:
    soc = _soc(graph)
    if not soc:
        return {}
    rows = db.query(IpCatalog).filter(IpCatalog.category == "sensor").order_by(IpCatalog.id).all()
    return {str(r.id): r for r in rows if soc in (r.compatible_soc or [])}


def _sensor_name(ip) -> str | None:
    return ((ip.capabilities or {}).get("properties") or {}).get("sensor_name")


def _installations(catalog, lineups, soc: str | None) -> list[dict]:
    found = []
    for lineup in lineups:
        document = lineup.document or {}
        if not _same_source_soc(document.get("soc"), soc):
            continue
        for config in (document.get("boards", {}).get(catalog.board, {}) or {}).get("configs", []):
            for slot, installed in sorted((config.get("lineup") or {}).items()):
                installed = [installed] if isinstance(installed, str) else installed
                if catalog.sensor_name in (installed or []):
                    found.append({"lineup_ref": lineup.id, "lineup_sha256": lineup.yaml_sha256,
                                  "board_config": config["config"], "slot": slot})
    return sorted(found, key=lambda r: (r["lineup_ref"], r["board_config"], r["slot"]))


def catalog_binding_targets(db, graph, fps: float | None = None) -> list[dict]:
    """Full mode identities, with a reproducible installed source selection.

    Catalogs without a compatible IP identity or installed source are not offered.
    The selected source config/slot is shown in every label, never inferred later.
    """
    soc = _soc(graph)
    ips = _sensor_ips(db, graph)
    names = {_sensor_name(ip) for ip in ips.values()}
    if not names:
        return []
    catalogs = db.query(SensorCatalog).filter(SensorCatalog.sensor_name.in_(names)).order_by(SensorCatalog.id).all()
    lineups = db.query(SensorBoardLineup).order_by(SensorBoardLineup.id).all()
    options = []
    for catalog in catalogs:
        installs = _installations(catalog, lineups, soc)
        if not installs:
            continue
        # A mode is listed once; its complete selected source identity is pinned.
        source = installs[0]
        for label, mode in (catalog.document.get("modes") or {}).items():
            transport = calculate_sensor_transport(mode, catalog.document.get("csis_wiring") or {})
            decoded = mode.get("decoded") or {}
            binding = {**source, "catalog_ref": catalog.id, "catalog_sha256": catalog.yaml_sha256, "mode_label": label}
            maximum = transport.get("assumed_fps")
            compatible = not (fps and isinstance(maximum, (int, float)) and maximum < fps)
            supported = transport.get("status") == "calculated"
            reason = None if supported else "single-image cadence/transport가 확정되지 않은 mode"
            if supported and not compatible:
                reason = f"목표 FPS를 {maximum:g} 이하로 함께 변경해야 함"
            timing = mode.get("timing_binding") or mode.get("timing")
            options.append({"id": f"{catalog.id}#{label}", "sensor": catalog.sensor_name,
                            "ip_ref": next(key for key, ip in ips.items() if _sensor_name(ip) == catalog.sensor_name),
                            "mode": label, "size": decoded.get("size"), "fps": maximum,
                            "bitwidth": next((v.get("bits_per_pixel") for v in transport.get("vc_rows", [])
                                              if v.get("data_class") == "image" and not v.get("duplicate_route")), None),
                            "supported": supported, "fps_compatible": compatible, "reason": reason,
                            "sensor_binding": binding,
                            "evidence": {"status": "bound" if timing else "missing_timing", "source": catalog.id,
                                         "note": "source board 설치 검증 · target 배선/IQ/센서 전력 미검증"},
                            "label": f"{catalog.sensor_name} · {label} · {catalog.board}/{source['board_config']}/{source['slot']}"})
    return [{"id": str(node["id"]), "node_id": str(node["id"]), "options": options,
             "option_count": len(options), "truncated": False}
            for node in _active_sensors(graph)]


def _mode_seed(db, catalog, binding, graph) -> dict:
    mode = (catalog.document.get("modes") or {}).get(binding.mode_label)
    if mode is None:
        raise ValueError("unknown full DT mode label")
    transport = calculate_sensor_transport(mode, catalog.document.get("csis_wiring") or {})
    images = [r for r in transport.get("vc_rows", []) if r.get("data_class") == "image" and not r.get("duplicate_route")]
    if transport.get("status") != "calculated" or len(images) != 1:
        raise ValueError("sensor binding requires resolved single-image cadence and transport")
    decoded = mode["decoded"]
    seed = {"sensor_name": catalog.sensor_name, "sensor_size": list(decoded["size"]),
            "sensor_format": "BAYER", "sensor_bitwidth": images[0]["bits_per_pixel"],
            "sensor_fps": transport["assumed_fps"], "mode_id": binding.mode_label}
    if "power_model" in mode:
        seed["power_model"] = deepcopy(mode["power_model"])
    active, source = _active_sensor_size(seed, graph)
    if not active or min(active) <= 0:
        raise ValueError("sensor mode has no valid active geometry")
    seed.update(active_size=list(active), active_size_source=source)
    return seed


def prepare_sensor_graph(db, graph, config):
    """Reshape a new pinned candidate once, then reuse strict projection validation.

    Calling this after all other changes only revalidates the binding; it does not
    replay geometry transforms and overwrite subsequent crop/scaling conditions.
    """
    if not config.sensor_modes:
        return graph
    from scenario_db.api.services.whatif_levers import _all_anchors, _anchors_on, _downstream, _place_anchor, _reshape, reset_pipeline
    candidate = replace(graph, scenario=deepcopy(graph.scenario), variant=deepcopy(graph.variant), ip_catalog=dict(graph.ip_catalog))
    candidate.variant.node_configs = deepcopy(candidate.variant.node_configs or {})
    candidate.variant.size_overrides = deepcopy(candidate.variant.size_overrides or {})
    candidate.variant.buffer_overrides = deepcopy(candidate.variant.buffer_overrides or {})
    candidate.variant.design_conditions = deepcopy(candidate.variant.design_conditions or {})
    active = {str(n["id"]): n for n in _active_sensors(candidate)}
    ips = None
    for node_id, binding in config.sensor_modes.items():
        if node_id not in active:
            raise ValueError(f"{node_id}: binding requires an active sensor node")
        catalog = db.get(SensorCatalog, binding.catalog_ref)
        lineup = db.get(SensorBoardLineup, binding.lineup_ref)
        if catalog is None or lineup is None:
            raise ValueError("sensor catalog/lineup must exist")
        if catalog.yaml_sha256 != binding.catalog_sha256 or lineup.yaml_sha256 != binding.lineup_sha256:
            raise ValueError("sensor source hash changed; prepare the binding again")
        if not _same_source_soc((lineup.document or {}).get("soc"), _soc(graph)):
            raise ValueError("sensor source lineup belongs to another SoC")
        previous = selected_sensor_mode(candidate, active[node_id]) or {}
        prior_binding = previous.get("catalog_binding") or {}
        if all(prior_binding.get(k) == v for k, v in binding.model_dump().items()):
            continue
        if ips is None:
            ips = _sensor_ips(db, candidate)
        match = next((ip for ip in ips.values() if _sensor_name(ip) == catalog.sensor_name), None)
        if match is None:
            raise ValueError("selected sensor has no IP identity compatible with this SoC")
        seed = _mode_seed(db, catalog, binding, candidate)
        node = next((n for n in (candidate.scenario.pipeline or {}).get("nodes", []) if str(n.get("id")) == node_id), None)
        if node is None:
            raise ValueError("sensor node must belong to the scenario pipeline")
        node["ip_ref"] = str(match.id)
        candidate.ip_catalog[str(match.id)] = match
        reset_pipeline(candidate)
        old, new = tuple(previous.get("active_size") or previous.get("sensor_size") or []), tuple(seed["active_size"])
        if len(old) != 2 or min(old) <= 0:
            raise ValueError("baseline sensor has no known active geometry")
        if old != new:
            nodes = _downstream(candidate, node_id, None)
            anchors = _anchors_on(candidate, set(nodes))
            anchors |= {k for k, size in _all_anchors(candidate).items() if size == old and _place_anchor(k, previous.get("place"))}
            from scenario_db.api.services.whatif_conditions import _anchor_role, _buffers
            by_id = {str(n.get("id")): n for n in candidate.pipeline_nodes}
            protected = {a for a in _all_anchors(candidate) if _anchor_role(candidate, a, _buffers(candidate), by_id) is not None}
            _reshape(candidate, nodes, anchors - protected, old, new, preserve_outputs=True, protected_anchors=protected)
        cfg = candidate.variant.node_configs.setdefault(node_id, {})
        for key in ("mode", "sensor_mode", "sensor_mode_ref", "sensor_readout"):
            cfg.pop(key, None)
        cfg["resolved_sensor_mode"] = seed
        # RAW precision changes apply only to the RAW section, never YUV output.
        bitwidth = seed["sensor_bitwidth"]
        downstream = set(_downstream(candidate, node_id, None))
        for affected in downstream:
            sim = (candidate.variant.node_configs.get(affected) or {}).get("sim") or {}
            fmt = str(sim.get("format") or "").upper()
            if any(token in fmt for token in ("BAYER", "RAW", "RGGB", "BGGR", "GBRG", "GRBG")):
                sim["bitwidth"] = bitwidth
        from scenario_db.api.services.whatif_conditions import _buffers
        from scenario_db.sim.graph_edges import edge_source, edge_target
        local_buffers = {e.get("buffer") for e in candidate.pipeline_edges
                         if {str(edge_source(e)), str(edge_target(e))} & downstream}
        for buffer_id, descriptor in _buffers(candidate).items():
            owned = any(str((descriptor.get(key) or {}).get("node_id") or "") in downstream for key in ("history", "dma"))
            fmt = str(descriptor.get("format") or "").upper()
            if (buffer_id in local_buffers or owned) and any(token in fmt for token in ("BAYER", "RAW", "RGGB", "BGGR", "GBRG", "GRBG")):
                override = candidate.variant.buffer_overrides.setdefault(buffer_id, {})
                override["bitdepth"] = bitwidth
                if "bitwidth" in descriptor:
                    override["bitwidth"] = bitwidth
        if "sensor_bitwidth" in candidate.variant.design_conditions:
            candidate.variant.design_conditions["sensor_bitwidth"] = bitwidth
    return resolve_sensor_modes(db, candidate, config)


def sensor_power_coverage(graph, fps: float | None = None) -> dict:
    """Optional measured rail power is used only at its exact sampled cadence."""
    rows = []
    target_fps = fps if fps is not None else (graph.variant.design_conditions or {}).get("fps")
    for node in _active_sensors(graph):
        mode = selected_sensor_mode(graph, node) or {}
        profile = mode.get("power_model") or {}
        sample, reason = None, "no measured sensor power sample"
        try:
            sample = SensorPowerSample.model_validate(profile)
            if not isinstance(target_fps, (int, float)) or not math.isclose(sample.fps, target_fps, rel_tol=0, abs_tol=1e-6):
                sample, reason = None, "sensor power sample FPS differs from the requested cadence"
        except ValidationError:
            if profile:
                reason = "invalid sensor power evidence; power_mw, fps and source are required"
        rows.append({"node_id": str(node["id"]), "power_mw": sample.power_mw if sample else None,
                     "status": "measured" if sample else "unknown", "reason": None if sample else reason,
                     "source": sample.source if sample else None, "fps": sample.fps if sample else None})
    complete = bool(rows) and all(r["power_mw"] is not None for r in rows)
    return {"power_mw": sum(r["power_mw"] for r in rows) if complete else None, "complete": complete, "nodes": rows}
