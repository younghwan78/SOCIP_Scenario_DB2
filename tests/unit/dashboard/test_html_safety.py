from __future__ import annotations

from dashboard.components import evidence_actions, table_actions


def test_viewer_link_escapes_href_and_label(monkeypatch):
    rendered: dict[str, object] = {}

    monkeypatch.setattr(
        evidence_actions,
        "build_pipeline_viewer_url",
        lambda **kwargs: '"/><script>alert(1)</script>',
    )
    monkeypatch.setattr(
        evidence_actions.st,
        "markdown",
        lambda value, **kwargs: rendered.update(
            html=value,
            unsafe=kwargs.get("unsafe_allow_html"),
        ),
    )

    evidence_actions.render_viewer_tab_link(
        api_base="http://api",
        scenario_id="scenario",
        variant_id="variant",
        soc_id=None,
        project_id=None,
        label="<img src=x onerror=alert(1)>",
    )

    html = str(rendered["html"])
    assert "<script>" not in html
    assert "<img" not in html
    assert "&quot;/&gt;&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert rendered["unsafe"] is True


def test_copy_button_escapes_label(monkeypatch):
    rendered: dict[str, str] = {}
    monkeypatch.setattr(
        table_actions.components,
        "html",
        lambda value, **kwargs: rendered.update(html=value),
    )

    table_actions.render_copy_table_button(
        [{"value": "safe"}],
        key="copy",
        label="<svg onload=alert(1)>",
    )

    assert "<svg" not in rendered["html"]
    assert "&lt;svg onload=alert(1)&gt;" in rendered["html"]
