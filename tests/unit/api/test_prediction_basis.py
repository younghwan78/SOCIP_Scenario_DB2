from scenario_db.api.services.prediction_basis import _sw_short, basis_label


def test_basis_label_recorded_and_legacy():
    assert basis_label({"recorded": True, "config_profile_ref": "simcfg-x-v2", "config_version": 2,
                        "power_params_ref": "pmp-exynos2600-v2", "power_params_version": 2,
                        "engine_rev": "arch-exploration/11"}) == "cfg2 · pmp2 · e11"
    assert basis_label({"recorded": True, "config_profile_ref": None, "power_params_ref": None,
                        "engine_rev": "arch-exploration/11"}) == "cfg 기본 · pmp 기본 · e11"
    # older runs did not record their config selection: no guess
    assert basis_label({"recorded": False, "engine_rev": "arch-exploration/9"}) == "미기록 · e9"


def test_sw_short():
    assert _sw_short("sw-vendor-v1.2.3") == "1.2.3"
    assert _sw_short(None) is None


def test_soc_short_and_sw_timing_hash():
    from scenario_db.api.services.prediction_basis import soc_short, sw_timing_hash

    assert soc_short("soc-exynos2600") == "2600" and soc_short(None) is None
    doc = {"node_configs": {"eis": {"sw_timing": {"mean_ms": 3.0}}, "mfc": {"mode": "x"}}}
    h = sw_timing_hash(doc)
    assert h and len(h) == 6
    assert sw_timing_hash({"node_configs": {"eis": {"sw_timing": {"mean_ms": 3.1}}}}) != h  # value change -> new id
    assert sw_timing_hash({"node_configs": {"mfc": {}}}) is None
