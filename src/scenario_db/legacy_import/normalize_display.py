from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scenario_db.legacy_import.ids import catalog_id
from scenario_db.legacy_import.read_legacy import read_yaml
from scenario_db.legacy_import.report import ImportReport


def load_legacy_display(path: Path, report: ImportReport) -> dict[str, dict[str, Any]]:
    raw = read_yaml(path)
    if not isinstance(raw, dict):
        report.error("legacy_display_not_object", "Display config must be a YAML object.", str(path))
        return {}
    displays = raw.get("displays", raw)
    if not isinstance(displays, dict):
        report.error("legacy_display_missing_displays", "Display config must contain a displays object or mapping.", str(path))
        return {}
    return displays


def convert_display_catalog(
    displays: dict[str, dict[str, Any]],
    *,
    project_ref: str,
    schema_version: str,
    report: ImportReport,
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for display_name, spec in displays.items():
        source = f"displays.{display_name}"
        if not isinstance(spec, dict):
            report.warning("legacy_display_spec_not_object", f"Skipping display with non-object spec: {display_name}", source)
            continue
        doc_id = catalog_id("display", str(display_name), project_ref)
        if doc_id in seen_ids:
            report.error("duplicate_display_id", f"Duplicate generated display id: {doc_id}", source)
            continue
        seen_ids.add(doc_id)
        refresh_rates = _refresh_rates(spec)
        bitdepth = spec.get("bitdepth") or spec.get("bitdepths") or []
        hdr_formats = spec.get("hdr_formats") or []
        properties = deepcopy(spec)
        properties["legacy_name"] = display_name
        doc = {
            "id": doc_id,
            "schema_version": schema_version,
            "kind": "ip",
            "category": "display",
            "hierarchy": {"type": "simple"},
            "capabilities": {
                "operating_modes": [{"id": f"{rate:g}hz"} for rate in refresh_rates],
                "supported_features": {
                    "bitdepth": bitdepth if isinstance(bitdepth, list) else [bitdepth],
                    "hdr_formats": hdr_formats if isinstance(hdr_formats, list) else [hdr_formats],
                },
                "properties": properties,
            },
            "compatible_soc": [],
        }
        docs.append(doc)
        report.increment("display_catalog")
    return docs


def _refresh_rates(spec: dict[str, Any]) -> list[float]:
    value = spec.get("refresh_rates")
    if value is None:
        value = spec.get("refresh_rate")
    if value is None:
        value = spec.get("fps")
    if isinstance(value, list):
        return sorted(float(item) for item in value if isinstance(item, (int, float)))
    if isinstance(value, (int, float)):
        return [float(value)]
    return []
