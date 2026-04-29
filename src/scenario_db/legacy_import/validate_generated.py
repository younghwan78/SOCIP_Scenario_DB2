from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scenario_db.legacy_import.read_legacy import read_yaml
from scenario_db.legacy_import.report import ImportReport
from scenario_db.models.capability.hw import IpCatalog, IpSubmodule, SocPlatform
from scenario_db.models.capability.sw import SwComponent, SwProfile
from scenario_db.models.definition.project import Project
from scenario_db.models.definition.usecase import Usecase


_MODEL_BY_KIND = {
    "ip": IpCatalog,
    "submodule": IpSubmodule,
    "soc": SocPlatform,
    "sw_profile": SwProfile,
    "sw_component": SwComponent,
    "project": Project,
    "scenario.usecase": Usecase,
}


def validate_generated_yaml(paths: list[Path], report: ImportReport) -> None:
    """Validate generated canonical YAML files before DB load."""
    for path in sorted(paths):
        _validate_one(path, report)


def _validate_one(path: Path, report: ImportReport) -> None:
    try:
        raw = read_yaml(path)
    except Exception as exc:  # pragma: no cover - defensive for malformed files.
        report.error("generated_yaml_unreadable", f"Cannot read generated YAML: {exc}", str(path))
        return

    if not isinstance(raw, dict):
        report.error("generated_yaml_not_object", "Generated YAML root must be an object.", str(path))
        return

    kind = raw.get("kind")
    if not isinstance(kind, str):
        report.error("generated_yaml_missing_kind", "Generated YAML must contain a string kind.", str(path))
        return

    model = _MODEL_BY_KIND.get(kind)
    if model is None:
        report.warning("generated_yaml_unknown_kind", f"Skipping validation for unknown kind: {kind}", str(path))
        return

    try:
        model.model_validate(raw)
    except ValidationError as exc:
        report.error("generated_yaml_schema_invalid", _format_validation_error(exc), str(path))
        return

    report.increment("validated_yaml")
    report.increment(f"validated_yaml_{_counter_name(kind)}")


def _format_validation_error(exc: ValidationError) -> str:
    first_error: dict[str, Any] = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(item) for item in first_error.get("loc", ())) or "<root>"
    message = first_error.get("msg", str(exc))
    return f"Generated YAML schema validation failed at {loc}: {message}"


def _counter_name(kind: str) -> str:
    return kind.replace(".", "_")
