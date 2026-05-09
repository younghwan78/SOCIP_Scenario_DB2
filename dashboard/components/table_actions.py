from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

import streamlit as st
import streamlit.components.v1 as components


def render_copyable_dataframe(
    data: Any,
    *,
    key: str,
    copy_data: Any | None = None,
    copy_label: str = "Copy table",
    **dataframe_kwargs: Any,
) -> None:
    """Render a Streamlit dataframe with a browser clipboard copy action."""

    rows = tabular_rows(copy_data if copy_data is not None else data)
    if rows:
        render_copy_table_button(rows, key=key, label=copy_label)
    st.dataframe(data, **dataframe_kwargs)


def render_copy_table_button(
    rows: list[dict[str, Any]],
    *,
    key: str,
    label: str = "Copy table",
) -> None:
    tsv = rows_to_tsv(rows)
    if not tsv:
        return
    element_id = f"copy-table-{_safe_key(key)}"
    payload = json.dumps(tsv)
    components.html(
        f"""
<div style="display:flex;align-items:center;gap:8px;margin:0 0 4px 0;">
  <button id="{element_id}" style="
    border:1px solid #D1D5DB;border-radius:6px;background:#FFFFFF;color:#374151;
    padding:4px 10px;font-size:12px;line-height:18px;cursor:pointer;">
    {label}
  </button>
  <span id="{element_id}-status" style="font-size:12px;color:#6B7280;"></span>
</div>
<script>
const button = document.getElementById("{element_id}");
const status = document.getElementById("{element_id}-status");
const text = {payload};
button.addEventListener("click", async () => {{
  try {{
    if (navigator.clipboard && window.isSecureContext) {{
      await navigator.clipboard.writeText(text);
    }} else {{
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.focus();
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
    }}
    status.textContent = "Copied";
  }} catch (error) {{
    status.textContent = "Copy failed";
  }}
  window.setTimeout(() => {{ status.textContent = ""; }}, 1600);
}});
</script>
""",
        height=34,
    )


def tabular_rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "data") and hasattr(data.data, "to_dict"):
        data = data.data
    if hasattr(data, "to_dict"):
        try:
            records = data.to_dict(orient="records")
            if isinstance(records, list):
                return [dict(row) for row in records if isinstance(row, Mapping)]
        except TypeError:
            pass
    if isinstance(data, Mapping):
        return [dict(data)]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, Mapping):
                rows.append(dict(item))
            else:
                rows.append({"value": item})
        return rows
    return [{"value": data}]


def rows_to_tsv(rows: list[dict[str, Any]]) -> str:
    clean_rows = [row for row in rows if isinstance(row, Mapping)]
    if not clean_rows:
        return ""
    fieldnames: list[str] = []
    for row in clean_rows:
        for key in row:
            key_text = str(key)
            if key_text not in fieldnames:
                fieldnames.append(key_text)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore", delimiter="\t")
    writer.writeheader()
    for row in clean_rows:
        writer.writerow({key: _cell(row.get(key)) for key in fieldnames})
    return buffer.getvalue()


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return value


def _safe_key(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return "".join(ch if ch.isalnum() else "-" for ch in value)[:40] + "-" + digest
