from __future__ import annotations

from pathlib import Path

from scenario_db.sim.fixture_contract import load_fixture_documents, validate_soc_sim_contract


ROOT = Path(__file__).resolve().parents[3]
EXYNOS2600_FIXTURE = ROOT / "db_fixtures_Exynos2600_S26Plus"
EXYNOS2500_FIXTURE = ROOT / "demo" / "generated" / "scenariodb"


def test_exynos2600_fixture_contract_separates_compute_and_external_metadata():
    docs = load_fixture_documents(EXYNOS2600_FIXTURE)

    report = validate_soc_sim_contract(docs, soc_id="soc-exynos2600")

    assert report["status"] == "warning"
    assert report["errors"] == []
    assert report["summary"]["compute_ip_count"] > 0
    assert report["summary"]["external_ip_count"] == 3
    assert not _issues_for_code(report, "MISSING_PPC")
    assert _issues_for_code(report, "BORROWABLE_SIM_PARAMS")
    assert _issues_for_code(report, "SENSOR_VVALID_INPUTS_MISSING")


def test_exynos2500_demo_contract_is_not_blocked_without_external_catalog():
    docs = load_fixture_documents(EXYNOS2500_FIXTURE)

    report = validate_soc_sim_contract(docs, soc_id="soc-exynos2500")

    assert report["status"] == "warning"
    assert report["errors"] == []
    assert _issues_for_code(report, "NO_EXTERNAL_DEVICE_CATALOG")


def test_contract_blocks_missing_soc_ip_ref():
    docs = [
        {
            "id": "soc-test",
            "kind": "soc",
            "ips": [{"ref": "ip-missing"}],
        }
    ]

    report = validate_soc_sim_contract(docs, soc_id="soc-test")

    assert report["status"] == "blocked"
    assert _issues_for_code(report, "IP_REF_NOT_FOUND")


def test_contract_blocks_compute_ip_without_positive_ppc():
    docs = [
        {
            "id": "soc-test",
            "kind": "soc",
            "ips": [{"ref": "ip-camera-test"}],
        },
        {
            "id": "ip-camera-test",
            "kind": "ip",
            "category": "camera",
            "capabilities": {
                "sim": {
                    "modes": {
                        "Normal": {
                            "ppc": 0,
                            "unit_power_mw_mp": 1.0,
                            "dvfs_group": "CAM",
                            "vdd": "VDD_CAM",
                        }
                    }
                }
            },
        },
    ]

    report = validate_soc_sim_contract(docs, soc_id="soc-test")

    assert report["status"] == "blocked"
    assert _issues_for_code(report, "MISSING_PPC")


def _issues_for_code(report: dict, code: str) -> list[dict]:
    return [
        issue
        for section in ("errors", "warnings", "borrowable")
        for issue in report[section]
        if issue["code"] == code
    ]
