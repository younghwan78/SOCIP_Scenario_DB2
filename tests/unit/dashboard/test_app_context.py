from dashboard.components.app_context import (
    adopt_query_context,
    context_bar_html,
    current_context,
    page_url,
    publish_query,
    set_context,
)


def test_adopt_query_sets_context_and_resets_page_widgets_once():
    state = {"viewer_variant_id": "old", "evidence_variant_id": "old"}
    query = {"scenario_id": "uc-camera-recording", "variant_id": "cam-rec-r1-uhd30-vdis"}

    assert adopt_query_context(query, state, page="evidence", reset_keys=("evidence_variant_id",))
    assert state["viewer_variant_id"] == "cam-rec-r1-uhd30-vdis"
    assert "evidence_variant_id" not in state

    # The same URL must not override a later in-page selection.
    state["viewer_variant_id"] = "user-picked"
    assert not adopt_query_context(query, state, page="evidence")
    assert state["viewer_variant_id"] == "user-picked"


def test_adopt_query_is_tracked_per_page():
    state = {}
    query = {"variant_id": "v1"}
    assert adopt_query_context(query, state, page="viewer")
    assert adopt_query_context(query, state, page="evidence")


def test_set_context_clears_downstream_on_upstream_change():
    state = {"viewer_scenario_id": "s1", "viewer_variant_id": "v1"}
    set_context(state, scenario_id="s2")
    assert current_context(state)["variant_id"] == ""
    set_context(state, scenario_id="s2", variant_id="v9")
    assert current_context(state)["variant_id"] == "v9"


def test_publish_query_mirrors_without_readoption():
    state = {}
    query_params = {"variant_id": "stale", "panel": "timing"}
    context = {"soc_id": "soc", "project_id": "", "scenario_id": "s", "variant_id": "v"}
    publish_query(query_params, context, page="viewer", state=state)
    assert query_params == {"variant_id": "v", "panel": "timing", "soc_id": "soc", "scenario_id": "s"}
    assert not adopt_query_context(query_params, state, page="viewer")


def test_page_links_carry_context_and_escape():
    context = {"soc_id": "soc", "project_id": "p", "scenario_id": "s<x>", "variant_id": ""}
    assert page_url("/Variant_Compare", context, variant_b="v2") == "/Variant_Compare?soc_id=soc&project_id=p&scenario_id=s%3Cx%3E&variant_b=v2"
    html = context_bar_html(context, active="Compare")
    assert "s&lt;x&gt;" in html and "<x>" not in html
    assert 'ctx-link ctx-link-active' in html
