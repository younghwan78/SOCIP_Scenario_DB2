from types import SimpleNamespace
from unittest.mock import MagicMock

from scenario_db.api.services import library


def test_sets_split_defined_and_measured_builds(monkeypatch):
    variant = SimpleNamespace(scenario_id="s", id="v", node_configs={"eis": {"sw_timing": {"mean_ms": 4.0, "max_ms": 6.0, "value_source": "assumed"}},
                                                                   "mfc": {"mode": "x"}})
    import scenario_db.db.repositories.variant_resolution as vr
    monkeypatch.setattr(vr, "include_variant_parent_rows", lambda db, rows: rows)
    monkeypatch.setattr(vr, "resolve_variant_from_rows", lambda rows, s, v: variant)

    def ev(i, sw, synthetic, mean):
        return SimpleNamespace(id=f"m{i}", sw_baseline_ref=sw, measured_at=f"2026-10-0{i}T00:00:00",
                               provenance={"data_origin": "synthetic"} if synthetic else {"data_origin": "physical_capture"},
                               sw_task_timing=[{"task": "eis", "mean_ms": mean, "max_ms": mean + 1}])
    evs = [ev(1, "sw-vendor-v1.2.3", False, 5.0), ev(2, "sw-vendor-v1.2.3", False, 3.0), ev(3, "sw-vendor-v1.2.3", True, 9.0)]
    db = MagicMock()
    db.get.return_value = variant
    ev_q, sw_q = MagicMock(), MagicMock()
    ev_q.filter.return_value.all.return_value = evs
    sw_q.filter.return_value.all.return_value = [SimpleNamespace(id="sw-vendor-v1.2.3", metadata_={"compatible_soc": ["soc-exynos2600"]})]
    db.query.side_effect = lambda *a: ev_q if len(a) == 1 else sw_q
    monkeypatch.setattr(library, "is_synthetic", lambda prov: (prov or {}).get("data_origin") == "synthetic")

    out = library.sw_timing_sets(db, scenario_id="s", variant_id="v")
    labels = [s["label"] for s in out["sets"]]
    assert labels[0].startswith("정의 #") and labels[1:] == ["1.2.3 실측 · 2600", "1.2.3 합성 · 2600"]
    eis = out["tasks"][0]["values"]
    real = eis["measured:sw-vendor-v1.2.3:real"]
    assert real["mean_ms"] == 4.0 and real["delta_pct"] == 0.0 and real["evidence"] == 2
    assert eis["measured:sw-vendor-v1.2.3:syn"]["delta_pct"] == 125.0
