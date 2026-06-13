from __future__ import annotations

from typing import Any

from dashboard.components.evidence_api_client import list_evidence
from dashboard.components import evidence_results_panel
from dashboard.components.measurement_result_view import (
    artifact_rows,
    cpu_cluster_rows,
    freq_residency_rows,
    kpi_mean,
    kpi_p95,
    kpi_summary_rows,
    measurement_list_rows,
    provenance_summary,
    sw_task_rows,
    vdd_power_rows,
)


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


def _evidence() -> dict[str, Any]:
    return {
        "id": "meas-x",
        "measured_at": "2026-06-10T15:20:00+09:00",
        "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "method": "measurement", "thermal": "room"},
        "provenance": {"device_id": "D1", "build_id": "B1", "collection_tool_versions": {"perfetto": "v47"}},
        "kpi": {
            "total_power_mw": {"mean": 3850.0, "p95": 4010.0, "n": 5, "ci_95": [3787.0, 3913.0]},
            "frame_latency_ms": 28.4,
        },
        "cpu_breakdown": [
            {
                "cluster": "BIG",
                "power_mw": {"mean": 410.0, "p95": 520.0, "n": 5},
                "avg_freq_mhz": 1920.0,
                "util_pct": 31.2,
                "freq_residency": [
                    {"freq_mhz": 2400.0, "ratio": 0.21, "time_ms": 100.0},
                    {"freq_mhz": 1920.0, "ratio": 0.48, "time_ms": 230.0},
                ],
            },
            {"cluster": "LIT", "power_mw": 185.0},
        ],
        "sw_task_timing": [
            {"task": "eis_warp", "cluster": "BIG", "mean_ms": 7.8, "p95_ms": 10.6, "max_ms": 15.1, "count_per_frame": 1.0, "samples": 26800},
        ],
        "vdd_power": {"VDD_CAM": {"mean_mw": 980.0, "p95_mw": 1080.0}},
        "artifacts": [
            {"type": "perfetto_trace", "storage": "fileshare", "path": "a/trace.pb", "sha256": "abc", "bytes": 123},
        ],
    }


def test_kpi_scalar_helpers():
    assert kpi_mean({"mean": 3850.0}) == 3850.0
    assert kpi_mean(28.4) == 28.4
    assert kpi_mean({"p95": 1.0}) is None
    assert kpi_p95({"p95": 4010.0}) == 4010.0
    assert kpi_p95(28.4) is None


def test_kpi_summary_rows():
    rows = {r["metric"]: r for r in kpi_summary_rows(_evidence())}
    tp = rows["total_power_mw"]
    assert tp["mean"] == 3850.0
    assert tp["p95"] == 4010.0
    assert tp["ci_95"] == [3787.0, 3913.0]
    assert tp["n"] == 5
    assert rows["frame_latency_ms"]["mean"] == 28.4
    assert rows["frame_latency_ms"]["p95"] is None


def test_cpu_cluster_rows_handles_stat_and_flat_power():
    rows = {r["cluster"]: r for r in cpu_cluster_rows(_evidence())}
    assert rows["BIG"]["power_mean_mw"] == 410.0
    assert rows["BIG"]["power_p95_mw"] == 520.0
    assert rows["BIG"]["avg_freq_mhz"] == 1920.0
    assert rows["LIT"]["power_mean_mw"] == 185.0
    assert rows["LIT"]["power_p95_mw"] is None


def test_freq_residency_rows_flattened_with_cluster():
    rows = freq_residency_rows(_evidence())
    assert {(r["cluster"], r["freq_mhz"]) for r in rows} == {("BIG", 2400.0), ("BIG", 1920.0)}
    assert all(r["ratio"] is not None for r in rows)


def test_sw_task_rows():
    rows = sw_task_rows(_evidence())
    assert rows[0]["task"] == "eis_warp"
    assert rows[0]["p95_ms"] == 10.6
    assert rows[0]["count_per_frame"] == 1.0


def test_vdd_power_rows():
    rows = vdd_power_rows(_evidence())
    assert rows[0] == {"rail": "VDD_CAM", "mean_mw": 980.0, "p95_mw": 1080.0}


def test_artifact_rows_includes_legacy_raw_artifacts():
    ev = _evidence()
    ev["provenance"]["raw_artifacts"] = [{"type": "power_csv", "path": "p.csv", "sha256": "z"}]
    rows = artifact_rows(ev)
    types = [r["type"] for r in rows]
    assert "perfetto_trace" in types
    assert "power_csv" in types


def test_provenance_summary():
    s = provenance_summary(_evidence())
    assert s["method"] == "measurement"
    assert s["device_id"] == "D1"
    assert s["tool_versions"] == {"perfetto": "v47"}


def test_measurement_list_rows():
    rows = measurement_list_rows([_evidence()])
    assert rows[0]["id"] == "meas-x"
    assert rows[0]["sw_version"] == "sw-vendor-v1.2.3"
    assert rows[0]["silicon_rev"] == "EVT1"
    assert rows[0]["total_power_mw"] == 3850.0


def test_list_evidence_passes_kind_filter():
    captured: dict[str, Any] = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _Response({"items": [{"id": "meas-x", "kind": "evidence.measurement"}], "total": 1})

    items = list_evidence(
        "http://api/v1",
        fake_request,
        kind="evidence.measurement",
        scenario_ref="uc-camera-recording",
        variant_ref="cam-rec-r1-uhd30-vdis",
    )
    assert items[0]["id"] == "meas-x"
    assert captured["url"].endswith("/evidence")
    assert captured["params"]["kind"] == "evidence.measurement"
    assert captured["params"]["scenario_ref"] == "uc-camera-recording"
    assert captured["params"]["sort_by"] == "measured_at"


def test_evidence_panel_loader_passes_project_filter(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_list_evidence(base_url, **kwargs):
        captured["base_url"] = base_url
        captured.update(kwargs)
        return [{"id": "meas-x"}]

    monkeypatch.setattr(evidence_results_panel, "list_evidence", fake_list_evidence)
    evidence_results_panel._load_evidence_list.clear()
    items, error = evidence_results_panel._load_evidence_list(
        "http://api/v1",
        "evidence.measurement",
        "uc-camera-recording",
        "cam-rec-r1-uhd30-vdis",
        "proj-A-exynos2500",
    )
    evidence_results_panel._load_evidence_list.clear()

    assert error is None
    assert items == [{"id": "meas-x"}]
    assert captured["project_ref"] == "proj-A-exynos2500"
