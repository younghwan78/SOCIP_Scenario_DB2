"""Unsupported timing is excluded from What-if feasibility, answers and sweeps."""

from unittest.mock import MagicMock

import pytest

from scenario_db.api.schemas.scenario_whatif import WhatIfAskRequest, WhatIfConstraints, WhatIfPreviewRequest
from scenario_db.api.services import scenario_whatif as service
from scenario_db.api.services import whatif_sweep
from scenario_db.db.models.definition import Project
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.timing_budget import NOT_APPLICABLE_NOTE
from tests.unit.api.test_scenario_whatif import _service
from tests.unit.sim.test_adapter_runner import _exynos2600_generated_graph


@pytest.fixture
def audio(monkeypatch):
    graph = _exynos2600_generated_graph("uc-aud-mp3-playback-e2600", "audio-mp3-screen-on")
    graph.project = Project(id=graph.scenario.project_ref, metadata_={"soc_ref": "soc-exynos2600"}, globals_={})
    _service(monkeypatch, graph)
    from scenario_db.api.services import whatif_sensors
    monkeypatch.setattr(whatif_sensors, "catalog_binding_targets", lambda *a: [])
    return graph, {"project_ref": graph.scenario.project_ref, "scenario_id": graph.scenario_id, "variant_id": graph.variant_id}


def test_audio_preview_and_sweep_never_pass(audio):
    graph, scope = audio
    request = WhatIfPreviewRequest(**scope, expected_baseline_hash=baseline_fingerprint(graph), changes=[{"target": "fps", "value": 24}])
    db = MagicMock()
    result = service.preview(db, request)
    for case in (result["baseline"], result["candidate"]):
        assert case["report"]["verdict"]["status"] == "not_applicable"
        assert not case["metrics"]["feasible"]
    eligible, reasons, _, _ = whatif_sweep._eligibility(result, WhatIfConstraints())
    assert not eligible and NOT_APPLICABLE_NOTE in reasons
    answer = service._answer({}, {}, result, None, None, [])
    assert answer["verdict"] == "not_applicable"
    assert "미지원" in answer["headline"] and NOT_APPLICABLE_NOTE in answer["facts"]
    db.commit.assert_not_called()


@pytest.mark.parametrize("ask", ["diagnose", "search_limit"])
def test_audio_answers_remain_unsupported_even_without_dvfs_domains(audio, ask):
    _, scope = audio
    out = service.ask(MagicMock(), WhatIfAskRequest(**scope, ask=ask))
    answer = out["answer"]
    assert answer["verdict"] == "not_applicable"
    assert answer["actions"] == [] and NOT_APPLICABLE_NOTE in answer["facts"]
    assert "충족" not in answer["headline"]


def test_unsupported_combine_is_neither_a_pass_nor_a_failure():
    combo = {"rows": [{"key": "baseline", "levers": [], "feasible": False, "verdict": "not_applicable", "delta": None}],
             "levers": [], "baseline_mw": 0, "best": None}
    answer = service._combine_answer(combo)
    assert answer["verdict"] == "not_applicable"
    assert answer["facts"] == [NOT_APPLICABLE_NOTE]
