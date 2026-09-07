from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from dashboard.components import viewer_timing_panel as timing
from dashboard.components.viewer_api_client import ViewerApiError
from scenario_db.api.schemas.view import ViewResponse
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.view.graph_utils import safe_id


def test_saved_timing_stays_pinned_when_latest_changes_and_rejects_foreign_scope(engine, api_client, monkeypatch):
    scenario_id = "uc-projecta-fhd30-recording"
    old_id, new_id = "sim-timing-contract-old", "sim-timing-contract-new"
    timing.clear_viewer_timing_caches()
    with Session(engine) as db:
        variant_id = db.query(ScenarioVariant.id).filter_by(scenario_id=scenario_id).order_by(ScenarioVariant.id).first()[0]
        graph = load_canonical_graph(db, scenario_id, variant_id)
        identities = {f"ip-{safe_id(node['id'])}": node["id"] for node in graph.pipeline_nodes}
        endpoint = f"/api/v1/scenarios/{scenario_id}/variants/{variant_id}/view"
        plain = api_client.get(endpoint, params={"level": 1}).json()
        edge = next(edge["data"] for edge in plain["edges"]
                    if edge["data"]["source"] in identities and edge["data"]["target"] in identities)
        source, target = identities[edge["source"]], identities[edge["target"]]
        events = [
            {"task_id": f"{source}#f0", "node_id": source, "frame_index": 0, "start_ms": 0, "end_ms": 5,
             "critical": True, "critical_path_rank": 0, "predecessors": []},
            {"task_id": f"{target}#f0", "node_id": target, "frame_index": 0, "start_ms": 5, "end_ms": 10,
             "critical": True, "critical_path_rank": 1, "predecessors": [f"{source}#f0"]},
        ]

        def store(identity, timestamp, timeline):
            db.add(Evidence(id=identity, schema_version="2.2", kind="evidence.simulation",
                            scenario_ref=scenario_id, variant_ref=variant_id, execution_context={},
                            aggregation={}, kpi={}, yaml_sha256="test", run_info={"timestamp": timestamp},
                            timeline_events=timeline))
            db.commit()

        def request(method, base, path, **kwargs):
            response = api_client.request(method, "/api/v1" + path, params=kwargs.get("params"))
            assert response.status_code == 200, response.text
            return response.json()

        monkeypatch.setattr(timing, "_request_json", request)
        try:
            store(old_id, "2099-01-01T00:00:00Z", events)
            selected = timing.resolve_overlay_evidence_id("http://timing-test", scenario_id, variant_id,
                                                         sim_mode="latest", sim_evidence_id=None)
            assert selected == old_id
            response = api_client.get(endpoint, params={"level": 1, "sim_evidence_id": selected})
            assert response.status_code == 200
            view = ViewResponse.model_validate(response.json())
            actual_id = timing.view_overlay_evidence_id(view, scenario_id, variant_id)
            assert actual_id == old_id
            mapped_edge = next(item for item in view.edges if item.data.id == edge["id"])
            assert mapped_edge.data.critical is True
            assert next(item for item in view.nodes if item.data.id == edge["target"]).data.sim_overlay.start_ms == 5
            newer = deepcopy(events)
            for item in newer:
                item["start_ms"] += 100
                item["end_ms"] += 100
            store(new_id, "2099-01-02T00:00:00Z", newer)
            latest = api_client.get("/api/v1/simulation/results", params={
                "scenario_ref": scenario_id, "variant_ref": variant_id, "latest": True,
            }).json()
            assert latest["items"][0]["id"] == new_id
            detail = timing._load_simulation_result("http://timing-test", actual_id, scenario_id, variant_id)
            assert detail["id"] == old_id
            assert detail["timeline_events"][0]["start_ms"] == 0
            with pytest.raises(ViewerApiError):
                timing._load_simulation_result("http://timing-test", actual_id, scenario_id, "foreign-variant")
        finally:
            db.query(Evidence).filter(Evidence.id.in_([old_id, new_id])).delete(synchronize_session=False)
            db.commit()
            timing.clear_viewer_timing_caches()
