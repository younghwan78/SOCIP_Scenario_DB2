"""Shared SoC/project/scenario/variant selection across dashboard pages.

The ``viewer_*`` session keys are the single source of truth. URL query
parameters are adopted once per page when they change (deep links), and pages
publish their current selection back to the URL so links stay shareable.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from html import escape
from typing import Any
from urllib.parse import urlencode

CONTEXT_FIELDS: dict[str, str] = {
    "soc_id": "viewer_soc_id",
    "project_id": "viewer_project_id",
    "scenario_id": "viewer_scenario_id",
    "variant_id": "viewer_variant_id",
}

# Downstream fields are invalid once an upstream field changes.
_ORDER = tuple(CONTEXT_FIELDS)

PAGE_LINKS: tuple[tuple[str, str], ...] = (
    ("DB Explorer", "/DB_Explorer"),
    ("Pipeline", "/Pipeline_Viewer"),
    ("Compare", "/Variant_Compare"),
    ("Evidence", "/Evidence_Dashboard"),
)


def _query_value(query: Mapping[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")


def query_signature(query: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(_query_value(query, key) for key in _ORDER)


def adopt_query_context(
    query: Mapping[str, Any],
    state: MutableMapping[str, Any],
    *,
    page: str,
    reset_keys: Iterable[str] = (),
) -> bool:
    """Copy URL context into session state when the URL context changed.

    Returns True when the query was adopted. ``reset_keys`` are page widget
    keys that cache a previous selection and must be dropped so the new
    context is not overridden by stale widget state.
    """
    signature = query_signature(query)
    if not any(signature):
        return False
    marker = f"_ctx_query_sig::{page}"
    if state.get(marker) == signature:
        return False
    state[marker] = signature
    for field, value in zip(_ORDER, signature):
        if value:
            state[CONTEXT_FIELDS[field]] = value
    for key in reset_keys:
        state.pop(key, None)
    return True


def current_context(state: Mapping[str, Any]) -> dict[str, str]:
    return {field: str(state.get(key) or "") for field, key in CONTEXT_FIELDS.items()}


def set_context(state: MutableMapping[str, Any], **values: str | None) -> dict[str, str]:
    """Update context fields; clear downstream fields when an upstream one changes."""
    for index, field in enumerate(_ORDER):
        if field not in values or values[field] is None:
            continue
        new_value = str(values[field] or "")
        key = CONTEXT_FIELDS[field]
        if str(state.get(key) or "") != new_value:
            state[key] = new_value
            for downstream in _ORDER[index + 1:]:
                if downstream not in values:
                    state.pop(CONTEXT_FIELDS[downstream], None)
    return current_context(state)


def context_query(context: Mapping[str, str], **extra: str | None) -> dict[str, str]:
    merged = {key: value for key, value in context.items() if value}
    merged.update({key: str(value) for key, value in extra.items() if value})
    return merged


def page_url(path: str, context: Mapping[str, str], **extra: str | None) -> str:
    query = context_query(context, **extra)
    return f"{path}?{urlencode(query)}" if query else path


def publish_query(query_params: MutableMapping[str, Any], context: Mapping[str, str], *, page: str,
                  state: MutableMapping[str, Any]) -> None:
    """Mirror the current context into the URL without triggering re-adoption."""
    wanted = context_query(context)
    current = {key: _query_value(query_params, key) for key in _ORDER if _query_value(query_params, key)}
    if current == wanted:
        return
    for key in _ORDER:
        if key in wanted:
            query_params[key] = wanted[key]
        elif key in query_params:
            del query_params[key]
    state[f"_ctx_query_sig::{page}"] = query_signature(wanted)


def context_bar_html(context: Mapping[str, str], *, active: str = "", labels: Mapping[str, str] | None = None) -> str:
    labels = labels or {}
    crumbs = []
    for field in _ORDER:
        value = context.get(field) or ""
        if not value:
            continue
        text = labels.get(field) or value
        crumbs.append(f'<span class="ctx-crumb" title="{escape(field)}">{escape(text)}</span>')
    trail = '<span class="ctx-sep">›</span>'.join(crumbs) or '<span class="ctx-empty">선택된 context 없음</span>'
    links = []
    for label, path in PAGE_LINKS:
        cls = "ctx-link ctx-link-active" if label == active else "ctx-link"
        links.append(f'<a class="{cls}" href="{escape(page_url(path, context), quote=True)}" target="_self">{escape(label)}</a>')
    return (
        '<div class="ctx-bar"><div class="ctx-trail">' + trail + '</div>'
        '<div class="ctx-links">' + "".join(links) + "</div></div>"
    )


CONTEXT_BAR_CSS = """
<style>
  .ctx-bar { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;
    border:1px solid #E5E7EB; border-radius:10px; background:#FFFFFF; padding:7px 12px; margin:0 0 10px 0; }
  .ctx-trail { display:flex; align-items:center; gap:6px; flex-wrap:wrap; font-size:13px; }
  .ctx-crumb { font-weight:700; color:#111827; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; }
  .ctx-sep { color:#9CA3AF; }
  .ctx-empty { color:#6B7280; }
  .ctx-links { display:flex; gap:6px; }
  .ctx-link { font-size:12px; font-weight:700; color:#374151 !important; text-decoration:none !important;
    border:1px solid #E5E7EB; border-radius:7px; padding:3px 9px; background:#F9FAFB; }
  .ctx-link:hover { background:#F3F4F6; }
  .ctx-link-active { background:#111827; color:#FFFFFF !important; border-color:#111827; }
</style>
"""


def render_context_bar(state: Mapping[str, Any], *, active: str = "", labels: Mapping[str, str] | None = None) -> None:
    import streamlit as st

    st.markdown(CONTEXT_BAR_CSS + context_bar_html(current_context(state), active=active, labels=labels),
                unsafe_allow_html=True)
