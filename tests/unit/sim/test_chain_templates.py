from __future__ import annotations

import pytest

from scenario_db.models.definition.usecase import Usecase
from scenario_db.sim.chain_templates import (
    compile_chain_template,
    compile_chain_template_sweep,
    normalize_chain_template,
)


def test_normalize_chain_template_supports_compact_buffers_and_links():
    template = {
        "kind": "scenario.chain_template",
        "id": "camera-recording-pyramid",
        "version": "1.0.0",
        "schema_version": 1,
        "project_ref": "proj-next",
        "source": {
            "ip_ref": "ip-sensor-hp2-projectA",
            "width": 4080,
            "height": 2296,
            "fps": 30,
            "format": "RAW_BAYER_16",
            "bitwidth": 12,
        },
        "buffer_columns": ["x", "y", "width", "height", "format", "bitwidth", "compression", "comp_ratio"],
        "buffers": {
            "L0": [0, 0, 2400, 1350, "YUV420", 10, "COMP_SBWC_LOSSLESS", 0.5],
            "L1": {"derive_from": "L0", "scale": 0.5},
            "L2": {"derive_from": "L1", "scale": 0.5},
            "OFF": [0, 0, 1920, 1080, "YUV420", 8, "COMP_OFF", 0.5],
        },
        "blocks": [
            {"id": "csis", "template": "csis_like", "ip_ref": "ip-csis-v8"},
            {"id": "pdp", "template": "pdp_like", "ip_ref": "ip-isp-v12"},
            {"id": "mlsc", "template": "mlsc_like", "ip_ref": "ip-isp-v12"},
            {"id": "mtnr", "template": "mtnr_like", "ip_ref": "ip-isp-v12"},
        ],
        "links": [
            "sensor_src:COUT -> csis:CIN | OTF",
            "csis:COUT -> pdp:CIN | OTF",
            "mlsc:WDMA0 -> L0 | M2M",
            "L0 -> mtnr:RDMA0 | M2M",
        ],
    }

    normalized = normalize_chain_template(template)

    assert normalized["id"] == "camera-recording-pyramid"
    assert normalized["version"] == "1.0.0"
    assert normalized["buffers"]["L0"] == {
        "roi": [0, 0, 2400, 1350],
        "width": 2400,
        "height": 1350,
        "format": "YUV420",
        "bitwidth": 10,
        "compression": "COMP_SBWC_LOSSLESS",
        "comp_ratio": 0.5,
    }
    assert normalized["buffers"]["L1"]["width"] == 1200
    assert normalized["buffers"]["L1"]["height"] == 675
    assert normalized["buffers"]["L2"]["width"] == 600
    assert normalized["buffers"]["L2"]["height"] == 338
    assert "comp_ratio" not in normalized["buffers"]["OFF"]
    assert normalized["links"][0] == {"from": "sensor_src:COUT", "to": "csis:CIN", "type": "OTF"}
    assert normalized["links"][2] == {"from": "mlsc:WDMA0", "to": "L0", "type": "M2M"}


def test_compile_chain_template_emits_versioned_valid_scenario():
    template = _template_payload()

    result = compile_chain_template(template)

    Usecase.model_validate(result.scenario)
    design = result.scenario["variants"][0]["design_conditions"]
    assert design["template_ref"] == "camera-recording-pyramid@1.0.0"
    assert design["template_schema_version"] == 1
    assert result.scenario["pipeline"]["buffers"]["L0"]["size"] == [0, 0, 2400, 1350]
    edges = result.scenario["pipeline"]["edges"]
    assert {"from": "sensor_src", "to": "csis", "type": "OTF"} in edges
    assert {"from": "mlsc", "to": "mtnr", "type": "M2M", "buffer": "L0"} in edges
    mlsc_outputs = result.scenario["variants"][0]["node_configs"]["mlsc"]["sim"]["outputs"]
    assert mlsc_outputs[0]["port"] == "WDMA0"
    assert mlsc_outputs[0]["width"] == 2400
    assert mlsc_outputs[0]["comp_ratio"] == 0.5
    mtnr_inputs = result.scenario["variants"][0]["node_configs"]["mtnr"]["sim"]["inputs"]
    assert mtnr_inputs[0]["port"] == "RDMA0"
    assert mtnr_inputs[0]["height"] == 1350
    assert result.import_bundle["import_report"]["generated"]["chain_template"] == 1


def test_chain_template_rejects_unknown_derive_buffer():
    template = _template_payload()
    template["buffers"]["L1"] = {"derive_from": "MISSING", "scale": 0.5}

    with pytest.raises(ValueError, match="derive_from references unknown buffer"):
        normalize_chain_template(template)


def test_compile_chain_template_sweep_expands_buffer_tuple_axis_values():
    sweep = {
        "kind": "scenario.chain_template_sweep",
        "id": "template-sbwc-sweep",
        "base_template": _template_payload(),
        "axes": [
            {
                "name": "l0",
                "path": "buffers.L0",
                "values": [
                    {
                        "label": "off",
                        "value": [0, 0, 2400, 1350, "YUV420", 10, "COMP_OFF", 1.0],
                    },
                    {
                        "label": "sbwc",
                        "value": [0, 0, 2400, 1350, "YUV420", 10, "COMP_SBWC_LOSSLESS", 0.5],
                    },
                ],
            }
        ],
    }

    result = compile_chain_template_sweep(sweep)

    assert len(result.import_bundle["documents"]) == 2
    assert [case["variant_id"] for case in result.cases] == ["template-fhd30-l0-off", "template-fhd30-l0-sbwc"]
    assert result.cases[1]["axis_values"]["l0"][6] == "COMP_SBWC_LOSSLESS"
    off_variant = result.import_bundle["documents"][0]["variants"][0]
    sbwc_variant = result.import_bundle["documents"][1]["variants"][0]
    assert off_variant["id"] == "template-fhd30-l0-off"
    assert sbwc_variant["id"] == "template-fhd30-l0-sbwc"
    off_output = off_variant["node_configs"]["mlsc"]["sim"]["outputs"][0]
    sbwc_output = sbwc_variant["node_configs"]["mlsc"]["sim"]["outputs"][0]
    assert off_output["compression"] == "COMP_OFF"
    assert "comp_ratio" not in off_output
    assert sbwc_output["compression"] == "COMP_SBWC_LOSSLESS"
    assert sbwc_output["comp_ratio"] == 0.5
    assert result.import_bundle["import_report"]["generated"]["chain_template_sweep_case"] == 2


def _template_payload() -> dict:
    return {
        "kind": "scenario.chain_template",
        "id": "camera-recording-pyramid",
        "version": "1.0.0",
        "schema_version": 1,
        "scenario_id": "uc-template-camera-recording",
        "variant_id": "template-fhd30",
        "project_ref": "proj-A-exynos2500",
        "soc_ref": "soc-exynos2500",
        "source": {
            "node_id": "sensor_src",
            "ip_ref": "ip-sensor-hp2-projectA",
            "width": 4080,
            "height": 2296,
            "fps": 30,
            "format": "RAW_BAYER_16",
            "bitwidth": 12,
        },
        "buffer_columns": ["x", "y", "width", "height", "format", "bitwidth", "compression", "comp_ratio"],
        "buffers": {
            "L0": [0, 0, 2400, 1350, "YUV420", 10, "COMP_SBWC_LOSSLESS", 0.5],
            "L1": {"derive_from": "L0", "scale": 0.5},
        },
        "blocks": [
            {"id": "csis", "template": "csis_like", "role": "csis", "ip_ref": "ip-csis-v8"},
            {"id": "pdp", "template": "pdp_like", "role": "pdp", "ip_ref": "ip-isp-v12"},
            {"id": "mlsc", "template": "mlsc_like", "role": "mlsc", "ip_ref": "ip-isp-v12"},
            {"id": "mtnr", "template": "mtnr_like", "role": "mtnr", "ip_ref": "ip-isp-v12"},
        ],
        "links": [
            "sensor_src:COUT -> csis:CIN | OTF",
            "csis:COUT -> pdp:CIN | OTF",
            "mlsc:WDMA0 -> L0 | M2M",
            "L0 -> mtnr:RDMA0 | M2M",
        ],
    }
