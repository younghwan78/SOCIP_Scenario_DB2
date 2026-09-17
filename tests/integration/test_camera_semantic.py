from copy import deepcopy
from pathlib import Path
import pytest
from sqlalchemy.orm import Session
from scenario_db.api.deps import get_db
from scenario_db.db.models.evidence import Evidence
from scenario_db.etl.loader import load_yaml_dir

ROOT = Path(__file__).resolve().parents[2]


def without_nulls(value):
    if isinstance(value, dict):
        return {k: without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_nulls(v) for v in value]
    return value


def test_camera_import_roundtrip_projection_and_conflicts(engine, api_client):
    with engine.connect() as connection:
        tx = connection.begin()
        previous = api_client.app.dependency_overrides[get_db]

        def test_db():
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                yield session

        api_client.app.dependency_overrides[get_db] = test_db
        try:
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                assert load_yaml_dir(
                    ROOT / "db_fixtures_Exynos2600_S26Plus", session, strict=True, validate=True
                ).ok
                before = session.query(Evidence).count()
            markdown = (
                ROOT / "examples/measurement-import/camera/scenario-statistics.md"
            ).read_text(encoding="utf-8")
            preview = api_client.post(
                "/api/v1/profiling/import/preview", json={"markdown": markdown}
            )
            assert preview.status_code == 200, preview.text
            prepared = preview.json()
            with Session(connection) as session:
                assert session.query(Evidence).count() == before
            payload = {"markdown": markdown, "expected_hash": prepared["sha256"]}
            saved = api_client.post("/api/v1/profiling/import/commit", json=payload)
            assert saved.status_code == 200, saved.text
            assert saved.json()["status"] == "created"
            assert (
                api_client.post("/api/v1/profiling/import/commit", json=payload).json()["status"]
                == "unchanged"
            )
            got = api_client.get("/api/v1/evidence/" + prepared["evidence"]["id"]).json()
            for key in (
                "pipeline_model",
                "profiling_metadata",
                "stage_timing",
                "execution_path_id",
                "sw_task_timing",
                "sw_event_latency",
            ):
                assert without_nulls(got[key]) == without_nulls(prepared["evidence"][key])
            filtered = api_client.get(
                "/api/v1/evidence", params={"execution_path_id": "fhd30-vdis"}
            ).json()
            assert any(r["id"] == got["id"] for r in filtered["items"])
            changed = {"markdown": markdown.replace("avg_ms: 0.2", "avg_ms: 0.25")}
            newer = api_client.post("/api/v1/profiling/import/preview", json=changed).json()
            assert (
                api_client.post(
                    "/api/v1/profiling/import/commit",
                    json={**changed, "expected_hash": prepared["sha256"]},
                ).status_code
                == 422
            )
            assert (
                api_client.post(
                    "/api/v1/profiling/import/commit",
                    json={**changed, "expected_hash": newer["sha256"]},
                ).status_code
                == 422
            )
            legacy = dict(
                profile_id="forged",
                revision=1,
                evidence_ref=got["id"],
                evidence_sha256=prepared["sha256"],
                project_ref=got["project_ref"],
                scenario_ref=got["scenario_ref"],
                variant_ref=got["variant_ref"],
                design_conditions=prepared["evidence"]["profiling_metadata"]["workload"],
                task_runtime={},
            )
            # Legacy profile creation must explicitly reject curated captures, even without HW mapping.
            blocked = api_client.post(
                "/api/v1/evidence/" + got["id"] + "/timing-profile",
                json=dict(profile_id="legacy", task_mapping={"eis": "eis"}),
            )
            assert blocked.status_code == 422
            selection = dict(
                source_evidence_ref=got["id"],
                target_project_ref=got["project_ref"],
                target_scenario_ref=got["scenario_ref"],
                target_variant_ref="cam-rec-r1-uhd30-vdis",
                target_path_id="uhd30-vdis",
                task_mapping={"eis": "eis"},
                runtime_overrides={"eis": {"scale": 1.3}},
                assumption_notes="Synthetic cross-workload test, unchanged EIS SW",
            )
            projection = api_client.post("/api/v1/profiling/sw-projection/prepare", json=selection)
            assert projection.status_code == 200, projection.text
            projected = projection.json()
            assert projected["task_runtime"]["eis"]["mean_ms"] == 2.6
            config = {
                "sw_timing_projection": projected,
                "include_timeline": True,
                "timeline_frame_count": 2,
            }
            request = dict(
                scenario_id=selection["target_scenario_ref"],
                variant_id=selection["target_variant_ref"],
                execution_context={**got["execution_context"], "method": "projection"},
                config=config,
                persist=False,
            )
            run = api_client.post("/api/v1/simulation/run", json=request)
            assert run.status_code == 200, run.text
            result = run.json()
            assert result["evidence"]["derived_from"] == [got["id"]]
            assert result["evidence"]["execution_context"]["method"] == "projection"
            assert (
                result["evidence"]["resolution_result"]["overall_feasibility"] != "production_ready"
            )
            assert (
                next(t for t in result["result"]["sw_task_timing"] if t["task"] == "eis")["mean_ms"]
                == 2.6
            )
            assert (
                next(t for t in result["result"]["sw_task_timing"] if t["task"] == "eis")[
                    "value_source"
                ]
                == "projected"
            )
            altered = deepcopy(request)
            altered["config"]["sw_timing_projection"]["task_runtime"]["eis"]["mean_ms"] = 2.7
            assert api_client.post("/api/v1/simulation/run", json=altered).status_code == 422
            invalid = deepcopy(selection)
            invalid["task_mapping"] = {"rt_chain": "eis"}
            invalid["runtime_overrides"] = {}
            assert (
                api_client.post("/api/v1/profiling/sw-projection/prepare", json=invalid).status_code
                == 422
            )
            exploration = api_client.post(
                "/api/v1/exploration/scenarios/preview",
                json=dict(
                    project_ref=selection["target_project_ref"],
                    scenario_id=selection["target_scenario_ref"],
                    variant_id=selection["target_variant_ref"],
                    config=config,
                    axes=[dict(target="node_clock_mhz", node_id="gdc_m", values=[300, 400])],
                ),
            )
            assert exploration.status_code == 200, exploration.text
            assert len(exploration.json()["cases"]) == 3
            with Session(connection) as session:
                assert session.query(Evidence).count() == before + 1
        finally:
            api_client.app.dependency_overrides[get_db] = previous
            tx.rollback()


def test_camera_cli_commits_to_postgres(engine, api_client, monkeypatch, tmp_path, capsys):
    from scenario_db.meas_import import camera_api
    from scenario_db.meas_import.camera import main
    from urllib.parse import urlsplit

    with engine.connect() as connection:
        tx = connection.begin()
        previous = api_client.app.dependency_overrides[get_db]

        def test_db():
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                yield session

        api_client.app.dependency_overrides[get_db] = test_db
        try:
            with Session(connection, join_transaction_mode="create_savepoint") as session:
                assert load_yaml_dir(
                    ROOT / "db_fixtures_Exynos2600_S26Plus", session, strict=True, validate=True
                ).ok
                before = session.query(Evidence).count()

            def post(url, payload, headers):
                response = api_client.post(urlsplit(url).path, json=payload, headers=headers)
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                return response.json()

            monkeypatch.setattr(camera_api, "_post_json", post)
            text = (ROOT / "examples/measurement-import/camera/scenario-statistics.md").read_text(
                encoding="utf-8"
            )
            text = text.replace("meas-camera-semantic-example-r1", "meas-camera-cli-r1")
            source = tmp_path / "capture.md"
            source.write_text(text, encoding="utf-8")
            args = ["--markdown", str(source), "--commit"]
            assert main(args) == 0
            import json

            assert json.loads(capsys.readouterr().out)["status"] == "created"
            assert main(args) == 0
            assert json.loads(capsys.readouterr().out)["status"] == "unchanged"
            source.write_text(text.replace("avg_ms: 0.2", "avg_ms: 0.25"), encoding="utf-8")
            assert main(args) == 1
            with Session(connection) as session:
                assert session.query(Evidence).count() == before + 1
                row = session.get(Evidence, "meas-camera-cli-r1")
                assert row.sw_task_timing[0]["mean_ms"] == 0.2
        finally:
            api_client.app.dependency_overrides[get_db] = previous
            tx.rollback()
