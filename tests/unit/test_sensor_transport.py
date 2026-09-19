from copy import deepcopy
from pathlib import Path
import pytest
import yaml
from scenario_db.sim.sensor_transport import calculate_sensor_transport

FIXTURES = Path(__file__).parents[2] / "db_fixtures_Exynos2600_S26Plus/00_sensor"


def mode():
    return {"decoded": {"fps": 100, "lanes": 2, "mipi_speed_mbps": 1000},
            "vc": {"dma0": {"vc0": {"map": 0, "size": [1000, 100],
                "bits_per_pixel": 10, "hwformat_base": "RAW10", "data_class": "image"}}}}


def test_link_conversion_cap_and_dram_boundary():
    m = mode()
    m["option"] = {"max_fps": 50}
    d = calculate_sensor_transport(m, {"phy": "DPHY"})
    c = calculate_sensor_transport(m, {"phy": "CPHY"})
    assert d["declared_unique_vc_payload_bytes"] == 125000
    assert d["csis_payload_bytes_s"] == 6250000
    assert d["payload_link_utilization_pct"] == 2.5
    assert c["link_capacity_mbps"] == pytest.approx(d["link_capacity_mbps"] * 16 / 7)
    assert c["dram_write_bytes_s"] is None
    assert "valid_time_ms" not in c


def test_duplicate_dma_and_conflicting_declarations():
    m = mode()
    m["vc"]["dma1"] = deepcopy(m["vc"]["dma0"])
    r = calculate_sensor_transport(m, {"phy": "DPHY"})
    assert r["csis_payload_bytes_s"] == 12500000
    assert r["vc_rows"][1]["duplicate_route"]
    m["vc"]["dma1"]["vc0"]["size"] = [2000, 100]
    r = calculate_sensor_transport(m, {"phy": "DPHY"})
    assert r["status"] == "missing_input"
    assert r["csis_payload_bytes_s"] is None


def test_multiexposure_is_not_claimed_as_actual_traffic():
    m = mode()
    other = deepcopy(m["vc"]["dma0"]["vc0"])
    other["map"] = 1
    m["vc"]["dma0"]["vc1"] = other
    r = calculate_sensor_transport(m, {"phy": "DPHY"})
    assert r["status"] == "cadence_unresolved"
    assert r["all_vcs_at_assumed_fps_bytes_s"] == 25000000
    assert r["csis_payload_bytes_s"] is None
    assert r["link_status"] == "unknown"


def test_unknown_inputs_and_link_excess():
    m = mode()
    assert calculate_sensor_transport(m, {})["link_status"] == "unknown"
    m["decoded"]["mipi_speed_mbps"] = 1
    assert calculate_sensor_transport(m, {"phy": "DPHY"})["link_status"] == "payload_exceeds_capacity"
    m["vc"]["dma0"]["vc0"]["bits_per_pixel"] = None
    assert calculate_sensor_transport(m, {"phy": "DPHY"})["csis_payload_bytes_s"] is None


def test_all_catalog_modes_preserve_input_and_suffix():
    count = 0
    for path in FIXTURES.rglob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if doc.get("kind") != "sensor.catalog":
            continue
        original = deepcopy(doc)
        for label, m in doc["modes"].items():
            r = calculate_sensor_transport(m, doc["csis_wiring"])
            assert r["dram_write_bytes_s"] is None
            if doc["id"] == "sensor-gng-m2s" and label == "mode0":
                assert r["csis_payload_bytes_s"] == 17554200 * 120
            if doc["id"] == "sensor-gng-m2s" and label == "mode0_aeb_nfi":
                assert r["status"] == "cadence_unresolved"
            if doc["id"] == "sensor-gng-m2s" and label == "mode0_nfi":
                assert r["assumed_fps"] == 60
            count += 1
        assert doc == original
    assert count == 449
