"""Right inspector panel — scenario summary, risk cards, notes."""
from __future__ import annotations

import streamlit as st

from scenario_db.api.schemas.view import RiskCard, ViewResponse, ViewSummary
from dashboard.components.viewer_theme import SEVERITY_BG, SEVERITY_COLOR


def _metric_row(label: str, value: str) -> str:
    return f"""
    <div style="display:flex;justify-content:space-between;align-items:center;
         padding:4px 0;border-bottom:1px solid #F3F4F6;">
      <span style="color:#9CA3AF;font-size:11px;">{label}</span>
      <span style="color:#111827;font-size:12px;font-weight:500;">{value}</span>
    </div>"""


def _risk_card(risk: RiskCard) -> str:
    sev_color = SEVERITY_COLOR.get(risk.severity, "#6B7280")
    sev_bg = SEVERITY_BG.get(risk.severity, "#F3F4F6")
    return f"""
    <div style="background:white;border:1px solid #E5E7EB;border-radius:10px;
         padding:10px 12px;margin-bottom:8px;border-left:3px solid {sev_color};">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span style="background:{sev_color};color:white;font-size:10px;font-weight:700;
              border-radius:50%;width:18px;height:18px;display:inline-flex;
              align-items:center;justify-content:center;">{risk.id}</span>
        <span style="font-size:12px;font-weight:700;color:#111827;">{risk.title}</span>
      </div>
      <div style="font-size:11px;color:#6B7280;margin-bottom:4px;">
        Component: {risk.component}
      </div>
      <div style="font-size:11px;color:#374151;margin-bottom:6px;line-height:1.4;">
        {risk.description}
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <span style="background:{sev_bg};color:{sev_color};font-size:10px;font-weight:600;
              border-radius:4px;padding:2px 7px;">{risk.severity}</span>
        <span style="font-size:10px;color:#9CA3AF;">Impact: {risk.impact}</span>
      </div>
    </div>"""


def render_inspector(view: ViewResponse) -> None:
    """Render the right-side inspector panel using Streamlit markdown."""
    s = view.summary

    # ── Scenario summary ──────────────────────────────────────────────────
    st.markdown(
        '<p style="font-size:10px;font-weight:700;color:#9CA3AF;'
        'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;">'
        'SCENARIO</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p style="font-size:18px;font-weight:700;color:#111827;line-height:1.2;">'
        f'{s.name}</p>'
        f'<p style="font-size:12px;color:#6B7280;margin-bottom:10px;">{s.subtitle}</p>',
        unsafe_allow_html=True,
    )

    metrics_html = (
        _metric_row("Period",     f"{s.period_ms} ms")
        + _metric_row("Budget",     f"{s.budget_ms} ms")
        + _metric_row("Resolution", s.resolution)
        + _metric_row("Frame Rate", f"{s.fps} fps")
        + _metric_row("Variant",    s.variant_label)
    )
    st.markdown(
        f'<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;'
        f'padding:8px 10px;margin-bottom:14px;">{metrics_html}</div>',
        unsafe_allow_html=True,
    )

    # ── Risks ─────────────────────────────────────────────────────────────
    if view.risks:
        st.markdown(
            f'<p style="font-size:10px;font-weight:700;color:#9CA3AF;'
            f'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;">'
            f'RISKS ({len(view.risks)})</p>',
            unsafe_allow_html=True,
        )
        for risk in view.risks:
            st.markdown(_risk_card(risk), unsafe_allow_html=True)
        st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)

    # ── Notes ─────────────────────────────────────────────────────────────
    if s.notes:
        st.markdown(
            '<p style="font-size:10px;font-weight:700;color:#9CA3AF;'
            'letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px;">'
            'NOTES</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:8px;'
            f'padding:10px 12px;font-size:11px;color:#374151;line-height:1.5;">'
            f'{s.notes}',
            unsafe_allow_html=True,
        )
        if s.captured_at:
            st.markdown(
                f'<p style="font-size:10px;color:#9CA3AF;margin-top:6px;">'
                f'Captured: {s.captured_at}</p></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown("</div>", unsafe_allow_html=True)
