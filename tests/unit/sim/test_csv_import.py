from __future__ import annotations

from scenario_db.sim.csv_import import (
    build_sim_block,
    load_legacy_sim_info_csv,
    merge_sim_block_into_catalog_yaml,
)


def test_load_legacy_sim_info_csv_builds_mode_block(tmp_path):
    csv_path = tmp_path / "projectA_info.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Project,A,,,,,,",
                "Name,Mode,Unit Power,IDC,PPC,VDD,DVFS",
                "YUVP,Normal,0.352,0,4,VDD_CAM,CAM",
                "YUVP,FHD,0.403,0,4,VDD_CAM,CAM",
                "YUVP,8K,0.331,0,4,VDD_CAM,CAM",
            ]
        ),
        encoding="utf-8",
    )

    rows = load_legacy_sim_info_csv(csv_path)
    block = build_sim_block(rows, "YUVP")

    assert block["hw_name"] == "YUVP"
    assert block["source_project"] == "A"
    assert block["modes"]["Normal"]["unit_power_mw_mp"] == 0.352
    assert block["modes"]["FHD"]["ppc"] == 4
    assert block["modes"]["8K"]["dvfs_group"] == "CAM"


def test_merge_sim_block_into_catalog_yaml():
    source = """
id: ip-mfc-v14
schema_version: "2.2"
kind: ip
category: codec
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: normal
      throughput_mpps: 120
"""
    rendered = merge_sim_block_into_catalog_yaml(
        source,
        {
            "hw_name": "MFC",
            "modes": {"Normal": {"unit_power_mw_mp": 1.0, "idc": 0.0, "ppc": 4.0}},
        },
    )

    assert "sim:" in rendered
    assert "hw_name: MFC" in rendered
    assert "unit_power_mw_mp: 1.0" in rendered
