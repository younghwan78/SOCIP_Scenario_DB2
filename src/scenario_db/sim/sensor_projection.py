"""Resolve pinned DT selections against DB before adapting simulation inputs."""
from copy import deepcopy
from dataclasses import replace
from scenario_db.db.models.sensor import SensorCatalog, SensorBoardLineup
from scenario_db.sim.external_devices import active_sensor_nodes, selected_sensor_mode
from scenario_db.sim.sensor_transport import calculate_sensor_transport, positive


def resolve_sensor_modes(db, graph, config):
    if not config.sensor_modes:
        return graph
    if set(config.sensor_modes) & set(config.sensor_readout):
        raise ValueError("DT binding and CIS readout require a verified mapping before combining")
    if config.timing_profile is not None:
        raise ValueError("sensor mode exploration cannot modify measured replay")
    variant = deepcopy(graph.variant)
    variant.node_configs = variant.node_configs or {}
    result = replace(graph, variant=variant)
    active = {str(n["id"]): n for n in active_sensor_nodes(graph)
              if ((variant.node_configs.get(str(n["id"])) or {}).get("sim") or {}).get("active") is not False}
    fps = config.fps if config.fps is not None else (variant.design_conditions or {}).get("fps", 30)
    if not positive(fps):
        raise ValueError("sensor projection requires positive finite scenario FPS")
    for node_id, binding in config.sensor_modes.items():
        if node_id not in active:
            raise ValueError(f"{node_id}: binding requires an active sensor node")
        catalog = db.get(SensorCatalog, binding.catalog_ref)
        lineup = db.get(SensorBoardLineup, binding.lineup_ref)
        if catalog is None or lineup is None:
            raise ValueError("sensor catalog/lineup must exist")
        if (catalog.yaml_sha256, lineup.yaml_sha256) != (binding.catalog_sha256, binding.lineup_sha256):
            raise ValueError("sensor source hash changed; prepare the binding again")
        configs = lineup.document.get("boards", {}).get(catalog.board, {}).get("configs", [])
        board = next((c for c in configs if c["config"] == binding.board_config), None)
        installed = (board or {}).get("lineup", {}).get(binding.slot, [])
        installed = [installed] if isinstance(installed, str) else installed
        if catalog.sensor_name not in installed:
            raise ValueError("sensor is not installed in this source board/config/slot")
        node = active[node_id]
        ip = graph.ip_catalog[node["ip_ref"]]
        props = (ip.capabilities or {}).get("properties", {})
        if props.get("sensor_name") != catalog.sensor_name:
            raise ValueError("source sensor differs from target node sensor")
        mode = catalog.document["modes"].get(binding.mode_label)
        if mode is None:
            raise ValueError("unknown full DT mode label")
        transport = calculate_sensor_transport(mode, catalog.document["csis_wiring"])
        if transport["status"] != "calculated":
            raise ValueError("mode requires complete payload and resolved single-image cadence")
        if fps > transport["assumed_fps"]:
            raise ValueError("scenario FPS exceeds the DT mode limit")
        base = selected_sensor_mode(graph, node) or {}
        if list(base.get("sensor_size") or []) != mode["decoded"].get("size"):
            raise ValueError("DT dimensions differ; explicit pipeline reshape is required")
        images = [r for r in transport["vc_rows"] if r["data_class"] == "image" and not r["duplicate_route"]]
        if len(images) != 1:
            raise ValueError("projection requires exactly one image VC")
        image = images[0]
        if image["bits_per_pixel"] != base.get("sensor_bitwidth"):
            raise ValueError("DT bit depth differs; explicit pipeline format update is required")
        # Evaluate the same DT payload at the scenario rate; retain full source snapshot.
        effective = deepcopy(mode)
        effective["decoded"]["fps"] = fps
        transport = calculate_sensor_transport(effective, catalog.document["csis_wiring"])
        if transport["link_status"] != "payload_within_capacity":
            raise ValueError("source link capacity is unknown or insufficient")
        source = {**binding.model_dump(), "board": catalog.board,
                  "target_project_ref": graph.scenario.project_ref,
                  "basis": "explicit source-board exploration; target wiring compatibility not certified"}
        projected = {**base, "mode_id": binding.mode_label, "sensor_fps": fps,
                     "sensor_phy_type": transport["phy"],
                     "sensor_mipi_speed": mode["decoded"]["mipi_speed_mbps"] / 1000,
                     "sensor_lanes": mode["decoded"]["lanes"],
                     "catalog_binding": source, "transport": transport,
                     "catalog_mode_snapshot": deepcopy(mode)}
        # A new DT selection must never inherit unrelated CIS timing from the old mode.
        for field in ("v_valid_ms", "sensor_pclk", "sensor_line_length_pck", "sensor_frame_length_lines", "timing_source"):
            projected.pop(field, None)
        from scenario_db.sim.sensor_timing_binding import catalog_timing
        timing_result = catalog_timing(db, catalog, binding.mode_label)
        if timing_result["status"] == "invalid_binding":
            raise ValueError(timing_result["binding_reason"])
        if timing_result["status"] == "calculated":
            if timing_result["valid_time_ms"] > 1000 / fps:
                raise ValueError("sensor readout exceeds scenario frame period")
            timing = timing_result["inputs"]
            projected.update(v_valid_ms=timing_result["valid_time_ms"],
                             sensor_pclk=timing["pixel_clock_hz"],
                             sensor_line_length_pck=timing["line_length_pck"],
                             sensor_frame_length_lines=timing["frame_length_lines"],
                             timing_source=timing["source"])
        cfg = variant.node_configs.setdefault(node_id, {})
        cfg.pop("sensor_readout", None)
        cfg["resolved_sensor_mode"] = projected
    return result
