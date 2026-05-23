from __future__ import annotations

from dashboard.components import evidence_result_view as view
from dashboard.components.evidence_dashboard_contract import RESULT_BREAKDOWN_TABS


def test_result_breakdown_selector_uses_pill_button_ui():
    source = view.__loader__.get_source(view.__name__)

    assert "st.pills(" in source
    assert "st.segmented_control(" not in source


def test_selected_breakdown_label_falls_back_to_first_contract_label():
    assert view.selected_breakdown_label("Timing Chart") == "Timing Chart"
    assert view.selected_breakdown_label("not-a-tab") == RESULT_BREAKDOWN_TABS[0]


def test_render_selected_result_breakdown_calls_only_timing_renderer(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(view, "render_external_device_info", lambda *args, **kwargs: calls.append("external"))
    monkeypatch.setattr(view, "render_ip_node_power", lambda *args, **kwargs: calls.append("power"))
    monkeypatch.setattr(view, "render_dma_bw", lambda *args, **kwargs: calls.append("dma"))
    monkeypatch.setattr(view, "render_timing_summary", lambda *args, **kwargs: calls.append("timing-summary"))
    monkeypatch.setattr(view, "render_timing_chart", lambda *args, **kwargs: calls.append("timing-chart"))
    monkeypatch.setattr(view, "render_timing_table", lambda *args, **kwargs: calls.append("timing-table"))
    monkeypatch.setattr(view, "render_timeline_table", lambda *args, **kwargs: calls.append("timeline-table"))
    monkeypatch.setattr(view, "render_simulation_report_tab", lambda *args, **kwargs: calls.append("report"))
    monkeypatch.setattr(view, "render_debug_trace", lambda *args, **kwargs: calls.append("debug"))

    view.render_selected_result_breakdown({"id": "sim-1"}, selected_label="Timing Chart", key_prefix="test")

    assert calls == ["timing-summary", "timing-chart"]


def test_render_selected_result_breakdown_calls_only_report_renderer(monkeypatch):
    calls: list[tuple[str, dict]] = []

    monkeypatch.setattr(view, "render_external_device_info", lambda *args, **kwargs: calls.append(("external", kwargs)))
    monkeypatch.setattr(view, "render_ip_node_power", lambda *args, **kwargs: calls.append(("power", kwargs)))
    monkeypatch.setattr(view, "render_dma_bw", lambda *args, **kwargs: calls.append(("dma", kwargs)))
    monkeypatch.setattr(view, "render_timing_summary", lambda *args, **kwargs: calls.append(("timing-summary", kwargs)))
    monkeypatch.setattr(view, "render_timing_chart", lambda *args, **kwargs: calls.append(("timing-chart", kwargs)))
    monkeypatch.setattr(view, "render_timing_table", lambda *args, **kwargs: calls.append(("timing-table", kwargs)))
    monkeypatch.setattr(view, "render_timeline_table", lambda *args, **kwargs: calls.append(("timeline-table", kwargs)))
    monkeypatch.setattr(view, "render_debug_trace", lambda *args, **kwargs: calls.append(("debug", kwargs)))
    monkeypatch.setattr(view.st, "json", lambda *args, **kwargs: calls.append(("raw", kwargs)))

    def _report(*args, **kwargs):
        calls.append(("report", kwargs))

    monkeypatch.setattr(view, "render_simulation_report_tab", _report)

    view.render_selected_result_breakdown(
        {"id": "sim-1"},
        selected_label="Report",
        key_prefix="test",
        api_base="http://api/api/v1",
        project_ref="projectA",
        soc_ref="socA",
    )

    assert [name for name, _ in calls] == ["report"]
    assert calls[0][1]["api_base"] == "http://api/api/v1"
    assert calls[0][1]["project_ref"] == "projectA"
    assert calls[0][1]["soc_ref"] == "socA"
