from __future__ import annotations

from types import SimpleNamespace

from scenario_db.cdgm.resolver import resolve_cdgm_arch_info


def _ip(ip_id: str, capabilities: dict) -> SimpleNamespace:
    return SimpleNamespace(id=ip_id, capabilities=capabilities, category="camera")


def _graph() -> SimpleNamespace:
    return SimpleNamespace(
        scenario_id="uc-camera",
        variant_id="UHD60-HLG",
        scenario=SimpleNamespace(metadata_={"domain": ["camera"], "category": ["camera"]}),
        variant=SimpleNamespace(
            design_conditions={
                "resolution_class": "UHD",
                "fps": 60,
                "hdr_format": "HLG",
                "codec_flow": "decode",
            },
            size_overrides={},
            tags=[],
        ),
        pipeline_nodes=[
            {"id": "csis0", "ip_ref": "ip-csis-v8", "role": "CSIS"},
            {"id": "isp0", "ip_ref": "ip-isp-v12", "role": "ISP"},
            {"id": "mfc", "ip_ref": "ip-mfc-v14", "role": "MFC"},
        ],
        ip_catalog={
            "ip-csis-v8": _ip(
                "ip-csis-v8",
                {
                    "sim": {
                        "cdgm_roles": {
                            "CSIS": {
                                "arch_ip": "CSIS",
                                "path_type": "input",
                                "ppc": 8.0,
                                "vdd": "VDD_CAM",
                                "dvfs_domain": "CSIS",
                            }
                        }
                    }
                },
            ),
            "ip-isp-v12": _ip(
                "ip-isp-v12",
                {
                    "sim": {
                        "cdgm_roles": {
                            "RT_ISP": {
                                "arch_ip": "RT_ISP",
                                "path_type": "rt",
                                "ppc": 8.0,
                                "vdd": "VDD_CAM",
                                "dvfs_domain": "CAM",
                            },
                            "ISP": {
                                "arch_ip": "ISP",
                                "path_type": "nrt",
                                "ppc": 4.0,
                                "vdd": "VDD_CAM",
                                "dvfs_domain": "ISP",
                                "pos": ["STEP1", "STEP2", "STEP3"],
                            },
                        }
                    }
                },
            ),
            "ip-mfc-v14": _ip(
                "ip-mfc-v14",
                {
                    "sim": {
                        "cdgm_roles": {
                            "MFC": {
                                "arch_ip": "MFC",
                                "path_type": "codec",
                                "ppc": 2.0,
                                "vdd": "VDD_INT",
                                "dvfs_domain": "MFC",
                            }
                        }
                    }
                },
            ),
        },
    )


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        id="cdgm-prof-soc-A-v1",
        role_overrides={
            "MFC_MFD_UHD60_HLG": {
                "extends": "MFC",
                "ip_ref": "ip-mfc-v14",
                "arch_ip": "MFC_MFD_UHD60_HLG",
                "path_type": "codec",
                "ppc": 6.0,
                "vdd": "VDD_INT",
                "dvfs_domain": "MFC",
                "when": {
                    "scenario_domain": "camera",
                    "resolution_class": "UHD",
                    "fps": 60,
                    "hdr_format": "HLG",
                },
            }
        },
    )


def test_resolve_cdgm_arch_info_projects_ip_roles_and_profile_overrides():
    result = resolve_cdgm_arch_info(
        _graph(),
        dvfs_domains={"CSIS": {}, "CAM": {}, "ISP": {}, "MFC": {}},
        profile=_profile(),
    )

    rows_by_role = {row["role_key"]: row for row in result["arch_info_rows"]}

    assert result["issues"] == []
    assert rows_by_role["RT_ISP"]["ip_ref"] == "ip-isp-v12"
    assert rows_by_role["ISP"]["pos"] == "STEP1+STEP2+STEP3"
    assert rows_by_role["MFC_MFD_UHD60_HLG"]["ppc"] == 6.0
    assert rows_by_role["MFC_MFD_UHD60_HLG"]["source"]["kind"] == "profile_override"


def test_resolve_cdgm_arch_info_reports_missing_dvfs_domain():
    result = resolve_cdgm_arch_info(
        _graph(),
        dvfs_domains={"CSIS": {}, "CAM": {}, "MFC": {}},
        profile=_profile(),
    )

    assert any(issue["code"] == "cdgm_dvfs_domain_not_found" for issue in result["issues"])
