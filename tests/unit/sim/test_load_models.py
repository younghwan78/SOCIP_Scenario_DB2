"""D-03: load models — the codec and bitrate set a decoder's effective ppc (node opt-in)."""
from __future__ import annotations

import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_is_v15_camera import FIXTURE, graph_from_fixture, read  # noqa: E402

from scenario_db.db.models.capability import IpCatalog  # noqa: E402
from scenario_db.sim.load_models import LOAD_MODELS, CodecThroughputV1, resolve_load_model  # noqa: E402
from scenario_db.sim.models import DVFSTable  # noqa: E402
from scenario_db.sim.timing_budget import TimingBudgetOptions, analyze_timing_budget  # noqa: E402

MODEL = "codec-throughput-v1"
CAPS = {
    "sim": {"load_models": {MODEL: {"codecs": {"AV1_DEC": {"ppc": 1.0, "cycles_per_bit": 0.5}, "H264_DEC": {"ppc": 2.0}}}}},
    "properties": {"codecs": {"decoders": {"VP9_DEC": {"max_resolution": "UHD", "max_fps": 60}}}},
}


def _eff(caps=CAPS, *, sim=None, design=None, width=3840, height=2160, fps=30.0, role="decoder"):
    return CodecThroughputV1().effective(caps=caps, node_id="mfc_dec", role=role, sim=sim or {}, design=design or {},
                                         width=width, height=height, fps=fps, base_ppc=4.0)


def test_the_registry_resolves_by_id():
    assert MODEL in LOAD_MODELS and resolve_load_model(MODEL, "n").id == MODEL
    with pytest.raises(ValueError, match="unknown load model"):
        resolve_load_model("nope", "n")


def test_codec_throughput_with_an_entropy_term_per_bit():
    # AV1 4K30 at 20 Mbps: 8.29 M px / 1.0 ppc + 20e6/30 bits x 0.5 cycles
    t = _eff(design={"codec_mfc": "AV1_DEC", "bitrate_mbps": 20})
    pixels = 3840 * 2160
    cycles = pixels / 1.0 + 20e6 / 30 * 0.5
    assert t["codec"] == "AV1_DEC" and t["direction"] == "decode" and t["ppc_source"] == "catalog"
    assert t["ppc_effective"] == pytest.approx(pixels / cycles, abs=1e-4)
    assert t["entropy_cycles_per_frame"] == pytest.approx(20e6 / 30 * 0.5, abs=0.1)
    # no bitrate (or no cycles_per_bit): the codec ppc alone
    assert _eff(sim={"codec": "h.264"})["ppc_effective"] == 2.0
    assert _eff(sim={"codec": "H264"}, design={"bitrate_mbps": 50})["ppc_effective"] == 2.0


def test_the_codec_limit_derives_the_ppc_when_no_coefficient_is_declared():
    caps = deepcopy(CAPS)
    caps["sim"]["load_models"][MODEL].update({"derive": "codec_limits", "clock_mhz": 664})
    t = _eff(caps, sim={"codec": "VP9_DEC"})
    assert t["ppc_codec"] == pytest.approx(3840 * 2160 * 60 / 664e6, abs=1e-4)
    assert t["ppc_source"] == "codec_limits (UHD60 at 664 MHz)"


@pytest.mark.parametrize("caps, sim, message", [
    ({}, {"codec": "AV1"}, "needs coefficients"),
    (CAPS, {"codec": "MPEG2"}, "needs a known codec"),
    (CAPS, {}, "needs a known codec"),
    (CAPS, {"codec": "VP9"}, "no coefficient for VP9_DEC"),
    (CAPS, {"codec": "HEVC_ENC"}, "no coefficient for HEVC_ENC"),
])
def test_an_opt_in_without_what_it_needs_is_refused(caps, sim, message):
    with pytest.raises(ValueError, match=message):
        _eff(caps, sim=sim)


@pytest.fixture(scope="module")
def youtube():
    catalog = {}
    for path in (FIXTURE / "00_hw").glob("ip-*.yaml"):
        d = read(path)
        catalog[d["id"]] = IpCatalog(id=d["id"], schema_version=d["schema_version"], category=d["category"],
                                     hierarchy=d["hierarchy"], capabilities=d["capabilities"], yaml_sha256="fixture")
    doc = read(FIXTURE / "00_hw" / "dvfs-exynos2600-sample-v0.yaml")
    tables = {k: DVFSTable.model_validate(v) for k, v in doc["domains"].items()}
    raw = read(FIXTURE / "02_definition" / "uc-vid-youtube-e2600.yaml")
    return catalog, tables, raw


def _opt_in(graph, catalog, coefficients):
    mfc = catalog["ip-mfc-s5e9965"]
    caps = deepcopy(mfc.capabilities)
    caps["sim"]["load_models"] = {MODEL: coefficients}
    ip = IpCatalog(id=mfc.id, schema_version=mfc.schema_version, category=mfc.category, hierarchy=mfc.hierarchy,
                   capabilities=caps, yaml_sha256="fixture-load-model")
    variant = deepcopy(graph.variant)
    cfg = variant.node_configs["mfc_dec"]
    variant.node_configs = {**variant.node_configs, "mfc_dec": {**cfg, "sim": {**cfg["sim"], "load_model": MODEL}}}
    return replace(graph, variant=variant, ip_catalog={**graph.ip_catalog, mfc.id: ip})


def _undeclared(graph):
    scenario = deepcopy(graph.scenario)
    pipeline = deepcopy(scenario.pipeline)
    for n in pipeline["nodes"]:
        n.pop("load_model", None)
    scenario.pipeline = pipeline
    return replace(graph, scenario=scenario)


def test_youtube_decoder_takes_the_codec_rate_only_when_it_opts_in(youtube):
    catalog, tables, raw = youtube
    graph = _undeclared(graph_from_fixture(raw, "yt-4k30-av1-sdr", catalog))
    plain = analyze_timing_budget(graph, TimingBudgetOptions(), dvfs_tables=tables)
    mfc = next(ip for ip in plain["ips"] if ip["node"] == "mfc_dec")
    assert "load_model" not in mfc  # undeclared: the mode ppc, as before
    slow = analyze_timing_budget(_opt_in(graph, catalog, {"codecs": {"AV1_DEC": {"ppc": 1.0, "cycles_per_bit": 0.5}}}),
                                 TimingBudgetOptions(), dvfs_tables=tables)
    lm = next(ip for ip in slow["ips"] if ip["node"] == "mfc_dec")
    assert lm["load_model"]["codec"] == "AV1_DEC" and lm["load_model"]["ppc_mode"] == 4.0
    assert lm["load_model"]["ppc_effective"] < 1.0
    # a quarter of the mode ppc (or less) needs at least four times the clock
    assert lm["own_required_mhz"] >= 4 * mfc["own_required_mhz"] * 0.99
    assert lm["hw_ms"] > mfc["hw_ms"] and lm["set_clock_mhz"] >= mfc["set_clock_mhz"]
    # the other IPs' own need is untouched (a DVFS domain shared with the MFC can still lift their set clock)
    others = {ip["node"]: ip["own_required_mhz"] for ip in plain["ips"] if ip["node"] != "mfc_dec"}
    assert {ip["node"]: ip["own_required_mhz"] for ip in slow["ips"] if ip["node"] != "mfc_dec"} == others


def test_where_a_node_takes_its_model_and_coefficients():
    from scenario_db.sim.load_models import load_model_for

    node = {"id": "mfc_dec", "load_model": {"ref": MODEL, "codecs": {"AV1_DEC": {"ppc": 1.0}}}}
    catalog_role = {"sim": {"load_models": {MODEL: {"roles": ["decoder"], "codecs": {}}}}}
    # the scenario node declares it with its own coefficients (the shared catalog is left as it is)
    assert load_model_for({}, {}, "decoder", node) == (MODEL, node["load_model"])
    # a catalog model listing the role applies to every node of that role, with the catalog coefficients
    assert load_model_for(catalog_role, {}, "decoder", {"id": "x"}) == (MODEL, None)
    assert load_model_for(catalog_role, {}, "encoder", {"id": "x"}) == (None, None)
    # the variant can opt out (none) or name the model itself
    assert load_model_for(catalog_role, {"load_model": "none"}, "decoder", node) == (None, None)
    assert load_model_for({}, {"load_model": MODEL}, "decoder", node) == (MODEL, node["load_model"])
    assert load_model_for({}, {}, "decoder", {"id": "x"}) == (None, None)


def test_e2600_decoders_use_the_scenario_coefficients_and_the_encoders_do_not(youtube):
    catalog, tables, raw = youtube
    node = next(n for n in raw["pipeline"]["nodes"] if n["id"] == "mfc_dec")
    assert node["load_model"]["ref"] == MODEL and node["load_model"]["value_source"] == "assumed"
    # the shared MFC catalog carries no load model: camera recording (encoder) inputs are unchanged
    assert "load_models" not in (catalog["ip-mfc-s5e9965"].capabilities.get("sim") or {})
    report = analyze_timing_budget(graph_from_fixture(raw, "yt-4k60-av1-hdr10", catalog), TimingBudgetOptions(), dvfs_tables=tables)
    mfc = next(ip for ip in report["ips"] if ip["node"] == "mfc_dec")
    assert mfc["load_model"]["codec"] == "AV1_DEC" and mfc["load_model"]["ppc_codec"] == 1.0
    assert report["verdict"]["status"] == "ok"
