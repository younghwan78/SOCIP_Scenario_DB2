from copy import deepcopy

import pytest

from scenario_db.sim.scenario_exploration import ScenarioExplorationRequest, preview_scenario
from scenario_db.sim.workloads import sim_params_for_node
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


def test_resolved_baseline_stable_and_preview_readonly():
    graph = _exynos2600_generated_graph('uc-camera-recording', 'cam-rec-r1-fhd30-vdis')
    before = deepcopy(graph.variant.node_configs)
    req = ScenarioExplorationRequest(scenario_id=graph.scenario_id, variant_id=graph.variant_id,
        project_ref=graph.scenario.project_ref, axes=[dict(target='sw_margin',values=[1.1,1.3])])
    report = preview_scenario(graph, req)
    assert report['persisted'] is False
    assert len(report['cases']) == 3
    assert report['cases'][0]['case_id'] == 'baseline'
    assert graph.variant.node_configs == before
    assert len({c['input_hash'] for c in report['cases']}) == 3
    assert report['cases'][0]['metrics']['total_power_mw'] is None
    assert report['cases'][0]['optimization_eligible'] is False
    with pytest.raises(ValueError, match='exceeds'):
        preview_scenario(graph, req, max_cases=2)


def test_operating_mode_clock_cap_is_respected():
    from types import SimpleNamespace
    ip = SimpleNamespace(id='ip-test', capabilities=dict(sim=dict(ppc=2,max_clock_mhz=800),
                          operating_modes=[dict(id='Normal',max_clock_mhz=400)]))
    params = sim_params_for_node(ip, {}, mode='Normal',node_id='n',role='r',warnings=[])
    assert params.max_clock_mhz == 400
