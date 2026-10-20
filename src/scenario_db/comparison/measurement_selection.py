"""Representative capture policy shared by calibration and frozen review reports.

Callers supply measurements already scoped to one scenario/variant. This policy does
not choose previous-project references, whose source priorities are configurable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
_ORIGIN_RANK = {"physical_capture": 2, "unknown": 1, "synthetic": 0}
_OLDEST = datetime.min.replace(tzinfo=UTC)


def has_total_value(capture: Capture) -> bool:
    """Report rule: a scalar or ``mean`` total that is not ``None`` (zero included)."""
    total = (capture.kpi or {}).get("total_power_mw")
    return (total.get("mean") if isinstance(total, dict) else total) is not None


def _priority(capture: Capture, has_total: Callable[[Capture], bool]) -> tuple[bool, int, datetime]:
    when = capture.measured_at or _OLDEST
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return bool(has_total(capture)), _ORIGIN_RANK[data_origin(capture.provenance)], when


def representative_measurement(captures: Iterable[T], *,
                               has_total: Callable[[Capture], bool] = has_total_value) -> T | None:
    """Choose total present > physical > unknown > synthetic > newest; ties keep input order.

    Missing timestamps are oldest and naive timestamps are UTC. Callers pass captures in
    database order ``measured_at DESC NULLS LAST, id`` so ties resolve with the database
    collation, exactly as before. ``has_total`` lets a caller keep its own comparability
    rule (calibration accepts numeric totals only). Each priority is computed once.
    """
    selected: T | None = None
    best: tuple[bool, int, datetime] | None = None
    for capture in captures:
        rank = _priority(capture, has_total)
        if best is None or rank > best:
            selected, best = capture, rank
    return selected
