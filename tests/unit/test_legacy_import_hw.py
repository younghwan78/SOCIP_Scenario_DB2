from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import yaml

from scenario_db.legacy_import.cli import main
from scenario_db.legacy_import.normalize_hw import convert_hw_catalog
from scenario_db.legacy_import.report import ImportReport
from scenario_db.models.capability.hw import IpCatalog


def _legacy_hw_blocks() -> list[dict]:
    return [
        {
            "name": "CSIS",
            "type": "IP",
            "ip_group": "CSIS",
            "hierarchy_group": "ISP",
            "min_size": [64, 64],
            "max_size": [8192, 8192],
            "supports_crop": True,
            "supports_scale": False,
            "supported_modes": ["Normal"],
            "modules": [
                {"name": "NFI_DEC", "type": "CIN"},
                {"name": "CSIS_WDMA", "type": "DMA", "direction": "write", "supported_compressions": ["COMP_BAYER_LOSSLESS"]},
            ],
            "edges": [
                {"src": "NFI_DEC", "dst": "CSIS_WDMA"},
            ],
        },
        {
            "name": "MFC",
            "type": "IP",
            "ip_group": "CODEC",
            "hierarchy_group": "CODEC",
            "supported_modes": ["Normal", "LowPower"],
            "modules": [
                {"name": "MFC_RDMA", "type": "DMA", "direction": "read"},
            ],
        },
    ]


def test_convert_hw_catalog_preserves_dma_and_internal_edges():
    report = ImportReport()
    docs = convert_hw_catalog(
        _legacy_hw_blocks(),
        project_ref="proj-projectA",
        schema_version="2.2",
        report=report,
    )

    assert report.ok
    assert report.generated["ip_catalog"] == 2
    csis = docs[0]
    assert csis["id"] == "ip-csis-projecta"
    assert csis["category"] == "camera"
    assert csis["capabilities"]["supported_features"]["crop"] is True
    assert csis["capabilities"]["supported_features"]["scale"] is False
    assert csis["capabilities"]["supported_features"]["compression"] == ["COMP_BAYER_LOSSLESS"]
    assert csis["capabilities"]["properties"]["internal_edges"] == [{"from": "NFI_DEC", "to": "CSIS_WDMA"}]
    assert csis["capabilities"]["properties"]["dma_ports"][0]["name"] == "CSIS_WDMA"

    mfc = docs[1]
    assert mfc["category"] == "codec"
    assert {mode["id"] for mode in mfc["capabilities"]["operating_modes"]} == {"Normal", "LowPower"}

    for doc in docs:
        IpCatalog.model_validate(doc)


def test_legacy_import_cli_emits_canonical_hw_yaml():
    tmp_path = Path(__file__).parents[2] / f"_tmp_legacy_import_{uuid.uuid4().hex}"
    try:
        tmp_path.mkdir()
        hw_path = tmp_path / "projectA_hw.yaml"
        out_dir = tmp_path / "generated"
        hw_path.write_text(yaml.safe_dump(_legacy_hw_blocks(), sort_keys=False), encoding="utf-8")

        exit_code = main([
            "--hw",
            str(hw_path),
            "--out",
            str(out_dir),
            "--project",
            "proj-projectA",
            "--strict",
        ])

        assert exit_code == 0
        generated = sorted((out_dir / "00_hw").glob("*.yaml"))
        assert [path.name for path in generated] == [
            "ip-csis-projecta.yaml",
            "ip-mfc-projecta.yaml",
        ]
        for path in generated:
            IpCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

        report = json.loads((out_dir / "import_report.json").read_text(encoding="utf-8"))
        assert report["ok"] is True
        assert report["generated"]["ip_catalog"] == 2
    finally:
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
