from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scenario_db.legacy_import.ids import catalog_id
from scenario_db.legacy_import.read_legacy import read_yaml
from scenario_db.legacy_import.report import ImportReport


def load_legacy_sensor(path: Path, report: ImportReport) -> dict[str, dict[str, Any]]:
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        report.error("legacy_sensor_not_object", "Sensor config must be a YAML object.", str(path))
        return {}
    sensors = raw.get("sensors")
    if not isinstance(sensors, dict):
        report.error("legacy_sensor_missing_sensors", "Sensor config must contain a sensors object.", str(path))
        return {}
    return sensors


def convert_sensor_catalog(
    sensors: dict[str, dict[str, Any]],
    *,
    project_ref: str,
    schema_version: str,
    report: ImportReport,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for sensor_name, modes in sensors.items():
        source = f"sensors.{sensor_name}"
        if not isinstance(modes, dict):
            report.warning("legacy_sensor_modes_not_object", f"Skipping sensor with non-object modes: {sensor_name}", source)
            continue
        doc_id = catalog_id("sensor", str(sensor_name), project_ref)
        if doc_id in seen_ids:
            report.error("duplicate_sensor_id", f"Duplicate generated sensor id: {doc_id}", source)
            continue
        seen_ids.add(doc_id)
        normalized_modes = _normalize_modes(modes, report, source)
        bitdepth = sorted({
            int(mode["sensor_bitwidth"])
            for mode in normalized_modes.values()
            if isinstance(mode.get("sensor_bitwidth"), int)
        })
        compression = sorted({
            "SBWC_v4"
            for mode in normalized_modes.values()
            if str(mode.get("sensor_sbwc") or "").lower() in {"enable", "enabled", "true", "1"}
        })
        doc = {
            "id": doc_id,
            "schema_version": schema_version,
            "kind": "ip",
            "category": "sensor",
            "hierarchy": {"type": "simple"},
            "capabilities": {
                "operating_modes": [{"id": str(mode_id)} for mode_id in normalized_modes],
                "supported_features": {
                    "bitdepth": bitdepth,
                    "compression": compression,
                },
                "properties": {
                    "legacy_name": sensor_name,
                    "modes": normalized_modes,
                },
            },
            "compatible_soc": [],
        }
        docs.append(doc)
        report.increment("sensor_catalog")
    return docs


def _normalize_modes(
    modes: dict[str, Any],
    report: ImportReport,
    source: str,
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for mode_id, mode in modes.items():
        mode_source = f"{source}.{mode_id}"
        if not isinstance(mode, dict):
            report.warning("legacy_sensor_mode_not_object", f"Skipping non-object sensor mode: {mode_id}", mode_source)
            continue
        item = deepcopy(mode)
        v_valid_ms = _calc_v_valid_ms(item)
        if v_valid_ms is not None:
            item["v_valid_ms"] = v_valid_ms
        else:
            report.warning(
                "legacy_sensor_v_valid_not_calculated",
                f"Cannot calculate v_valid_ms for sensor mode: {mode_id}",
                mode_source,
            )
        normalized[str(mode_id)] = item
    return normalized


def _calc_v_valid_ms(mode: dict[str, Any]) -> float | None:
    size = mode.get("sensor_size")
    pclk = mode.get("sensor_pclk")
    line_length = mode.get("sensor_line_length_pck")
    if not isinstance(size, list) or len(size) < 2:
        return None
    height = size[1]
    if not all(isinstance(value, (int, float)) and value for value in (height, pclk, line_length)):
        return None
    return round(float(line_length) * 1000.0 / float(pclk) * float(height), 6)

