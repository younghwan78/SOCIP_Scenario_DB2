from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dashboard.components.query_api_client import (
    architecture_query_link,
    decode_query_params,
    get_query_facets,
    query_variants,
)
from dashboard.components.query_examples import EXAMPLE_CASES


ROOT = Path(__file__).resolve().parents[3]
PAGE = ROOT / "dashboard" / "pages" / "3_Architecture_Query.py"
HOME = ROOT / "dashboard" / "Home.py"


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict:
        return self._payload


def test_query_api_client_uses_expected_paths() -> None:
    calls = []

    def request(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/query/facets"):
            return _Response({"fields": [], "operators": []})
        return _Response({"items": [], "total": 0, "limit": 100, "offset": 0, "has_next": False, "errors": []})

    assert get_query_facets("http://api/api/v1", request_func=request)["fields"] == []
    assert query_variants("http://api/api/v1", {"where": []}, request_func=request)["items"] == []

    assert calls[0][0] == "GET"
    assert calls[0][1] == "http://api/api/v1/query/facets"
    assert calls[1][0] == "POST"
    assert calls[1][1] == "http://api/api/v1/query/variants"
    assert calls[1][2]["json"] == {"where": []}


def test_architecture_query_link_preserves_context() -> None:
    link = architecture_query_link({"soc_ref": "soc-demo", "scenario_id": "uc-camera", "empty": ""})

    assert link == "/Architecture_Query?soc_ref=soc-demo&scenario_id=uc-camera"


def test_architecture_query_link_can_round_trip_predicates_and_limit() -> None:
    link = architecture_query_link(
        {
            "soc_ref": "soc-exynos2600",
            "limit": 25,
            "where": [
                {"field": "buffer.compression", "op": "contains", "value": "SBWC"},
                {"field": "evidence.latest.kpi.total_power_mw", "op": "lte", "value": 100},
            ],
            "groups": [
                {
                    "join": "or",
                    "where": [
                        {"field": "topology.uses_ip", "op": "contains", "value": "npu"},
                        {"field": "topology.uses_ip", "op": "contains", "value": "gpu"},
                    ],
                }
            ],
            "aggregate": {
                "group_by": ["scenario.category"],
                "metrics": [{"field": "evidence.latest.kpi.total_power_mw", "ops": ["count", "avg"]}],
                "top_n": 10,
            },
        }
    )

    query = {key: value[0] for key, value in parse_qs(urlsplit(link).query).items()}

    assert query["soc_ref"] == "soc-exynos2600"
    assert query["limit"] == "25"
    assert decode_query_params(query)["where"] == [
        {"field": "buffer.compression", "op": "contains", "value": "SBWC"},
        {"field": "evidence.latest.kpi.total_power_mw", "op": "lte", "value": 100},
    ]
    assert decode_query_params(query)["groups"] == [
        {
            "join": "or",
            "where": [
                {"field": "topology.uses_ip", "op": "contains", "value": "npu"},
                {"field": "topology.uses_ip", "op": "contains", "value": "gpu"},
            ],
        }
    ]
    assert decode_query_params(query)["aggregate"] == {
        "group_by": ["scenario.category"],
        "metrics": [{"field": "evidence.latest.kpi.total_power_mw", "ops": ["count", "avg"]}],
        "top_n": 10,
    }


def test_decode_query_params_drops_invalid_limit() -> None:
    decoded = decode_query_params({"limit": "not-a-number", "where": "[]"})

    assert decoded == {"where": []}


def test_architecture_query_page_contract() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "Architecture Query" in source
    assert "자주 쓰는 Queries" in source
    assert "Apply Query" not in source
    assert "Apply & Run" not in source
    assert source.count('st.button("Run Query"') == 1
    assert "Presets update the query conditions automatically. Use Run Query to execute." in source
    assert "Available Values" in source
    assert [item["title"] for item in EXAMPLE_CASES] == [
        "SBWC 사용",
        "LLC 사용",
        "Camera power 기준 이상",
        "Camera NPU 사용",
        "Camera GPU 사용",
    ]
    assert "summarize_query_results" in source
    assert "zero_result_guidance" in source
    assert "active_query_rows" in source
    assert "Share current query" in source
    assert "Custom / shared query" in source
    assert "Loaded from URL or custom edits." in source
    assert "OR group (advanced)" in source
    assert "Rows in this section are OR conditions." in source
    assert "Aggregation View" in source
    assert "Enable aggregation" in source
    assert '"enabled": isinstance(aggregate, dict)' in source
    assert "query_aggregation_enabled" in source
    assert "aggregation_rows" in source
    assert "st.tabs" in source
    assert "list_soc_platforms" in source
    assert "list_projects" in source
    assert "list_scenarios" in source
    assert "list_variants" in source
    assert "All SoCs" in source
    assert "All Scenarios" in source
    assert "get_query_facets" in source
    assert "query_variants" in source
    assert "st.data_editor" in source
    assert "Edit the table below, then use Run Query." in source
    assert 'key_prefix="query_predicates_editor"' in source
    assert 'key_prefix="query_custom_predicates_editor"' in source
    assert 'key=f"query_example_preview_' not in source
    assert 'st.expander("Custom predicates (advanced)", expanded=False)' in source
    assert "Use this to add extra rows or change field/operator choices." in source
    assert 'st.expander("Payload (debug)", expanded=False)' in source
    assert "This is the Query API request preview. It does not execute by itself." in source
    assert 'st.subheader("Payload")' not in source
    assert "Open Pipeline Viewer" in source
    assert "topology.uses_ip" in source


def test_architecture_query_is_linked_from_dashboard_home() -> None:
    source = HOME.read_text(encoding="utf-8")

    assert PAGE.exists()
    assert (ROOT / "dashboard" / "pages" / "6_Import_Workbench.py").exists()
    assert '"Architecture Query"' in source
    assert '"Architecture Query": "ScenarioDB_ArchitectureQuery.png"' in source
    assert "Open Architecture Query" in source
    assert 'st.switch_page("pages/3_Architecture_Query.py")' in source
    assert "Filter variants by design axis, effective topology, buffer usage, and latest evidence KPI conditions." in source


def test_dashboard_home_orders_cards_by_read_to_exploration_flow() -> None:
    source = HOME.read_text(encoding="utf-8")
    body = source[source.index("col1, col2, col3, col4, col5, col6 = st.columns(6)") :]
    markers = [
        '"DB Explorer"',
        '"Pipeline Viewer"',
        '"Architecture Query"',
        '"Evidence Dashboard"',
        '"Exploration Workbench"',
        '"Import Workbench"',
    ]

    positions = [body.index(marker) for marker in markers]

    assert positions == sorted(positions)
    assert 'st.switch_page("pages/6_Import_Workbench.py")' in body
