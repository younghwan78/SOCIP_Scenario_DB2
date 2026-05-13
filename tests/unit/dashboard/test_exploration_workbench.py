from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from dashboard.components.exploration_api_client import (
    compile_exploration_recipe,
    compile_exploration_sweep,
    get_exploration_example,
    list_exploration_examples,
    preview_exploration_sweep,
)
from dashboard.components.exploration_candidate_compare import candidate_ids, comparison_rows, selected_candidate
from dashboard.components.exploration_result_view import candidate_to_result


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def test_exploration_api_client_uses_expected_paths():
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(method: str, url: str, **kwargs: Any) -> _Response:
        calls.append((method, url, kwargs))
        if url.endswith("/examples"):
            return _Response({"items": [{"id": "recipe:demo"}], "total": 1})
        if url.endswith("/examples/recipe:demo"):
            return _Response({"id": "recipe:demo", "yaml_text": "id: demo", "payload": {"id": "demo"}})
        if url.endswith("/recipes/compile"):
            return _Response({"persisted": False, "scenario": {}, "import_bundle": {}, "warnings": [], "mapping_trace": []})
        if url.endswith("/sweeps/compile"):
            return _Response({"persisted": False, "import_bundle": {}, "cases": [], "warnings": []})
        if url.endswith("/sweeps/preview"):
            return _Response({"persisted": False, "cases": [], "comparison": [], "import_bundle": {}})
        raise AssertionError(url)

    base = "http://api/api/v1"
    assert list_exploration_examples(base, request_func=request)[0]["id"] == "recipe:demo"
    assert get_exploration_example(base, "recipe:demo", request_func=request)["payload"]["id"] == "demo"
    assert compile_exploration_recipe(base, source_yaml="id: demo", request_func=request)["persisted"] is False
    assert compile_exploration_sweep(base, source_yaml="id: sweep", request_func=request)["persisted"] is False
    assert preview_exploration_sweep(base, source_yaml="id: sweep", request_func=request)["persisted"] is False

    assert [call[1].replace(base, "") for call in calls] == [
        "/exploration/examples",
        "/exploration/examples/recipe:demo",
        "/exploration/recipes/compile",
        "/exploration/sweeps/compile",
        "/exploration/sweeps/preview",
    ]
    preview_payload = calls[-1][2]["json"]
    assert preview_payload["include_results"] is True
    assert preview_payload["config"]["include_timeline"] is True


def test_candidate_comparison_rows_and_selection():
    preview = {
        "cases": [
            {"case_id": "case-a", "variant_id": "v-a"},
            {"case_id": "case-b", "variant_id": "v-b"},
        ],
        "comparison": [
            {"case_id": "case-a", "variant_id": "v-a", "total_power_mw": 10.12345, "fps": 30},
            {"case_id": "case-b", "variant_id": "v-b", "total_power_mw": 12.0, "delta_total_power_mw": 1.87655, "fps": 60},
        ],
    }

    assert candidate_ids(preview) == ["case-a", "case-b"]
    rows = comparison_rows(preview)
    assert rows[0]["total_power_mw"] == 10.123
    assert rows[1]["delta_total_power_mw"] == 1.877
    assert selected_candidate(preview, "case-b")["variant_id"] == "v-b"
    assert selected_candidate(preview, "missing")["variant_id"] == "v-a"


def test_candidate_to_result_adapts_sim_run_result_for_shared_viewer():
    candidate = {
        "case_id": "case-a",
        "scenario_id": "uc-explore",
        "variant_id": "explore-fps-30",
        "axis_values": {"fps": 30},
        "kpi": {"total_power_mw": 10.0, "total_bw_mbs": 100.0},
        "warnings": ["borrowed mapping"],
        "feasible": True,
        "result": {
            "scenario_id": "uc-explore",
            "variant_id": "explore-fps-30",
            "resolved": {"isp0": {"node_id": "isp0", "total_power_mw": 10.0}},
            "dma_breakdown": [{"node_id": "isp0", "bw_mbs": 100.0}],
            "timeline_events": [{"task_id": "isp0", "start_ms": 0, "end_ms": 1}],
            "topology_order": ["isp0"],
            "calculation_trace": {"kpi": []},
        },
    }

    result = candidate_to_result(candidate)

    assert result["id"] == "case-a"
    assert result["scenario_ref"] == "uc-explore"
    assert result["variant_ref"] == "explore-fps-30"
    assert result["sweep_context"]["axis_values"] == {"fps": 30}
    assert result["kpi"]["total_power_mw"] == 10.0
    assert result["dvfs_breakdown"] == [{"node_id": "isp0", "total_power_mw": 10.0}]
    assert result["dma_breakdown"][0]["bw_mbs"] == 100.0
    assert result["warnings"] == ["borrowed mapping"]


def test_exploration_workbench_page_and_home_are_wired():
    root = Path(__file__).resolve().parents[3]
    page = (root / "dashboard" / "pages" / "5_Exploration_Workbench.py").read_text(encoding="utf-8")
    home = (root / "dashboard" / "Home.py").read_text(encoding="utf-8")

    assert "Exploration Workbench" in page
    assert "list_exploration_examples" in page
    assert "compile_exploration_recipe" in page
    assert "compile_exploration_sweep" in page
    assert "preview_exploration_sweep" in page
    assert "render_candidate_comparison" in page
    assert "render_candidate_detail" in page
    assert "Promote selected to Variant" in page
    assert "Save selected as Evidence" in page
    assert "What this means" in page
    assert "Saved to DB" in page
    assert "Generated Documents" in page
    assert "Batch Exploration" in page
    assert "Single Design" in page
    assert "Run Simulation" in page
    assert "Upload Exploration YAML" in page
    assert "Start blank YAML" in page
    assert "Topology" in page
    assert "Port Flow" in page
    assert "Buffer Usage" in page
    assert "_port_flow_text" in page
    assert "_render_api_error" in page
    assert "_api_error_detail" in page
    assert "pages/5_Exploration_Workbench.py" in home


def test_exploration_workbench_can_hide_input_panel_for_wide_results():
    root = Path(__file__).resolve().parents[3]
    page = (root / "dashboard" / "pages" / "5_Exploration_Workbench.py").read_text(encoding="utf-8")

    assert "explore_input_panel_visible" in page
    assert "Hide Exploration YAML" in page
    assert "Show Exploration YAML" in page
    assert "result_container = st.container()" in page
    assert "Exploration YAML input is hidden" in page


def test_exploration_workbench_formats_api_error_details():
    root = Path(__file__).resolve().parents[3]
    namespace: dict[str, Any] = {}
    source = (root / "dashboard" / "pages" / "5_Exploration_Workbench.py").read_text(encoding="utf-8")
    helper_source = source[source.index("def _api_error_detail"):source.index("def _input_panel_visible")]
    namespace.update(
        {
            "json": __import__("json"),
            "yaml": yaml,
            "Any": Any,
            "Node": Node,
            "MappingNode": MappingNode,
            "ScalarNode": ScalarNode,
            "SequenceNode": SequenceNode,
        }
    )
    exec(helper_source, namespace, namespace)

    lines = namespace["_api_error_detail"](
        '{"detail":[{"loc":["body","source_yaml"],"msg":"YAML payload must be a mapping"},{"loc":["pipeline"],"msg":"Field required"}]}',
        source_yaml="id: demo\nsource:\n  width: 1920\n",
    )

    assert lines[0].startswith("Line 1: YAML payload must be a mapping")
    assert lines[1].startswith("Line 1: pipeline: Field required")
    assert "Hint: Single Design YAML needs a pipeline list." in lines[1]
    assert "> 1 | id: demo" in lines[1]


def test_exploration_workbench_detects_yaml_type_from_content():
    root = Path(__file__).resolve().parents[3]
    namespace: dict[str, Any] = {}
    source = (root / "dashboard" / "pages" / "5_Exploration_Workbench.py").read_text(encoding="utf-8")
    helper_source = source[source.index("def _parse_yaml_mapping"):source.index("def _input_panel_visible")]
    namespace.update(
        {
            "json": __import__("json"),
            "yaml": yaml,
            "Any": Any,
            "Node": Node,
            "MappingNode": MappingNode,
            "ScalarNode": ScalarNode,
            "SequenceNode": SequenceNode,
        }
    )
    exec(helper_source, namespace, namespace)

    assert namespace["_detect_yaml_kind"]("id: single\nsource: {}\npipeline: []\n") == "single"
    assert namespace["_detect_yaml_kind"]("id: batch\nbase_recipe:\n  id: single\n") == "batch"
    assert namespace["_detect_yaml_kind"]("not: exploration\n") == "unknown"


def test_exploration_workbench_builds_continuous_port_flow():
    root = Path(__file__).resolve().parents[3]
    namespace: dict[str, Any] = {}
    source = (root / "dashboard" / "pages" / "5_Exploration_Workbench.py").read_text(encoding="utf-8")
    helper_source = source[source.index("def _topology_rows"):source.index("def _parse_editor_yaml")]
    namespace.update({"Any": Any})
    exec(helper_source, namespace, namespace)
    scenario = {
        "pipeline": {
            "nodes": [
                {"id": "sensor_src", "role": "sensor", "ip_ref": "ip-sensor"},
                {"id": "byrp0", "role": "byrp", "ip_ref": "ip-isp"},
                {"id": "gdc0", "role": "gdc", "ip_ref": "ip-gdc"},
            ],
            "edges": [
                {"from": "sensor_src", "to": "byrp0", "type": "OTF"},
                {"from": "byrp0", "to": "gdc0", "type": "vOTF", "buffer": "BYRP0_GDC0_BUF"},
            ],
            "buffers": {
                "BYRP0_GDC0_BUF": {
                    "size": [0, 0, 1920, 1080],
                    "format": "YUV420",
                    "compression": "COMP_OFF",
                }
            },
        },
        "variants": [
            {
                "node_configs": {
                    "byrp0": {
                        "sim": {
                            "inputs": [{"port": "BYRP_CIN", "port_type": "OTF_IN"}],
                            "outputs": [{"port": "BYRP_WDMA", "port_type": "DMA_WRITE"}],
                        }
                    },
                    "gdc0": {
                        "sim": {
                            "inputs": [{"port": "GDC_RDMA", "port_type": "DMA_READ"}],
                            "outputs": [{"port": "GDC_WDMA", "port_type": "DMA_WRITE"}],
                        }
                    },
                }
            }
        ],
    }

    text = namespace["_port_flow_text"](scenario)
    usage = namespace["_buffer_usage_rows"](scenario)

    assert "sensor_src.COUT" in text
    assert "byrp0.BYRP_CIN" in text
    assert "byrp0.BYRP_WDMA [byrp | ip-isp] -- vOTF write --> BUFFER: BYRP0_GDC0_BUF" in text
    assert "read --> gdc0.GDC_RDMA" in text
    assert usage[0]["writer"].startswith("byrp0.BYRP_WDMA")
    assert usage[0]["reader"].startswith("gdc0.GDC_RDMA")


def test_theme_does_not_reposition_sidebar_number_input_buttons():
    root = Path(__file__).resolve().parents[3]
    theme = (root / "dashboard" / "components" / "ui_theme.py").read_text(encoding="utf-8")

    assert 'section[data-testid="stSidebar"] button:not(:has(p))' not in theme
    assert '"sdb-sidebar-toggle"' in theme
