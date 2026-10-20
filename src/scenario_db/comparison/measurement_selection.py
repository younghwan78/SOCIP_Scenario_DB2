"""Representative capture policy shared by calibration and frozen review reports.

Callers supply measurements already scoped to one scenario/variant. This policy does
not choose previous-project references, whose source priorities are configurable.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

DATA_ORIGINS = ("synthetic", "physical_capture", "unknown")


def data_origin(provenance: dict[str, Any] | None) -> str:
    """Honor explicit origin; legacy silicon captures require method and device."""
    p = provenance or {}
    explicit = p.get("data_origin")
    if explicit in DATA_ORIGINS:
        return str(explicit)
    if str(p.get("collection_method") or "").startswith("synthetic") or p.get("device_id") == "SYNTHETIC":
        return "synthetic"
    if p.get("collection_method") and p.get("device_id"):
        return "physical_capture"
    return "unknown"


def is_synthetic(provenance: dict[str, Any] | None) -> bool:
    return data_origin(provenance) == "synthetic"


def is_physical(provenance: dict[str, Any] | None) -> bool:
    return data_origin(provenance) == "physical_capture"


class Capture(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def kpi(self) -> dict[str, Any] | None: ...

    @property
    def provenance(self) -> dict[str, Any] | None: ...

    @property
    def measured_at(self) -> datetime | None: ...


T = TypeVar("T", bound=Capture)


def _priority(capture: Capture) -> tuple[bool, int, datetime]:
    total = (capture.kpi or {}).get("total_power_mw")
    has_total = (total.get("mean") if isinstance(total, dict) else total) is not None
    origin = data_origin(capture.provenance)
    when = capture.measured_at or datetime.min.replace(tzinfo=UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return has_total, {"physical_capture": 2, "unknown": 1, "synthetic": 0}[origin], when


def representative_measurement(captures: Iterable[T]) -> T | None:
    """Choose total present > physical > unknown > synthetic > newest > lowest ID.

    Zero power is present, missing timestamps are oldest, and naive timestamps are
    UTC. Equal-priority captures use ascending ID regardless of database row order.
    """
    selected: T | None = None
    for capture in captures:
        if selected is None or _priority(capture) > _priority(selected):
            selected = capture
        elif _priority(capture) == _priority(selected) and capture.id < selected.id:
            selected = capture
    return selected
