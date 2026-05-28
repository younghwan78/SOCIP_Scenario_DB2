from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExplorationContext:
    project_ref: str | None = None
    soc_ref: str | None = None


def exploration_context_from_payload(payload: dict[str, Any]) -> ExplorationContext:
    """Return the DB context declared by an exploration payload."""

    base = _base_payload(payload)
    project_ref = _clean_ref(base.get("project_ref"))
    soc_ref = _clean_ref(base.get("soc_ref"))
    if soc_ref is None and isinstance(base.get("mapping_profile"), dict):
        soc_ref = _clean_ref(base["mapping_profile"].get("target_soc_ref"))
    return ExplorationContext(project_ref=project_ref, soc_ref=soc_ref)


def clear_exploration_context_results(state: MutableMapping[str, Any]) -> None:
    state.pop("explore_compile_result", None)
    state.pop("explore_preview_result", None)


def _base_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("base_recipe"), dict):
        return payload["base_recipe"]
    if isinstance(payload.get("base_template"), dict):
        return payload["base_template"]
    return payload


def _clean_ref(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
