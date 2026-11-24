"""R-4b: the E2600 ABOX subsystem in the audio scenarios (assumed values)."""

import pytest
import yaml

from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

ROOT = "db_Exynos2600_SM-S947B/02_definition"
UCS = ("uc-aud-mp3-playback-e2600", "uc-aud-streaming-e2600")
OPTS = TimingBudgetOptions(throughput_model="pipelined")


@pytest.fixture(scope="module")
def reports():
    out = {}
    for uc in UCS:
        with open(f"{ROOT}/{uc}.yaml", encoding="utf-8") as fh:
            for v in yaml.safe_load(fh)["variants"]:
                out[v["id"]] = (v, analyze_timing_budget(_exynos2600_generated_graph(uc, v["id"]), OPTS))
    return out


def test_every_audio_variant_runs_the_abox_subsystem(reports):
    for vid, (v, r) in reports.items():
        sub = r["subsystems"]["abox"]
        assert r["power"]["domain_loads"]["abox"]["model"] == "mcps-v1", vid
        assert sub["feasible"] and sub["unattributed_units"] == [], vid
        assert sub["route"]["latency_ok"], vid
        output = "bt_codec" if "bt_codec" not in (v.get("routing_switch") or {}).get("disabled_nodes", []) else "speaker"
        assert sub["route"]["id"] == ("pb_bt" if output == "bt_codec" else "pb_speaker"), vid


def test_the_offload_path_decodes_on_the_dsp_and_wakes_rarely(reports):
    off = reports["audio-mp3-screen-off-offload"][1]["subsystems"]["abox"]
    cpu = reports["audio-mp3-screen-on"][1]["subsystems"]["abox"]
    assert "decode" in off["route"]["stages"] and "decode" not in cpu["route"]["stages"]
    assert off["wake"]["per_s"] == pytest.approx(0.5) and cpu["wake"]["per_s"] == pytest.approx(50.0)


def test_hires_flac_runs_192k_streams_and_the_bt_child_does_not_inherit_them(reports):
    flac = reports["audio-flac-hires-screen-off"][1]["subsystems"]["abox"]
    bt = reports["audio-aac-bt-screen-on"][1]["subsystems"]["abox"]
    units = {u["id"]: u for u in flac["units"]}
    assert units["hifi5"]["load_mcps"] == pytest.approx(100.0)
    assert {u["id"]: u for u in bt["units"]}["hifi5"]["load_mcps"] == pytest.approx(25.0)
    assert flac["route"]["streams"] == ["pb_main", "pb_out"]


def test_the_subsystem_is_the_abox_node_power(reports):
    for vid, (_v, r) in reports.items():
        row = next(ip for ip in r["ips"] if ip["node"] == "abox")
        assert row["power_mw"] == pytest.approx(r["subsystems"]["abox"]["mw"], abs=1e-3), vid
        assert r["power"]["hw_by_ip"]["abox"] == pytest.approx(r["subsystems"]["abox"]["mw"], abs=1e-3), vid
