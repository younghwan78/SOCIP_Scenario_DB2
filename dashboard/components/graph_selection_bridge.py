"""Bridge that carries diagram click selections into Streamlit.

The ELK viewer renders through one-way ``components.html`` iframes; on click
they post ``{type: 'sdb-graph-select', id, kind, label, seq}`` to the top
window. The tiny bidirectional component in ``graph_bridge/`` listens there
(same origin) and forwards the payload as its component value.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

COMPONENT_PATH = Path(__file__).resolve().parent / "graph_bridge"

_component_func = None


def bridge_available() -> bool:
    return (COMPONENT_PATH / "index.html").is_file()


def _get_component():
    global _component_func
    if _component_func is None:
        _component_func = components.declare_component("sdb_graph_selection_bridge", path=str(COMPONENT_PATH))
    return _component_func


def read_graph_selection(*, key: str) -> dict[str, Any] | None:
    """Render the invisible bridge and return the latest diagram selection.

    Returns ``{"id", "kind", "label", "seq"}`` or ``None``.
    """

    if not bridge_available():
        return None
    raw = _get_component()(key=key, default=None)
    return normalize_graph_selection(raw)


def normalize_graph_selection(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    selection_id = str(raw.get("id") or "").strip()
    if not selection_id:
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    return {
        "id": selection_id,
        "kind": kind if kind in {"node", "edge"} else "node",
        "label": str(raw.get("label") or selection_id),
        "seq": int(raw.get("seq") or 0),
    }
