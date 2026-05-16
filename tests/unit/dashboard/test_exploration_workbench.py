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
from dashboard.components.exploration_candidate_compare import (
    candidate_ids,
    chart_candidate_rows,
    comparison_raw_rows,
    comparison_rows,
    metric_distribution_rows,
    metric_distribution_row_style,
    metric_bar_rows,
    pareto_case_ids,
    selected_candidate,
    tradeoff_plot_rows,
)
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
    assert rows[0]["baseline"] is True
    assert selected_candidate(preview, "case-b")["variant_id"] == "v-b"
    assert selected_candidate(preview, "missing")["variant_id"] == "v-a"

    rebased = comparison_rows(preview, baseline_case_id="case-b")
    assert rebased[0]["delta_total_power_mw"] == -1.877
    assert rebased[1]["baseline"] is True


def test_candidate_comparison_marks_pareto_and_filters():
    preview = {
        "cases": [{"case_id": "low-power"}, {"case_id": "balanced"}, {"case_id": "dominated"}],
        "comparison": [
            {"case_id": "low-power", "feasible": True, "warning_count": 0, "total_power_mw": 10.0, "total_bw_mbs": 140.0, "hw_time_max_ms": 5.0},
            {"case_id": "balanced", "feasible": True, "warning_count": 0, "total_power_mw": 12.0, "total_bw_mbs": 100.0, "hw_time_max_ms": 4.0},
            {"case_id": "dominated", "feasible": True, "warning_count": 1, "total_power_mw": 14.0, "total_bw_mbs": 160.0, "hw_time_max_ms": 6.0},
        ],
    }

    raw = comparison_raw_rows(preview)
    assert pareto_case_ids(raw) == {"low-power", "balanced"}
    assert [row["case_id"] for row in comparison_rows(preview, pareto_only=True)] == ["low-power", "balanced"]
    assert [row["case_id"] for row in comparison_rows(preview, hide_warning_cases=True)] == ["low-power", "balanced"]


def test_candidate_tradeoff_plot_rows_use_readable_status_and_condition_labels():
    preview = {
        "cases": [{"case_id": "fhd-off"}, {"case_id": "qhd-on"}, {"case_id": "bad"}],
        "comparison": [
            {
                "case_id": "fhd-off",
                "feasible": True,
                "warning_count": 0,
                "scale_width": 1920,
                "scale_height": 1080,
                "compression": "COMP_OFF",
                "total_power_mw": 10.0,
                "total_bw_mbs": 100.0,
            },
            {
                "case_id": "qhd-on",
                "feasible": True,
                "warning_count": 0,
                "scale_width": 2560,
                "scale_height": 1440,
                "compression": "COMP_SBWC_LOSSLESS",
                "total_power_mw": 11.0,
                "total_bw_mbs": 90.0,
            },
            {
                "case_id": "bad",
                "feasible": False,
                "warning_count": 0,
                "scale_width": 2560,
                "scale_height": 1440,
                "compression": "COMP_OFF",
                "total_power_mw": 20.0,
                "total_bw_mbs": 200.0,
            },
        ],
    }

    plot_rows = tradeoff_plot_rows(comparison_raw_rows(preview))
    by_case = {row["case_id"]: row for row in plot_rows}

    assert by_case["fhd-off"]["tradeoff_status"] == "Pareto candidate"
    assert by_case["qhd-on"]["tradeoff_status"] == "Pareto candidate"
    assert by_case["bad"]["tradeoff_status"] == "Infeasible"
    assert by_case["fhd-off"]["condition_label"] == "1920x1080 / COMP_OFF"
    assert by_case["qhd-on"]["compression_label"] == "COMP_SBWC_LOSSLESS"


def test_candidate_metric_bar_rows_show_diff_and_percent_from_baseline():
    rows = comparison_raw_rows(
        {
            "cases": [{"case_id": "base"}, {"case_id": "higher"}, {"case_id": "lower"}],
            "comparison": [
                {"case_id": "base", "total_power_mw": 100.0, "total_bw_mbs": 50.0, "scale_width": 1920, "scale_height": 1080},
                {"case_id": "higher", "total_power_mw": 125.0, "total_bw_mbs": 70.0, "scale_width": 2560, "scale_height": 1440},
                {"case_id": "lower", "total_power_mw": 80.0, "total_bw_mbs": 40.0, "scale_width": 1280, "scale_height": 720},
            ],
        },
        baseline_case_id="base",
    )

    bars = metric_bar_rows(rows, metric="total_power_mw", unit="mW")
    by_case = {row["case_id"]: row for row in bars}

    assert by_case["base"]["label"] == "100.0 mW | baseline"
    assert by_case["higher"]["label"] == "125.0 mW | +25.0 (+25.0%)"
    assert by_case["lower"]["label"] == "80.0 mW | -20.0 (-20.0%)"
    assert by_case["higher"]["short_label"] == "125.0 mW\n+25.0 / +25.0%"
    assert by_case["higher"]["color"] == "#C17A2F"
    assert by_case["lower"]["color"] == "#2F7D6D"


def test_candidate_metric_distribution_rows_capture_default_low_high_and_spread():
    rows = comparison_raw_rows(
        {
            "cases": [{"case_id": "default"}, {"case_id": "low"}, {"case_id": "high"}],
            "comparison": [
                {"case_id": "default", "total_power_mw": 100.0, "total_bw_mbs": 50.0, "hw_time_max_ms": 10.0},
                {"case_id": "low", "total_power_mw": 80.0, "total_bw_mbs": 40.0, "hw_time_max_ms": 8.0},
                {"case_id": "high", "total_power_mw": 120.0, "total_bw_mbs": 70.0, "hw_time_max_ms": 15.0},
            ],
        },
        baseline_case_id="default",
    )

    summary = metric_distribution_rows(rows)
    by_key = {(row["metric"], row["point"]): row for row in summary}

    assert by_key["Power", "min"]["case_id"] == "low"
    assert by_key["Power", "default"]["case_id"] == "default"
    assert by_key["Power", "max"]["case_id"] == "high"
    assert by_key["Power", "min"]["delta_vs_default"] == -20.0
    assert by_key["Power", "default"]["delta_vs_default"] == 0.0
    assert by_key["Power", "max"]["delta_pct_vs_default"] == 20.0
    assert by_key["Power", "spread"]["value"] == 40.0
    assert by_key["Power", "spread"]["delta_pct_vs_default"] == 40.0
    assert by_key["DMA BW", "min"]["delta_vs_default"] == -10.0
    assert by_key["HW Time", "max"]["delta_pct_vs_default"] == 50.0


def test_candidate_metric_distribution_rows_have_metric_group_styles():
    assert metric_distribution_row_style({"metric": "Power"})[0] != metric_distribution_row_style({"metric": "DMA BW"})[0]
    assert "background-color" in metric_distribution_row_style({"metric": "HW Time"})[0]


def test_candidate_chart_rows_use_axis_combination_labels_for_fps_format_sweep():
    rows = comparison_raw_rows(
        {
            "cases": [{"case_id": "fps30-16"}, {"case_id": "fps30-12"}, {"case_id": "fps60-16"}],
            "comparison": [
                {"case_id": "fps30-16", "fps": 30, "source_format": "RAW_BAYER_16", "total_power_mw": 10.0, "total_bw_mbs": 100.0, "hw_time_max_ms": 4.0},
                {"case_id": "fps30-12", "fps": 30, "source_format": "RAW_BAYER_12", "total_power_mw": 10.0, "total_bw_mbs": 75.0, "hw_time_max_ms": 4.0},
                {"case_id": "fps60-16", "fps": 60, "source_format": "RAW_BAYER_16", "total_power_mw": 20.0, "total_bw_mbs": 200.0, "hw_time_max_ms": 2.0},
            ],
        },
        baseline_case_id="fps30-16",
    )

    chart_rows = chart_candidate_rows(rows, sort_key="YAML order", limit=10)

    assert [row["condition_label"] for row in chart_rows] == ["30 (16b)", "30 (12b)", "60 (16b)"]
    assert chart_candidate_rows(rows, sort_key="DMA BW", limit=2)[0]["case_id"] == "fps30-12"


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
    assert "Baseline candidate" in (root / "dashboard" / "components" / "exploration_candidate_compare.py").read_text(encoding="utf-8")
    assert "Pareto only" in (root / "dashboard" / "components" / "exploration_candidate_compare.py").read_text(encoding="utf-8")
    assert "KPI Distribution by Sweep" in (root / "dashboard" / "components" / "exploration_candidate_compare.py").read_text(encoding="utf-8")
    assert "What this means" in page
    assert "Saved to DB" in page
    assert "Generated Documents" in page
    assert "Batch Exploration" in page
    assert "Single Design" in page
    assert "Run Simulation" in page
    assert "Upload Exploration YAML" in page
    assert "New Single Design" in page
    assert "New Batch Exploration" in page
    assert "Clear YAML editor" in page
    assert "SINGLE_DESIGN_TEMPLATE" in page
    assert "BATCH_EXPLORATION_TEMPLATE" in page
    assert "Topology" in page
    assert "Compact Graph" in page
    assert "Port Flow" in page
    assert "Buffer Usage" in page
    assert "_port_flow_text" in page
    assert "_topology_dot" in page
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


def test_exploration_workbench_summarizes_mapping_profile_from_yaml_payload():
    root = Path(__file__).resolve().parents[3]
    namespace: dict[str, Any] = {}
    source = (root / "dashboard" / "pages" / "5_Exploration_Workbench.py").read_text(encoding="utf-8")
    helper_source = source[source.index("def _mapping_profile_rows_from_payload"):source.index("def _parse_editor_yaml")]
    namespace.update({"Any": Any})
    exec(helper_source, namespace, namespace)
    payload = {
        "base_recipe": {
            "pipeline": [{"id": "byrp0", "role": "byrp_like"}, {"id": "gdc0", "role": "gdc_like"}],
            "mapping_profile": {
                "source_project_ref": "proj-a",
                "target_soc_ref": "soc-b",
                "role_mappings": {
                    "byrp_like": {
                        "source_role": "byrp",
                        "target_role": "byrp",
                        "source_ip_ref": "ip-isp-v12",
                        "target_ip_ref": "ip-isp-v12",
                        "confidence": "borrowed",
                        "ip_params": {"ppc": 4, "unit_power_mw_mp": 4.3, "vdd": "VDD_CAM", "dvfs_group": "CAM"},
                    }
                },
            },
        }
    }

    rows = namespace["_mapping_profile_rows_from_payload"](payload)
    missing = namespace["_unmapped_pipeline_roles"](payload)

    assert rows == [
        {
            "mapping_key": "byrp_like",
            "source_project_ref": "proj-a",
            "target_soc_ref": "soc-b",
            "source_role": "byrp",
            "target_role": "byrp",
            "source_ip_ref": "ip-isp-v12",
            "target_ip_ref": "ip-isp-v12",
            "confidence": "borrowed",
            "ppc": 4,
            "unit_power_mw_mp": 4.3,
            "vdd": "VDD_CAM",
            "dvfs_group": "CAM",
        }
    ]
    assert missing == ["gdc0"]


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
    dot = namespace["_topology_dot"](scenario)
    usage = namespace["_buffer_usage_rows"](scenario)

    assert "sensor_src.COUT" in text
    assert "byrp0.BYRP_CIN" in text
    assert "byrp0.BYRP_WDMA [byrp | ip-isp] -- vOTF write --> BUFFER: BYRP0_GDC0_BUF" in text
    assert "read --> gdc0.GDC_RDMA" in text
    assert '"sensor_src" -> "byrp0" [label="OTF"' in dot
    assert '"byrp0" -> "buffer::BYRP0_GDC0_BUF" [label="vOTF write"' in dot
    assert '"buffer::BYRP0_GDC0_BUF" -> "gdc0" [label="read"' in dot
    assert usage[0]["writer"].startswith("byrp0.BYRP_WDMA")
    assert usage[0]["reader"].startswith("gdc0.GDC_RDMA")


def test_theme_does_not_reposition_sidebar_number_input_buttons():
    root = Path(__file__).resolve().parents[3]
    theme = (root / "dashboard" / "components" / "ui_theme.py").read_text(encoding="utf-8")

    assert 'section[data-testid="stSidebar"] button:not(:has(p))' not in theme
    assert '"sdb-sidebar-toggle"' in theme
