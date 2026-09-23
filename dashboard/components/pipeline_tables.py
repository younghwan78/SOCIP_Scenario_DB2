"""DMA / buffer and transform tables derived from a loaded ViewResponse.

The tables expose architecture attributes that the graph only shows as
labels: DMA port pairs, buffer size/format/bitdepth/compression, and the
per-IP scale/crop/rotate/CSC operations. Everything is read from the view
projection the graph itself renders, so the table and the diagram agree.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_FORMAT_PLANE_FACTOR = {
    "Y": 1.0,
    "BAYER": 1.0,
    "RAW_BAYER": 1.0,
    "RAW_BAYER_16": 1.0,
    "YUV420": 1.5,
    "YUV420_10BIT": 1.5,
    "YUV420_SBWC": 1.5,
    "YUV420_SBWCL": 1.5,
    "YUV422": 2.0,
    "YUV422_10BIT": 2.0,
    "YUV444": 3.0,
    "RGB": 3.0,
    "RGBA8888": 4.0,
    "RGBA1010102": 4.0,
}

_PACKED_32BIT = {"RGBA8888", "RGBA1010102"}


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else dict(value)


def _elements(view: Any, attr: str) -> list[dict[str, Any]]:
    items = view.get(attr) if isinstance(view, dict) else getattr(view, attr, None)
    return [_as_dict(item).get("data") or {} for item in (items or [])]


def estimate_frame_bytes(memory: dict[str, Any]) -> int | None:
    """Uncompressed frame size estimate; declared size_bytes wins."""
    if memory.get("size_bytes"):
        return int(memory["size_bytes"])
    width, height = memory.get("width"), memory.get("height")
    fmt = str(memory.get("format") or "").upper()
    if not width or not height or fmt not in _FORMAT_PLANE_FACTOR:
        return None
    if fmt in _PACKED_32BIT:
        return int(width * height * 4)
    bitdepth = int(memory.get("bitdepth") or 8)
    bytes_per_sample = 1 if bitdepth <= 8 else 2
    return int(width * height * _FORMAT_PLANE_FACTOR[fmt] * bytes_per_sample)


def _size_text(memory: dict[str, Any]) -> str:
    width, height = memory.get("width"), memory.get("height")
    return f"{width}x{height}" if width and height else ""


def _ports(pairs: Iterable[Any]) -> tuple[str, str]:
    src, dst = [], []
    for pair in pairs or []:
        pair = _as_dict(pair)
        if pair.get("src") and pair["src"] not in src:
            src.append(str(pair["src"]))
        if pair.get("dst") and pair["dst"] not in dst:
            dst.append(str(pair["dst"]))
    return ", ".join(src), ", ".join(dst)


def dma_rows(view: Any) -> list[dict[str, Any]]:
    """One row per (buffer, producer, consumer) memory transfer."""
    nodes = {str(node.get("id")): node for node in _elements(view, "nodes")}

    def label(node_id: Any) -> str:
        node = nodes.get(str(node_id)) or {}
        # Producer/consumer can be pipeline ids that the L1 projection groups;
        # fall back to the upper-case HW-style name so rows stay readable.
        return str(node.get("label") or str(node_id or "").upper())

    def is_buffer(node_id: Any) -> bool:
        return (nodes.get(str(node_id)) or {}).get("type") == "buffer"

    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for edge in _elements(view, "edges"):
        if edge.get("flow_type") != "M2M":
            continue
        buffer_ref = str(edge.get("buffer_ref") or "")
        source, target = edge.get("source"), edge.get("target")
        producer = edge.get("producer") or (None if is_buffer(source) else source)
        consumer = edge.get("consumer") or (None if is_buffer(target) else target)
        if not buffer_ref:
            buffer_ref = str(source if is_buffer(source) else target if is_buffer(target) else "")
        memory = _as_dict(edge.get("memory"))
        if not memory:
            for candidate in (source, target):
                if is_buffer(candidate):
                    memory = _as_dict((nodes.get(str(candidate)) or {}).get("memory"))
                    break
        key = (buffer_ref, str(producer or ""), str(consumer or ""))
        src_ports, dst_ports = _ports(edge.get("port_pairs") or [])
        row = rows.setdefault(
            key,
            {
                "Buffer": buffer_ref.replace("buf_", "") or "-",
                "Producer": label(producer) if producer else "",
                "WDMA port": "",
                "Consumer": label(consumer) if consumer else "",
                "RDMA port": "",
                "Size": _size_text(memory),
                "Format": memory.get("format") or "",
                "Bit": memory.get("bitdepth"),
                "Compression": memory.get("compression") or "",
                "Frame MB (est.)": None,
                "Size source": "",
            },
        )
        if src_ports and not row["WDMA port"]:
            row["WDMA port"] = src_ports
        if dst_ports and not row["RDMA port"]:
            row["RDMA port"] = dst_ports
        if producer and not row["Producer"]:
            row["Producer"] = label(producer)
        if consumer and not row["Consumer"]:
            row["Consumer"] = label(consumer)
        for field, value in (("Size", _size_text(memory)), ("Format", memory.get("format")),
                             ("Bit", memory.get("bitdepth")), ("Compression", memory.get("compression"))):
            if value and not row[field]:
                row[field] = value
        frame_bytes = estimate_frame_bytes(memory)
        if frame_bytes and row["Frame MB (est.)"] is None:
            row["Frame MB (est.)"] = round(frame_bytes / (1024 * 1024), 2)
            row["Size source"] = "declared" if memory.get("size_bytes") else "W×H×format"
    ordered = sorted(rows.values(), key=lambda row: (row["Producer"], row["Buffer"], row["Consumer"]))
    for row in ordered:
        if not row["Size"]:
            row["Size source"] = "size 미정의"
    return ordered


def transform_rows(view: Any) -> list[dict[str, Any]]:
    """IP-level scale/crop/rotate/CSC operations active in this variant."""
    rows = []
    for node in _elements(view, "nodes"):
        if node.get("type") not in {"ip", "submodule", "sw"}:
            continue
        ops = _as_dict(node.get("active_operations"))
        caps = [str(item) for item in node.get("capability_badges") or []]
        if not ops and not caps:
            continue
        active = []
        if ops.get("scale"):
            ratio = ops.get("scale_ratio")
            active.append("scale" + (f" ×{ratio:.2f}" if isinstance(ratio, (int, float)) else ""))
        if ops.get("crop"):
            ratio = ops.get("crop_ratio")
            active.append("crop" + (f" {ratio:.2f}" if isinstance(ratio, (int, float)) else ""))
        if ops.get("rotate"):
            active.append(f"rotate {ops['rotate']}°")
        if ops.get("compose"):
            active.append("compose")
        if ops.get("colorspace_convert"):
            active.append(f"CSC {ops['colorspace_convert']}")
        if not active and not caps:
            continue
        rows.append(
            {
                "IP / node": str(node.get("label") or node.get("id")),
                "Active ops": ", ".join(active) or "bypass",
                "In": ops.get("scale_from") or "",
                "Out": ops.get("scale_to") or "",
                "Capability": ", ".join(caps),
                "DMA": node.get("dma_count"),
            }
        )
    return sorted(rows, key=lambda row: (row["Active ops"] == "bypass", row["IP / node"]))


def dma_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    known = [row["Frame MB (est.)"] for row in rows if isinstance(row.get("Frame MB (est.)"), (int, float))]
    return {
        "transfers": len(rows),
        "buffers": len({row["Buffer"] for row in rows}),
        "footprint_mb": round(sum(known), 1) if known else None,
        "compressed": sum(1 for row in rows if row.get("Compression") and row["Compression"] != "COMP_OFF"),
        "missing_size": sum(1 for row in rows if not row.get("Size")),
    }


def render_pipeline_tables(view: Any, *, key_prefix: str) -> None:
    import pandas as pd
    import streamlit as st

    rows = dma_rows(view)
    transforms = transform_rows(view)
    summary = dma_summary(rows)
    tab_dma, tab_tf = st.tabs([f"DMA / Buffer ({summary['transfers']})", f"Scale · Crop · Rotate ({len(transforms)})"])
    with tab_dma:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("M2M transfers", summary["transfers"])
        c2.metric("Buffers", summary["buffers"])
        c3.metric("Footprint (MB, 1 frame est.)", summary["footprint_mb"] if summary["footprint_mb"] is not None else "-")
        c4.metric("Compressed / size 미정의", f"{summary['compressed']} / {summary['missing_size']}")
        if rows:
            query = st.text_input("Filter (IP, buffer, port)", key=f"{key_prefix}_dma_filter", placeholder="예: MCSC, PYRAMID, WDMA")
            shown = [row for row in rows if not query or query.lower() in " ".join(str(v) for v in row.values()).lower()]
            st.dataframe(pd.DataFrame(shown), hide_index=True, use_container_width=True,
                         height=min(38 + 35 * len(shown), 520))
            st.caption("Frame MB는 압축 전 W×H×format 추정치(8bit 초과는 2byte/sample)입니다. 선언된 size_bytes가 있으면 그 값을 씁니다.")
        else:
            st.info("이 view level에는 M2M 전송이 없습니다. IP Pipeline (L1)에서 확인하세요.")
    with tab_tf:
        if transforms:
            st.dataframe(pd.DataFrame(transforms), hide_index=True, use_container_width=True,
                         height=min(38 + 35 * len(transforms), 480))
            st.caption("Active ops = 이 variant에서 켜진 동작, Capability = IP catalog가 선언한 지원 기능.")
        else:
            st.info("이 view level에 operation 정보가 있는 노드가 없습니다.")
