from __future__ import annotations

from scenario_db.comparison.evidence import (
    compare_prediction_measurement,
    normalize_evidence_observations,
)


def _evidence(kind: str) -> dict:
    return {
        "id": "sim-x" if kind == "evidence.simulation" else "meas-x",
        "kind": kind,
        "project_ref": "proj-x",
        "scenario_ref": "uc-camera-x",
        "variant_ref": "fhd30",
        "execution_context": {
            "silicon_rev": "EVT1",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
            "thermal": "room",
            "power_state": "discharging",
        },
    }


def test_comparison_reports_matched_and_missing_metrics():
    prediction = {
        **_evidence("evidence.simulation"),
        "kpi": {"total_power_mw": 700.0, "total_bw_mbs": 6200.0},
    }
    measurement = {
        **_evidence("evidence.measurement"),
        "kpi": {
            "total_power_mw": {"mean": 680.0, "p95": 710.0, "n": 10},
            "frame_latency_ms": {"mean": 28.4, "p95": 32.1, "n": 5400},
        },
    }

    report = compare_prediction_measurement(prediction, measurement)
    rows = {row["metric_id"]: row for row in report["rows"]}

    assert rows["power.total"]["status"] == "MATCHED"
    assert rows["power.total"]["delta"] == 20.0
    assert rows["power.total"]["delta_pct"] == 2.941
    assert rows["bandwidth.total"]["status"] == "PREDICTION_ONLY"
    assert rows["latency.frame"]["status"] == "MEASUREMENT_ONLY"
    assert report["summary"]["status_counts"] == {
        "PREDICTION_ONLY": 1,
        "MEASUREMENT_ONLY": 1,
        "MATCHED": 1,
    }


def test_comparison_uses_catalog_statistic_for_scoped_observations():
    prediction = {
        **_evidence("evidence.simulation"),
        "metric_observations": [
            {
                "metric_id": "sw.runtime",
                "scope": {"kind": "task", "ref": "eis_warp"},
                "unit": "ms",
                "value": 9.0,
            }
        ],
    }
    measurement = {
        **_evidence("evidence.measurement"),
        "metric_observations": [
            {
                "metric_id": "sw.runtime",
                "scope": {"kind": "task", "ref": "eis_warp"},
                "unit": "ms",
                "stats": {"mean": 7.8, "p95": 10.6, "n": 5400},
            }
        ],
    }

    row = compare_prediction_measurement(prediction, measurement)["rows"][0]

    assert row["measurement_statistic"] == "p95"
    assert row["measurement"] == 10.6
    assert row["measurement_p95"] == 10.6
    assert row["delta"] == -1.6


def test_blocking_context_mismatch_suppresses_delta():
    prediction = {**_evidence("evidence.simulation"), "kpi": {"total_power_mw": 700.0}}
    measurement = {**_evidence("evidence.measurement"), "kpi": {"total_power_mw": 680.0}}
    measurement["execution_context"]["thermal"] = "hot"

    report = compare_prediction_measurement(prediction, measurement)
    row = report["rows"][0]

    assert report["context"]["compatible"] is False
    assert report["context"]["blocking_mismatches"] == ["thermal"]
    assert row["status"] == "CONTEXT_MISMATCH"
    assert row["delta"] is None
    assert row["delta_pct"] is None


def test_silicon_revision_mismatch_is_advisory():
    prediction = {**_evidence("evidence.simulation"), "kpi": {"total_power_mw": 700.0}}
    measurement = {**_evidence("evidence.measurement"), "kpi": {"total_power_mw": 680.0}}
    prediction["execution_context"]["silicon_rev"] = "PRE-SI"

    report = compare_prediction_measurement(prediction, measurement)

    assert report["context"]["compatible"] is True
    silicon = next(
        row for row in report["context"]["rows"] if row["field"] == "silicon_rev"
    )
    assert silicon["status"] == "MISMATCH"
    assert silicon["severity"] == "advisory"
    assert report["rows"][0]["status"] == "MATCHED"


def test_legacy_detail_fields_normalize_to_scoped_observations():
    evidence = {
        **_evidence("evidence.simulation"),
        "vdd_power": {"VDD_CAM": {"power_mw": 100.0}},
        "dma_breakdown": [
            {
                "node_id": "isp0",
                "port": "RDMA0",
                "direction": "read",
                "bw_mbs": 1420.0,
            }
        ],
        "timing_breakdown": [{"node_id": "isp0", "hw_time_ms": 3.2}],
        "sw_task_timing": [{"task": "eis_warp", "mean_ms": 7.8, "p95_ms": 10.6}],
    }

    observations = {
        (item["metric_id"], item["scope"]["kind"], item["scope"]["ref"]): item
        for item in normalize_evidence_observations(evidence)
    }

    assert observations[("power.rail", "rail", "VDD_CAM")]["stats"]["mean"] == 100.0
    assert observations[("bandwidth.read", "dma_port", "isp0:RDMA0")]["value"] == 1420.0
    assert observations[("latency.stage", "pipeline_stage", "isp0")]["value"] == 3.2
    assert observations[("sw.runtime", "task", "eis_warp")]["stats"]["p95"] == 10.6


def test_explicit_observation_overrides_legacy_detail():
    evidence = {
        **_evidence("evidence.measurement"),
        "vdd_power": {"VDD_CAM": {"power_mw": 100.0}},
        "metric_observations": [
            {
                "metric_id": "power.rail",
                "scope": {"kind": "rail", "ref": "VDD_CAM"},
                "unit": "mW",
                "value": 123.0,
            }
        ],
    }

    observations = normalize_evidence_observations(evidence)

    assert len(observations) == 1
    assert observations[0]["value"] == 123.0


def test_simulation_vdd_power_total_mw_produces_rail_observations():
    """Runner-shaped rails ({core_mw, bw_mw, total_mw}) must be visible to the
    comparison; before the fix every simulation rail was MEASUREMENT_ONLY."""
    evidence = {
        **_evidence("evidence.simulation"),
        "vdd_power": {"VDD_CAM": {"core_mw": 80.0, "bw_mw": 20.0, "total_mw": 100.0}},
    }

    observations = {
        (item["metric_id"], item["scope"]["kind"], item["scope"]["ref"]): item
        for item in normalize_evidence_observations(evidence)
    }

    assert observations[("power.rail", "rail", "VDD_CAM")]["stats"]["mean"] == 100.0


def test_power_domain_joins_simulation_rails_with_measured_buck_domains():
    """Sim rails are logical domain names; measured PMIC bucks declare their
    domain. power.domain is the declared join key between the two."""
    prediction = {
        **_evidence("evidence.simulation"),
        "vdd_power": {"MIF": {"core_mw": 0.0, "bw_mw": 40.0, "total_mw": 40.0}},
    }
    measurement = {
        **_evidence("evidence.measurement"),
        "vdd_power": {
            "B5S4_VDDMIF_AP_L": {"power_mw": 30.0, "std_mw": 3.0, "domain": "MIF"},
            "B5S5_VDDMIF_CP_L": {"power_mw": 12.0, "std_mw": 4.0, "domain": "MIF"},
        },
    }

    report = compare_prediction_measurement(prediction, measurement)
    rows = {
        (row["metric_id"], row["scope_kind"], row["scope_ref"]): row
        for row in report["rows"]
    }

    domain_row = rows[("power.domain", "power_domain", "MIF")]
    assert domain_row["status"] == "MATCHED"
    assert domain_row["prediction"] == 40.0
    assert domain_row["measurement"] == 42.0
    # Physical buck names still do not join at power.rail level.
    assert rows[("power.rail", "rail", "MIF")]["status"] == "PREDICTION_ONLY"
    assert rows[("power.rail", "rail", "B5S4_VDDMIF_AP_L")]["status"] == "MEASUREMENT_ONLY"


def test_measured_rails_without_domain_produce_no_domain_observations():
    evidence = {
        **_evidence("evidence.measurement"),
        "vdd_power": {"BUCK1": {"power_mw": 10.0}},
    }
    ids = {item["metric_id"] for item in normalize_evidence_observations(evidence)}
    assert "power.domain" not in ids


def test_cpu_breakdown_produces_cluster_observations():
    """Measured cpu_breakdown (the headline CPU digest) must be visible to
    the comparison as power.cluster rows."""
    measurement = {
        **_evidence("evidence.measurement"),
        "cpu_breakdown": [
            {"cluster": "BIG", "power_mw": {"mean": 26.9, "p95": 27.2, "n": 3}},
            {"cluster": "MID", "power_mw": 119.3},
            {"cluster": "LIT"},  # no power -> skipped
        ],
    }

    observations = {
        (item["metric_id"], item["scope"]["ref"]): item
        for item in normalize_evidence_observations(measurement)
    }

    assert observations[("power.cluster", "BIG")]["stats"]["mean"] == 26.9
    assert observations[("power.cluster", "MID")]["value"] == 119.3
    assert ("power.cluster", "LIT") not in observations


def test_power_breakdown_cpu_clusters_produce_prediction_observations():
    prediction = {
        **_evidence("evidence.simulation"),
        "power_breakdown": {
            "model": {"id": "v1-vfps", "version": "1.0"},
            "cpu": {"total_mw": 150.0, "by_cluster": {"BIG": 100.0, "MID": 50.0}},
        },
    }
    observations = {
        (item["metric_id"], item["scope"]["ref"]): item
        for item in normalize_evidence_observations(prediction)
    }
    assert observations[("power.cluster", "BIG")]["value"] == 100.0
    assert observations[("power.cluster", "MID")]["value"] == 50.0


def test_ip_breakdown_sums_instances_into_power_ip_observations():
    prediction = {
        **_evidence("evidence.simulation"),
        "ip_breakdown": [
            {"ip": "ip-isp-v12", "instance_index": 0, "power_mW": 40.0},
            {"ip": "ip-isp-v12", "instance_index": 1, "power_mW": 35.0},
            {"ip": "ip-mfc-v9", "instance_index": 0, "power_mW": 20.0},
        ],
    }
    observations = {
        (item["metric_id"], item["scope"]["ref"]): item
        for item in normalize_evidence_observations(prediction)
    }
    assert observations[("power.ip", "ip-isp-v12")]["value"] == 75.0
    assert observations[("power.ip", "ip-mfc-v9")]["value"] == 20.0


def test_cluster_rows_join_between_prediction_and_measurement():
    prediction = {
        **_evidence("evidence.simulation"),
        "power_breakdown": {"cpu": {"total_mw": 100.0, "by_cluster": {"BIG": 100.0}}},
    }
    measurement = {
        **_evidence("evidence.measurement"),
        "cpu_breakdown": [{"cluster": "BIG", "power_mw": {"mean": 110.0, "n": 3}}],
    }
    report = compare_prediction_measurement(prediction, measurement)
    rows = {
        (row["metric_id"], row["scope_ref"]): row for row in report["rows"]
    }
    cluster_row = rows[("power.cluster", "BIG")]
    assert cluster_row["status"] == "MATCHED"
    assert cluster_row["delta"] == -10.0
