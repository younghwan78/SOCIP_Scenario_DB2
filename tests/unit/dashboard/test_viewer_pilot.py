from types import SimpleNamespace
import pytest
from dashboard.components.viewer_pilot import pilot_payload


def test_pilot_preserves_frame_flow_identity_and_disables_deadline_display():
    view = SimpleNamespace(scenario_id="uc-camera-recording", variant_id="cam-rec-r1-uhd30-vdis",
                           model_dump=lambda **kw: {"nodes": [], "edges": []})
    result = dict(id="capture", project_ref="proj-sm-s947b", scenario_ref=view.scenario_id,
                  variant_ref=view.variant_id, timeline_events=[dict(task_id="slice:1", start_ms=0,
                  node_id="sensor_rear", frame_index=0, predecessors=[], source_slice_name="SENSOR_READOUT f0000",
                  resource_name="Scenario / SENSOR / SENSOR")])
    args=pilot_payload(result,view)
    assert args["pilot"] is True
    assert args["options"]["showDeadlines"] is False
    assert args["options"]["frameIntervalMs"] == pytest.approx(1000/30)
    assert args["events"][0]["task_id"] == "slice:1"
    assert args["events"][0]["display_name"] == "SENSOR_READOUT f0000"
    with pytest.raises(ValueError,match="belong"):
        pilot_payload({**result,"variant_ref":"another"},view)
