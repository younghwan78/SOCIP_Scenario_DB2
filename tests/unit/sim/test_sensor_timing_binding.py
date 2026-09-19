from copy import deepcopy
from pathlib import Path
import pytest
import yaml
from scenario_db.sim.sensor_timing_binding import resolve_timing_binding, timing_mode_hash
from scenario_db.sim.sensor_timing import calculate_sensor_timing

ROOT = Path(__file__).parents[3] / "db_fixtures_Exynos2600_S26Plus/00_sensor"


def docs():
    return [yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
            for name in ("m2s/sensor-gng.yaml", "timing-s5kgng.yaml")]


def test_reviewed_mapping_coverage_and_formula():
    count = 0
    for board in ("m1s", "m2s"):
        catalog, profile = docs()
        catalog = yaml.safe_load((ROOT / board / "sensor-gng.yaml").read_text(encoding="utf-8"))
        for name, mode in catalog["modes"].items():
            if "timing_binding" not in mode:
                continue
            timing = resolve_timing_binding(catalog, mode, profile)
            result = calculate_sensor_timing(timing)
            assert result["valid_time_ms"] > 0
            assert timing["source"]["dt_mode_index"] == mode["decoded"]["mode_index"]
            count += 1
        assert "timing_binding" not in catalog["modes"]["mode0_aeb"]
        assert "timing_binding" not in catalog["modes"]["mode0_nfi"]
    assert count == 20


@pytest.mark.parametrize("field,value", [("mode_index", 999), ("mode_sha256", "0" * 64),
                                         ("profile_revision", "stale"), ("mode_label", "missing")])
def test_invalid_binding_rejected(field, value):
    catalog, profile = docs()
    mode = deepcopy(catalog["modes"]["mode0"])
    mode["timing_binding"][field] = value
    with pytest.raises(ValueError):
        resolve_timing_binding(catalog, mode, profile)


def test_wrong_sensor_missing_profile_and_extended_mode():
    catalog, profile = docs()
    mode = catalog["modes"]["mode0"]
    with pytest.raises(ValueError): resolve_timing_binding(catalog, mode, None)
    wrong = deepcopy(profile); wrong["sensor_name"] = "OTHER"
    with pytest.raises(ValueError): resolve_timing_binding(catalog, mode, wrong)
    mode["decoded"]["ex_mode"] = "EX_AEB"
    with pytest.raises(ValueError): resolve_timing_binding(catalog, mode, profile)


def test_hash_is_independent_of_yaml_layout():
    _, profile = docs()
    timing = next(iter(profile["modes"].values()))
    assert timing_mode_hash(timing) == timing_mode_hash(yaml.safe_load(yaml.safe_dump(timing)))


def test_all_sensor_bindings_resolve_and_cover_registered_sensors():
    profiles = {}
    for path in ROOT.glob("timing*.yaml"):
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        profiles[profile["id"]] = profile
    sensors = set()
    count = 0
    for path in ROOT.glob("*/sensor-*.yaml"):
        catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
        for mode in catalog["modes"].values():
            if mode.get("timing_binding"):
                timing = resolve_timing_binding(catalog, mode, profiles[mode["timing_binding"]["profile_ref"]])
                assert calculate_sensor_timing(timing)["valid_time_ms"] > 0
                sensors.add(catalog["sensor_name"])
                count += 1
    assert len(profiles) == 14
    assert sum(len(p["modes"]) for p in profiles.values()) == 433
    assert len(sensors) == 13
    assert count == 220


def test_numeric_source_parser_never_executes_expressions():
    from scripts.import_sensor_cis_timings import number
    assert number("201590000 * 4ULL") == 806360000
    assert number("0x1720") == 5920
    assert number("14872.0") == 14872
    with pytest.raises(ValueError): number("unknown_clock()")
    with pytest.raises(ValueError): number("10 / 2")
