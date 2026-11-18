"""W3-7: E2600 display / game / video variants leave no IP at 0 mW except UFS storage (no host power coefficient).

GPU / NPU / ABOX get their power from D-03 domain loads; modes without sim coefficients (DPU VRR, MFC Secure /
LowLatency), the M2M scaler and the APV decoder carry assumed ``sim.ip_params`` on the variant (E2600 only).
"""

import pytest
import yaml

from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.domain_loads import domain_load_config
from scenario_db.sim.models import SimulationRunConfig
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph

ROOT = "db_Exynos2600_SM-S947B/02_definition"
SCENARIOS = ["uc-vid-playback-local-e2600", "uc-vid-youtube-e2600", "uc-disp-gallery-e2600", "uc-game-play-e2600",
             "uc-game-streaming-e2600"]
NOT_MODELLED = {"ip-ufs-s5e9965"}  # UFS host controller: no power coefficient in the source release


def _variants(scenario):
    with open(f"{ROOT}/{scenario}.yaml", encoding="utf-8") as fh:
        return [v["id"] for v in yaml.safe_load(fh)["variants"]]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_active_ip_has_power_coefficients_or_a_domain_load(scenario):
    gaps = []
    for vid in _variants(scenario):
        g = _exynos2600_generated_graph(scenario, vid)
        nodes = {str(n["id"]): n for n in g.scenario.pipeline["nodes"]}
        for w in build_simulation_inputs(g, SimulationRunConfig()).workloads:
            if w.ip_ref in NOT_MODELLED or (w.sim_params.ppc > 0 and w.sim_params.unit_power_mw_mp > 0):
                continue
            caps = g.ip_catalog[w.ip_ref].capabilities or {}
            if domain_load_config(caps, nodes.get(w.node_id), (g.variant.node_configs or {}).get(w.node_id) or {}):
                continue
            gaps.append(f"{vid}:{w.node_id} ({w.mode})")
    assert gaps == []
