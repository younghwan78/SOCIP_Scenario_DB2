from __future__ import annotations

from unittest.mock import MagicMock
from types import SimpleNamespace
from pathlib import Path
from zipfile import ZipFile
import io

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from scenario_db.api.app import create_app
from scenario_db.api.deps import get_db
from scenario_db.api.schemas.simulation import SimulateRequest, SimulateRunResponse
from scenario_db.api.routers import simulation as simulation_router
from scenario_db.db.models.capability import SocDvfsTable
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.reporting.models import WrittenArtifact, WrittenReportBundle
from scenario_db.sim.models import SimRunResult
from scenario_db.sim.service import run_simulation_request


def test_simulation_run_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    def _fake_run(db_arg, request):
        assert db_arg is db
        assert request.scenario_id == "uc-camera-recording"
        return {
            "evidence_id": "sim-uc-camera-recording-FHD30-SDR-H265-abc123",
            "status": "completed",
            "cached": False,
            "params_hash": "abc123",
            "warnings": ["isp0 has ppc=0"],
            "kpi": {"total_power_mw": 1.0},
            "result": None,
        }

    monkeypatch.setattr(simulation_router, "run_simulation_request", _fake_run)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/simulation/run",
        json={
            "scenario_id": "uc-camera-recording",
            "variant_id": "FHD30-SDR-H265",
            "execution_context": {
                "silicon_rev": "EVT0",
                "sw_baseline_ref": "sw-vendor-v1.2.3",
                "thermal": "hot",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_id"].startswith("sim-uc-camera-recording")
    assert body["cached"] is False
    assert body["warnings"] == ["isp0 has ppc=0"]
    assert body["kpi"]["total_power_mw"] == 1.0


def test_delete_simulation_result_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    def _fake_delete(db_arg, evidence_id):
        assert db_arg is db
        assert evidence_id == "sim-1"
        return True

    monkeypatch.setattr(simulation_router, "delete_simulation_evidence", _fake_delete)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.delete("/api/v1/simulation/results/sim-1")

    assert response.status_code == 204
    db.commit.assert_called_once()


def test_delete_simulation_result_404(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    monkeypatch.setattr(simulation_router, "delete_simulation_evidence", lambda db_arg, evidence_id: False)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.delete("/api/v1/simulation/results/missing")

    assert response.status_code == 404
    db.commit.assert_not_called()


def test_export_simulation_result_artifacts_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    class _Row:
        id = "sim-1"
        kind = "evidence.simulation"
        schema_version = "2.2"
        scenario_ref = "uc-camera-recording"
        variant_ref = "FHD30-SDR-H265"
        sw_baseline_ref = "sw-vendor-v1.2.3"
        execution_context = {"silicon_rev": "EVT0", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "normal"}
        run_info = {"timestamp": "2026-05-21T01:02:03+09:00", "tool": "scenariodb-sim"}
        aggregation = {}
        kpi = {"total_power_mw": 1.0}
        ip_breakdown = []
        dma_breakdown = []
        timing_breakdown = []
        dvfs_breakdown = []
        timeline_events = []
        external_devices = []
        topology_order = []
        vdd_power = {}
        calculation_trace = None
        params_hash = "abc123"
        artifacts = []

    out_dir = Path("E:/reports").resolve()

    def _fake_write(evidence, *, context, output_dir, overwrite):
        assert evidence["id"] == "sim-1"
        assert context.project_ref == "projectA"
        assert context.variant_name == "FHD30 Recording"
        assert Path(output_dir) == out_dir
        assert overwrite is True
        return WrittenReportBundle(
            prefix="projectA-FHD30_Recording",
            output_dir=out_dir,
            artifacts=[
                WrittenArtifact(
                    type="timing_chart",
                    storage="local_file",
                    path=out_dir / "projectA-FHD30_Recording_timing_chart.html",
                    sha256="sha-timing",
                    bytes=10,
                )
            ],
        )

    updated_artifacts = []

    def _fake_update(db_arg, evidence_id, artifacts):
        assert db_arg is db
        assert evidence_id == "sim-1"
        updated_artifacts.extend(artifacts)
        return _Row()

    monkeypatch.setattr(simulation_router, "get_evidence", lambda db_arg, evidence_id: _Row())
    monkeypatch.setattr(simulation_router, "get_settings", lambda: MagicMock(report_dir="output_simulation", allow_custom_report_dir=True))
    monkeypatch.setattr(simulation_router, "write_report_bundle", _fake_write, raising=False)
    monkeypatch.setattr(
        simulation_router,
        "artifact_metadata",
        lambda bundle: [{"type": "timing_chart", "storage": "local_file", "path": str(out_dir / "projectA-FHD30_Recording_timing_chart.html"), "sha256": "sha-timing"}],
        raising=False,
    )
    monkeypatch.setattr(simulation_router, "update_simulation_artifacts", _fake_update, raising=False)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/simulation/results/sim-1/artifacts/export",
        json={"output_dir": str(out_dir), "project_ref": "projectA", "variant_name": "FHD30 Recording"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence_id"] == "sim-1"
    assert body["prefix"] == "projectA-FHD30_Recording"
    assert body["artifacts"][0]["bytes"] == 10
    assert updated_artifacts[0]["sha256"] == "sha-timing"
    db.commit.assert_called_once()


def test_export_simulation_result_rejects_output_dir_outside_report_root(
    monkeypatch,
    tmp_path: Path,
):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    class _Row:
        id = "sim-1"
        kind = "evidence.simulation"
        schema_version = "2.2"
        scenario_ref = "uc-camera-recording"
        variant_ref = "FHD30-SDR-H265"
        execution_context = {}
        run_info = {}
        aggregation = {}
        kpi = {}
        ip_breakdown = []
        dma_breakdown = []
        timing_breakdown = []
        dvfs_breakdown = []
        timeline_events = []
        external_devices = []
        topology_order = []
        vdd_power = {}
        artifacts = []

    monkeypatch.setattr(simulation_router, "get_evidence", lambda db_arg, evidence_id: _Row())
    report_root = tmp_path / "report-root"
    outside_dir = tmp_path.parent / "outside-reports"
    monkeypatch.setattr(
        simulation_router,
        "get_settings",
        lambda: MagicMock(report_dir=str(report_root), allow_custom_report_dir=False),
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/simulation/results/sim-1/artifacts/export",
        json={"output_dir": str(outside_dir)},
    )

    assert response.status_code == 422
    db.commit.assert_not_called()


def test_export_simulation_result_existing_files_return_conflict(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    class _Row:
        id = "sim-1"
        kind = "evidence.simulation"
        schema_version = "2.2"
        scenario_ref = "uc-camera-recording"
        variant_ref = "FHD30-SDR-H265"
        execution_context = {}
        run_info = {}
        aggregation = {}
        kpi = {}
        ip_breakdown = []
        dma_breakdown = []
        timing_breakdown = []
        dvfs_breakdown = []
        timeline_events = []
        external_devices = []
        topology_order = []
        vdd_power = {}
        artifacts = []

    def _raise_exists(*args, **kwargs):
        raise FileExistsError("already exists")

    monkeypatch.setattr(simulation_router, "get_evidence", lambda db_arg, evidence_id: _Row())
    monkeypatch.setattr(simulation_router, "get_settings", lambda: MagicMock(report_dir="output_simulation", allow_custom_report_dir=False))
    monkeypatch.setattr(simulation_router, "write_report_bundle", _raise_exists)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/api/v1/simulation/results/sim-1/artifacts/export",
        json={"output_dir": "projectA", "overwrite": False},
    )

    assert response.status_code == 409
    db.commit.assert_not_called()


def test_download_simulation_result_artifacts_zip_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    class _Row:
        id = "sim-1"
        kind = "evidence.simulation"
        schema_version = "2.2"
        scenario_ref = "uc-camera-recording"
        variant_ref = "FHD30-SDR-H265"
        execution_context = {}
        run_info = {}
        aggregation = {}
        kpi = {}
        ip_breakdown = []
        dma_breakdown = []
        timing_breakdown = []
        dvfs_breakdown = []
        timeline_events = []
        external_devices = []
        topology_order = []
        vdd_power = {}
        artifacts = []

    monkeypatch.setattr(simulation_router, "get_evidence", lambda db_arg, evidence_id: _Row())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/v1/simulation/results/sim-1/artifacts/download.zip",
        params={"project_ref": "projectA", "variant_name": "FHD30 Recording"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == [
            "projectA-FHD30_Recording_bw_chart.html",
            "projectA-FHD30_Recording_simulation_result.html",
            "projectA-FHD30_Recording_timing_chart.html",
        ]


def test_simulation_readiness_endpoint(monkeypatch):
    app = create_app()
    db = MagicMock()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    def _fake_readiness(db_arg, scenario_id, variant_id):
        assert db_arg is db
        assert scenario_id == "uc-camera-recording"
        assert variant_id == "FHD30-SDR-H265"
        return {
            "status": "ready",
            "scenario_id": scenario_id,
            "variant_id": variant_id,
            "soc_id": "soc-exynos2500",
            "profile": {"soc_id": "soc-exynos2500"},
            "summary": {"compute_nodes": 2},
            "errors": [],
            "warnings": [],
        }

    monkeypatch.setattr(simulation_router, "check_simulation_readiness_request", _fake_readiness)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get(
        "/api/v1/simulation/readiness",
        params={"scenario_id": "uc-camera-recording", "variant_id": "FHD30-SDR-H265"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["summary"]["compute_nodes"] == 2


def test_run_simulation_request_returns_response_on_cache_miss(monkeypatch):
    db = MagicMock()

    class _Inputs:
        scenario_id = "scenario"
        variant_id = "variant"
        project_ref = "project"
        warnings = []

    class _Evidence:
        id = "sim-1"
        kpi = {"total_power_mw": 1.0}
        resolution_result = None
        schema_version = "2.2"
        kind = "evidence.simulation"
        scenario_ref = "scenario"
        variant_ref = "variant"
        execution_context = ExecutionContext(
            silicon_rev="EVT0",
            sw_baseline_ref="sw-vendor-v1.2.3",
            thermal="normal",
        )
        sweep_context = None
        aggregation = MagicMock()
        run = MagicMock()
        ip_breakdown = []
        dma_breakdown = []
        timing_breakdown = []
        dvfs_breakdown = []
        timeline_events = []
        external_devices = []
        topology_order = []
        vdd_power = {}
        calculation_trace = None
        params_hash = "abc123"
        artifacts = []

    _Evidence.aggregation.model_dump.return_value = {}
    _Evidence.run.model_dump.return_value = {}

    monkeypatch.setattr("scenario_db.sim.service.load_canonical_graph", lambda db_arg, scenario_id, variant_id: object())
    monkeypatch.setattr("scenario_db.sim.service.build_simulation_inputs", lambda graph, config: _Inputs())
    monkeypatch.setattr("scenario_db.sim.service.params_hash", lambda inputs: "inputs-hash")
    monkeypatch.setattr("scenario_db.sim.service.get_simulation_evidence_by_params_hash", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "scenario_db.sim.service.run_simulation",
        lambda inputs, dvfs_tables: SimRunResult(
            scenario_id="scenario",
            variant_id="variant",
            total_power_mw=1.0,
            total_power_ma=0.0,
            core_power_mw=1.0,
            bw_power_mw=0.0,
            bw_total_mbs=0.0,
            hw_time_max_ms=0.0,
            feasible=True,
        ),
    )
    monkeypatch.setattr("scenario_db.sim.service.build_simulation_evidence", lambda *args, **kwargs: _Evidence())

    response = run_simulation_request(
        db,
        SimulateRequest(
            scenario_id="scenario",
            variant_id="variant",
            execution_context=ExecutionContext(
                silicon_rev="EVT0",
                sw_baseline_ref="sw-vendor-v1.2.3",
                thermal="normal",
            ),
            force=True,
        ),
    )

    assert response.evidence_id == "sim-1"
    assert response.status == "completed"
    assert response.cached is False
    assert response.persisted is False


def test_persist_race_converges_on_winning_simulation_evidence(monkeypatch):
    db = MagicMock()
    db.commit.side_effect = IntegrityError("INSERT evidence", {}, Exception("duplicate"))

    inputs = SimpleNamespace(
        scenario_id="scenario",
        variant_id="variant",
        project_ref="project",
        warnings=["input warning"],
    )
    generated = SimpleNamespace(id="sim-scenario-variant-request-hash")
    winner = SimpleNamespace(id=generated.id)
    lookups = iter([None, winner])

    monkeypatch.setattr(
        "scenario_db.sim.service.load_canonical_graph",
        lambda db_arg, scenario_id, variant_id: object(),
    )
    monkeypatch.setattr(
        "scenario_db.sim.service.build_simulation_inputs",
        lambda graph, config: inputs,
    )
    monkeypatch.setattr(
        "scenario_db.sim.service._request_hash",
        lambda *args, **kwargs: "request-hash",
    )
    monkeypatch.setattr(
        "scenario_db.sim.service.get_simulation_evidence_by_params_hash",
        lambda *args, **kwargs: next(lookups),
    )
    monkeypatch.setattr("scenario_db.sim.service.run_simulation", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        "scenario_db.sim.service.build_simulation_evidence",
        lambda *args, **kwargs: generated,
    )
    monkeypatch.setattr("scenario_db.sim.service.get_evidence", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "scenario_db.sim.service.upsert_simulation_evidence",
        lambda *args, **kwargs: None,
    )

    def _cached_response(row, response_inputs, hash_value):
        assert row is winner
        assert response_inputs is inputs
        assert hash_value == "request-hash"
        return SimulateRunResponse(
            evidence_id=row.id,
            status="completed",
            cached=True,
            params_hash=hash_value,
            warnings=list(response_inputs.warnings),
            kpi={},
            persisted=True,
        )

    monkeypatch.setattr(
        "scenario_db.sim.service._cached_simulation_response",
        _cached_response,
    )

    response = run_simulation_request(
        db,
        SimulateRequest(
            scenario_id="scenario",
            variant_id="variant",
            execution_context=ExecutionContext(
                silicon_rev="EVT0",
                sw_baseline_ref="sw-vendor-v1.2.3",
                thermal="normal",
            ),
            persist=True,
        ),
    )

    assert response.cached is True
    assert response.evidence_id == generated.id
    db.rollback.assert_called_once_with()


def test_persisted_rerun_response_keeps_repository_artifacts(monkeypatch):
    db = MagicMock()
    inputs = SimpleNamespace(
        scenario_id="scenario",
        variant_id="variant",
        project_ref="project",
        warnings=[],
    )
    result = SimRunResult(
        scenario_id="scenario",
        variant_id="variant",
        total_power_mw=999.0,
        total_power_ma=0.0,
        core_power_mw=999.0,
        bw_power_mw=0.0,
        bw_total_mbs=0.0,
        hw_time_max_ms=0.0,
        feasible=True,
    )
    generated = SimpleNamespace(
        id="sim-scenario-variant-request-hash",
        kpi={"total_power_mw": 999.0},
    )
    persisted_row = SimpleNamespace(
        id=generated.id,
        schema_version="2.2",
        kind="evidence.simulation",
        scenario_ref="scenario",
        variant_ref="variant",
        kpi=generated.kpi,
        artifacts=[
            {
                "type": "simulation_report",
                "storage": "file",
                "path": "reports/result.html",
            }
        ],
    )

    monkeypatch.setattr(
        "scenario_db.sim.service.load_canonical_graph",
        lambda db_arg, scenario_id, variant_id: object(),
    )
    monkeypatch.setattr(
        "scenario_db.sim.service.build_simulation_inputs",
        lambda graph, config: inputs,
    )
    monkeypatch.setattr(
        "scenario_db.sim.service._request_hash",
        lambda *args, **kwargs: "request-hash",
    )
    monkeypatch.setattr("scenario_db.sim.service.run_simulation", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        "scenario_db.sim.service.build_simulation_evidence",
        lambda *args, **kwargs: generated,
    )
    monkeypatch.setattr(
        "scenario_db.sim.service.get_evidence",
        lambda *args, **kwargs: persisted_row,
    )
    monkeypatch.setattr(
        "scenario_db.sim.service.upsert_simulation_evidence",
        lambda *args, **kwargs: persisted_row,
    )

    response = run_simulation_request(
        db,
        SimulateRequest(
            scenario_id="scenario",
            variant_id="variant",
            execution_context=ExecutionContext(
                silicon_rev="EVT0",
                sw_baseline_ref="sw-vendor-v1.2.3",
                thermal="normal",
            ),
            persist=True,
            force=True,
        ),
    )

    assert response.persisted is True
    assert response.evidence["artifacts"] == persisted_row.artifacts


def test_run_simulation_request_loads_db_dvfs_table_and_marks_context(monkeypatch):
    class _Inputs:
        scenario_id = "scenario"
        variant_id = "variant"
        project_ref = "project"
        warnings = []

    class _Evidence:
        def __init__(self, execution_context):
            self.id = "sim-1"
            self.kpi = {"total_power_mw": 1.0}
            self.resolution_result = None
            self.schema_version = "2.2"
            self.kind = "evidence.simulation"
            self.scenario_ref = "scenario"
            self.variant_ref = "variant"
            self.execution_context = execution_context
            self.sweep_context = None
            self.aggregation = MagicMock()
            self.run = MagicMock()
            self.ip_breakdown = []
            self.dma_breakdown = []
            self.timing_breakdown = []
            self.dvfs_breakdown = []
            self.timeline_events = []
            self.external_devices = []
            self.topology_order = []
            self.vdd_power = {}
            self.calculation_trace = None
            self.params_hash = "abc123"
            self.artifacts = []
            self.aggregation.model_dump.return_value = {}
            self.run.model_dump.return_value = {}

    class _Query:
        def __init__(self, row):
            self.row = row
            self.filters = {}

        def filter_by(self, **kwargs):
            self.filters.update(kwargs)
            return self

        def one_or_none(self):
            if self.filters == {"id": "dvfs-soc-A-v4"}:
                return self.row
            return None

    dvfs_row = SocDvfsTable(
        id="dvfs-soc-A-v4",
        schema_version="2.3",
        soc_ref="soc-A",
        dvfs_version=4,
        evt_hint="EVT1",
        source={"guide_name": "camera_dvfs_guide"},
        domains={
            "CAM": {
                "domain": "CAM",
                "levels": [
                    {"level": 0, "speed_mhz": 800.0, "voltages": {4: 800.0}},
                    {"level": 4, "speed_mhz": 332.0, "voltages": {4: 606.25}},
                ],
            }
        },
        compatibility_scope="soc",
        yaml_sha256="sha",
    )
    db = MagicMock()
    db.query.return_value = _Query(dvfs_row)
    captured = {}

    monkeypatch.setattr(
        "scenario_db.sim.service.load_canonical_graph",
        lambda db_arg, scenario_id, variant_id: SimpleNamespace(soc=SimpleNamespace(id="soc-A")),
    )
    monkeypatch.setattr("scenario_db.sim.service.build_simulation_inputs", lambda graph, config: _Inputs())
    monkeypatch.setattr("scenario_db.sim.service.params_hash", lambda inputs: "inputs-hash")
    monkeypatch.setattr("scenario_db.sim.service.get_simulation_evidence_by_params_hash", lambda *args, **kwargs: None)

    def _run(inputs, dvfs_tables):
        captured["dvfs_tables"] = dvfs_tables
        return SimRunResult(
            scenario_id="scenario",
            variant_id="variant",
            total_power_mw=1.0,
            total_power_ma=0.0,
            core_power_mw=1.0,
            bw_power_mw=0.0,
            bw_total_mbs=0.0,
            hw_time_max_ms=0.0,
            feasible=True,
        )

    def _evidence(result, *, execution_context, project_ref, params_hash):
        captured["execution_context"] = execution_context
        return _Evidence(execution_context)

    monkeypatch.setattr("scenario_db.sim.service.run_simulation", _run)
    monkeypatch.setattr("scenario_db.sim.service.build_simulation_evidence", _evidence)

    response = run_simulation_request(
        db,
        SimulateRequest(
            scenario_id="scenario",
            variant_id="variant",
            execution_context=ExecutionContext(
                silicon_rev="EVT0",
                sw_baseline_ref="sw-vendor-v1.2.3",
                thermal="normal",
            ),
            dvfs_table_ref="dvfs-soc-A-v4",
            force=True,
        ),
    )

    assert response.evidence_id == "sim-1"
    assert captured["dvfs_tables"]["CAM"].levels[0].speed_mhz == 800.0
    assert captured["execution_context"].dvfs_table_ref == "dvfs-soc-A-v4"
    assert captured["execution_context"].dvfs_version == 4
    assert captured["execution_context"].evt_hint == "EVT1"
