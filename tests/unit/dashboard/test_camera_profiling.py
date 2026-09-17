from pathlib import Path
from streamlit.testing.v1 import AppTest
from dashboard.components.camera_profiling import camera_rows


def test_camera_page_loads_without_backend_or_capture():
    path = Path(__file__).resolve().parents[3] / "dashboard/pages/7_Camera_Profiling.py"
    app = AppTest.from_file(str(path)).run(timeout=20)
    assert not app.exception
    assert [t.label for t in app.tabs] == ["Import / Review", "SW Projection"]


def test_camera_display_does_not_convert_missing_runtime_to_zero():
    result = camera_rows(
        {
            "pipeline_model": {
                "tasks": [{"task_id": "eis", "kind": "sw", "stage": "eis"}],
                "execution_path": {"enabled_task_ids": ["eis"]},
            }
        }
    )
    assert result[0]["enabled"] and result[0]["mean_ms"] is None


def test_camera_review_renders_graph_and_statistics():
    path = (
        Path(__file__).resolve().parents[3]
        / "examples/measurement-import/camera/scenario-statistics.md"
    )
    script = f"""from pathlib import Path
from scenario_db.meas_import.camera import parse_markdown,assemble_camera
from dashboard.components.camera_profiling import render_camera
render_camera(assemble_camera(parse_markdown(Path({str(path)!r}).read_text(encoding="utf-8"))).model_dump(mode="json"))
"""
    app = AppTest.from_string(script).run(timeout=20)
    assert not app.exception
    assert len(app.dataframe) == 4
