from __future__ import annotations

from typing import Any


def edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")


def edge_type(edge: dict[str, Any]) -> str:
    return str(edge.get("type") or "").upper()

