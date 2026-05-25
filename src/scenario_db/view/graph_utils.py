"""Common graph projection helpers shared by view modules."""
from __future__ import annotations

from typing import Any


def edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")


def safe_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value)).strip("-")


def parse_size(size: Any) -> tuple[int | None, int | None]:
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        try:
            return int(size[0]), int(size[1])
        except (TypeError, ValueError):
            return None, None
    if not isinstance(size, str) or "x" not in size:
        return None, None
    left, right = size.lower().split("x", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None, None


def resolution_to_size(resolution: Any) -> str | None:
    mapping = {
        "FHD": "1920x1080",
        "UHD": "3840x2160",
        "4K": "3840x2160",
        "8K": "7680x4320",
    }
    return mapping.get(str(resolution).upper())
