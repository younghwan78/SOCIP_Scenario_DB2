from __future__ import annotations

from scenario_db.sim.csv_import import (
    apply_sim_import_mapping,
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


def test_apply_sim_import_mapping_updates_catalogs_and_role_modes(tmp_path):
    csv_path = tmp_path / "projectA_info.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Project,A,,,,,,",
                "Name,Mode,Unit Power,IDC,PPC,VDD,DVFS",
                "BYRP,Normal,4.34,0,4,VDD_CAM,CAM",
                "RGBP,Normal,3.728,0,4,VDD_CAM,CAM",
                "MFC,Normal,1.0,0,4,VDD_INT,INT",
            ]
        ),
        encoding="utf-8",
    )
    catalog_root = tmp_path / "fixtures"
    hw_dir = catalog_root / "00_hw"
    hw_dir.mkdir(parents=True)
    isp_catalog = hw_dir / "ip-isp.yaml"
    isp_catalog.write_text(
        """
id: ip-isp
schema_version: "2.2"
kind: ip
category: camera
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: Normal
""",
        encoding="utf-8",
    )
    mfc_catalog = hw_dir / "ip-mfc.yaml"
    mfc_catalog.write_text(
        """
id: ip-mfc
schema_version: "2.2"
kind: ip
category: codec
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: Normal
""",
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(
        f"""
source_csv: {csv_path.as_posix()}
catalog_root: {catalog_root.as_posix()}
catalogs:
  - catalog: 00_hw/ip-isp.yaml
    hw_name: ISP
    base:
      hw_name: ISP
      modes:
        Normal:
          unit_power_mw_mp: 0.0
          idc: 0.0
          ppc: 0.0
          vdd: VDD_CAM
          dvfs_group: CAM
    role_modes:
      bayer_processing: BYRP
      rgb_processing: RGBP
  - catalog: 00_hw/ip-mfc.yaml
    hw_name: MFC
""",
        encoding="utf-8",
    )

    results = apply_sim_import_mapping(mapping)

    assert [item.changed for item in results] == [True, True]
    isp = isp_catalog.read_text(encoding="utf-8")
    assert "role_modes:" in isp
    assert "bayer_processing:" in isp
    assert "unit_power_mw_mp: 4.34" in isp
    mfc = mfc_catalog.read_text(encoding="utf-8")
    assert "hw_name: MFC" in mfc
    assert "dvfs_group: INT" in mfc


def test_apply_sim_import_mapping_dry_run_does_not_write(tmp_path):
    csv_path = tmp_path / "projectA_info.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Project,A,,,,,,",
                "Name,Mode,Unit Power,IDC,PPC,VDD,DVFS",
                "MFC,Normal,1.0,0,4,VDD_INT,INT",
            ]
        ),
        encoding="utf-8",
    )
    catalog = tmp_path / "ip-mfc.yaml"
    original = """
id: ip-mfc
schema_version: "2.2"
kind: ip
category: codec
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: Normal
"""
    catalog.write_text(original, encoding="utf-8")
    mapping = tmp_path / "mapping.yaml"
    mapping.write_text(
        f"""
source_csv: {csv_path.as_posix()}
catalog_root: {tmp_path.as_posix()}
catalogs:
  - catalog: ip-mfc.yaml
    hw_name: MFC
""",
        encoding="utf-8",
    )

    results = apply_sim_import_mapping(mapping, dry_run=True)

    assert results[0].changed is True
    assert catalog.read_text(encoding="utf-8") == original
