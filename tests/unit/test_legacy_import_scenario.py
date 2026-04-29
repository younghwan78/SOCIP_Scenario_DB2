from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import yaml

from scenario_db.legacy_import.cli import main
from scenario_db.legacy_import.normalize_scenario import convert_scenario_group_usecase, convert_scenario_usecase
from scenario_db.legacy_import.report import ImportReport
from scenario_db.models.definition.project import Project
from scenario_db.models.definition.usecase import Usecase


def _legacy_scenario() -> dict:
    return {
        "name": "FHD30_Recording",
        "sensor": {"hw": "HP2", "mode": "mode1"},
        "tasks": [
            {"id": "t_sensor", "hw": "HP2", "description": "FHD30 LN2"},
        ],
        "ip_blocks": [
            {
                "ip_settings": {
                    "hw": "CSIS",
                    "mode": "Normal",
                    "inputs": [{"port": "NFI_DEC", "size": [0, 0, 4000, 2252]}],
                    "outputs": [
                        {"port": "COUTFIFO", "size": [0, 0, 4000, 2252]},
                        {
                            "port": "CSIS_WDMA",
                            "size": [0, 0, 4000, 2252],
                            "format": "BAYER_PACKED",
                            "bitwidth": 12,
                            "comp": "enable",
                        },
                    ],
                },
                "tasks": [{"id": "t_csis", "hw": "CSIS", "description": "CSIS"}],
                "edges": [{"src": "t_sensor", "dst": "t_csis", "dst_port": "NFI_DEC", "type": "OTF"}],
            },
            {
                "ip_settings": {
                    "hw": "BYRP",
                    "mode": "Normal",
                    "inputs": [
                        {
                            "port": "COMP_RD0_RDMA",
                            "size": [0, 0, 4000, 2252],
                            "format": "BAYER_PACKED",
                            "bitwidth": 12,
                            "comp": "enable",
                        }
                    ],
                    "outputs": [{"port": "COUTFIFO", "size": [0, 0, 4000, 2252]}],
                },
                "tasks": [{"id": "t_byrp", "hw": "BYRP", "description": "BYRP"}],
                "edges": [
                    {
                        "src": "t_csis",
                        "src_port": "CSIS_WDMA",
                        "dst": "t_byrp",
                        "dst_port": "COMP_RD0_RDMA",
                        "type": "M2M",
                    }
                ],
            },
            {
                "sw_tasks": [
                    {
                        "id": "t_postIRTA",
                        "name": "postIRTA",
                        "group": "IRTA",
                        "processor": "CPU_MID_Clustor",
                        "duration_ms": 4.0,
                    }
                ],
                "edges": [{"src": "t_byrp", "dst": "t_postIRTA", "type": "M2M"}],
            },
            {
                "ip_settings": {
                    "hw": "MFC",
                    "mode": "Normal",
                    "inputs": [
                        {"port": "MFC_RDMA", "size": [0, 0, 1920, 1080], "format": "YUV420", "bitwidth": 10}
                    ],
                    "outputs": [{"port": "MFC_WDMA", "size": [0, 0, 40000, 1000], "format": "STAT", "bitwidth": 10}],
                },
                "tasks": [{"id": "t_mfc", "hw": "MFC", "description": "MFC"}],
                "edges": [{"src": "t_postIRTA", "dst": "t_mfc", "dst_port": "MFC_RDMA", "type": "M2M"}],
            },
        ],
    }


def _legacy_preview_scenario() -> dict:
    scenario = _legacy_scenario()
    scenario["name"] = "FHD30_Preview"
    scenario["ip_blocks"] = scenario["ip_blocks"][:2] + [
        {
            "ip_settings": {
                "hw": "DPU",
                "mode": "Normal",
                "inputs": [
                    {"port": "DPU_RDMA", "size": [0, 0, 1920, 1080], "format": "YUV420", "bitwidth": 10}
                ],
                "outputs": [{"port": "COUTFIFO", "size": [0, 0, 1920, 1080]}],
            },
            "tasks": [{"id": "t_dpu", "hw": "DPU", "description": "DPU"}],
            "edges": [{"src": "t_byrp", "dst": "t_dpu", "dst_port": "DPU_RDMA", "type": "M2M"}],
        }
    ]
    return scenario


def test_convert_scenario_usecase_generates_pipeline_variant_and_overlays():
    report = ImportReport()
    doc = convert_scenario_usecase(
        _legacy_scenario(),
        project_ref="proj-projectA",
        schema_version="2.2",
        report=report,
    )

    assert doc is not None
    assert report.ok
    assert report.generated["scenario_usecase"] == 1
    assert doc["id"] == "uc-fhd30-recording"
    assert [node["id"] for node in doc["pipeline"]["nodes"]] == ["t_sensor", "t_csis", "t_byrp", "t_postIRTA", "t_mfc"]
    assert len(doc["pipeline"]["edges"]) == 4
    assert len(doc["pipeline"]["task_graph"]["nodes"]) == 5
    assert len(doc["pipeline"]["task_graph"]["edges"]) == 4

    variant = doc["variants"][0]
    assert variant["id"] == "FHD30-Recording"
    assert variant["design_conditions"]["resolution"] == "FHD"
    assert variant["design_conditions"]["fps"] == 30
    assert variant["node_configs"]["t_byrp"]["inputs"][0]["port"] == "COMP_RD0_RDMA"
    assert variant["node_configs"]["t_postIRTA"]["kind"] == "sw_task"
    assert variant["buffer_overrides"]["BUF_T_CSIS_CSIS_WDMA_T_BYRP_COMP_RD0_RDMA"]["format"] == "BAYER_PACKED"

    Usecase.model_validate(doc)


def test_legacy_import_cli_emits_project_and_scenario_usecase_yaml():
    tmp_path = Path(__file__).parents[2] / f"_tmp_legacy_scenario_import_{uuid.uuid4().hex}"
    try:
        tmp_path.mkdir()
        scenario_path = tmp_path / "projectA_FHD30_recording_scenario.yaml"
        out_dir = tmp_path / "generated"
        scenario_path.write_text(yaml.safe_dump(_legacy_scenario(), sort_keys=False), encoding="utf-8")

        exit_code = main([
            "--scenario",
            str(scenario_path),
            "--out",
            str(out_dir),
            "--project",
            "proj-projectA",
            "--project-name",
            "Project A",
            "--soc",
            "soc-projectA",
            "--strict",
        ])

        assert exit_code == 0
        generated = sorted((out_dir / "02_definition").glob("*.yaml"))
        assert [path.name for path in generated] == [
            "proj-projectA.yaml",
            "uc-fhd30-recording.yaml",
        ]
        Project.model_validate(yaml.safe_load(generated[0].read_text(encoding="utf-8")))
        Usecase.model_validate(yaml.safe_load(generated[1].read_text(encoding="utf-8")))

        report = json.loads((out_dir / "import_report.json").read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["generated"]["project"] == 1
        assert report["generated"]["scenario_usecase"] == 1
        assert report["generated"]["scenario_variant"] == 1
    finally:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)


def test_convert_scenario_group_uses_superset_and_disables_missing_sw_hw_branch():
    report = ImportReport()
    doc = convert_scenario_group_usecase(
        [
            ("recording.yaml", _legacy_scenario()),
            ("preview.yaml", _legacy_preview_scenario()),
        ],
        project_ref="proj-projectA",
        schema_version="2.2",
        report=report,
        group_id="uc-camera-recording",
        group_name="Camera Recording",
    )

    assert doc is not None
    assert report.ok
    assert doc["id"] == "uc-camera-recording"
    assert {node["id"] for node in doc["pipeline"]["nodes"]} == {
        "t_sensor",
        "t_csis",
        "t_byrp",
        "t_postIRTA",
        "t_mfc",
        "t_dpu",
    }
    assert len(doc["variants"]) == 2

    recording = next(variant for variant in doc["variants"] if variant["id"] == "FHD30-Recording")
    preview = next(variant for variant in doc["variants"] if variant["id"] == "FHD30-Preview")
    assert recording["routing_switch"]["disabled_nodes"] == ["t_dpu"]
    assert set(preview["routing_switch"]["disabled_nodes"]) == {"t_postIRTA", "t_mfc"}
    assert "t_postIRTA" in recording["node_configs"]
    assert "t_postIRTA" not in preview["node_configs"]
    assert "t_dpu" in preview["node_configs"]
    assert "t_dpu" not in recording["node_configs"]
    assert recording["buffer_overrides"] != preview["buffer_overrides"]

    Usecase.model_validate(doc)


def test_convert_scenario_group_policy_can_reject_mixed_usecases():
    report = ImportReport()
    doc = convert_scenario_group_usecase(
        [
            ("recording.yaml", _legacy_scenario()),
            ("preview.yaml", _legacy_preview_scenario()),
        ],
        project_ref="proj-projectA",
        schema_version="2.2",
        report=report,
        group_id="uc-camera-recording",
        group_name="Camera Recording",
        grouping_policy={"require_same_usecase": True},
    )

    assert doc is None
    assert not report.ok
    assert any(message.code == "legacy_group_mixed_usecase" for message in report.messages)


def test_legacy_import_cli_emits_grouped_scenario_yaml():
    tmp_path = Path(__file__).parents[2] / f"_tmp_legacy_scenario_group_{uuid.uuid4().hex}"
    try:
        tmp_path.mkdir()
        recording_path = tmp_path / "projectA_FHD30_recording_scenario.yaml"
        preview_path = tmp_path / "projectA_FHD30_preview_scenario.yaml"
        out_dir = tmp_path / "generated"
        recording_path.write_text(yaml.safe_dump(_legacy_scenario(), sort_keys=False), encoding="utf-8")
        preview_path.write_text(yaml.safe_dump(_legacy_preview_scenario(), sort_keys=False), encoding="utf-8")

        exit_code = main([
            "--scenario-group",
            str(recording_path),
            str(preview_path),
            "--group-id",
            "uc-camera-recording",
            "--group-name",
            "Camera Recording",
            "--out",
            str(out_dir),
            "--project",
            "proj-projectA",
            "--project-name",
            "Project A",
            "--soc",
            "soc-projectA",
            "--strict",
        ])

        assert exit_code == 0
        generated = sorted((out_dir / "02_definition").glob("*.yaml"))
        assert [path.name for path in generated] == [
            "proj-projectA.yaml",
            "uc-camera-recording.yaml",
        ]
        Project.model_validate(yaml.safe_load(generated[0].read_text(encoding="utf-8")))
        Usecase.model_validate(yaml.safe_load(generated[1].read_text(encoding="utf-8")))

        report = json.loads((out_dir / "import_report.json").read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["generated"]["scenario_group_usecase"] == 1
        assert report["generated"]["scenario_variant"] == 2
    finally:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)


def test_legacy_import_cli_applies_grouping_policy_yaml():
    tmp_path = Path(__file__).parents[2] / f"_tmp_legacy_scenario_group_policy_{uuid.uuid4().hex}"
    try:
        tmp_path.mkdir()
        recording_path = tmp_path / "projectA_FHD30_recording_scenario.yaml"
        preview_path = tmp_path / "projectA_FHD30_preview_scenario.yaml"
        policy_path = tmp_path / "grouping_policy.yaml"
        out_dir = tmp_path / "generated"
        recording_path.write_text(yaml.safe_dump(_legacy_scenario(), sort_keys=False), encoding="utf-8")
        preview_path.write_text(yaml.safe_dump(_legacy_preview_scenario(), sort_keys=False), encoding="utf-8")
        policy_path.write_text(yaml.safe_dump({"require_same_usecase": True}, sort_keys=False), encoding="utf-8")

        exit_code = main([
            "--scenario-group",
            str(recording_path),
            str(preview_path),
            "--grouping-policy",
            str(policy_path),
            "--out",
            str(out_dir),
            "--project",
            "proj-projectA",
            "--project-name",
            "Project A",
            "--soc",
            "soc-projectA",
            "--strict",
        ])

        assert exit_code == 1
        report = json.loads((out_dir / "import_report.json").read_text(encoding="utf-8"))
        assert report["ok"] is False
        assert any(message["code"] == "legacy_group_mixed_usecase" for message in report["messages"])
    finally:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
