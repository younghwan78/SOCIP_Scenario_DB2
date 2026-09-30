from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.comparison.evidence import compare_prediction_measurement
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.meas_import.cli import main as meas_import
from scenario_db.meas_import.meta import MeasurementImportMeta, PmuSpec
from scenario_db.meas_import.pmu_digest import (
    PmuDigestError,
    build_pmu_digest,
    import_pmu_digest,
    main as pmu_main,
    read_pmu_samples,
)
from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.sim.clock_models import ConfiguredClock
from scenario_db.sim.dvfs_resolver import DvfsResolver
from scenario_db.sim.measured_clock import measured_clocks_from_observations
from scenario_db.sim.models import IPSimParams, IPWorkload
from scenario_db.sim.service import _apply_measured_clocks

REPO = Path(__file__).resolve().parents[3]
SAMPLE_DIR = REPO / "examples" / "measurement-import" / "pmu-sample"
MTNR = "ip-mtnr-is-v15-s5e9975"
MCSC = "ip-mcsc-is-v15-s5e9975"
IP_MAP = {"MTNR": MTNR, "MCSC": MCSC}


def _csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "pmu.csv"
    path.write_text("metric,scope_kind,scope_ref,value,unit,stat,freq_mhz\n" + body, encoding="utf-8")
    return path


def _digest(tmp_path: Path, body: str, **kw):
    return build_pmu_digest(read_pmu_samples(_csv(tmp_path, body)), **kw)


def _by_id(digest):
    return {(o["metric_id"], o["scope"]["ref"]): o for o in digest.observations}


# --- reduction -----------------------------------------------------------------
def test_sample_file_reduces_to_catalog_observations():
    spec = PmuSpec(
        file="pmu_digest.csv", ip_map=IP_MAP, cluster_map={"big": "BIG", "little": "LIT"}
    )
    digest = import_pmu_digest(SAMPLE_DIR / "pmu_digest.csv", spec)
    obs = _by_id(digest)

    mtnr = obs[("clock.ip", MTNR)]
    # residency-weighted mean of 300ms@600, 600ms@800, 100ms@1000
    assert mtnr["stats"] == {"mean": 760.0, "p50": 800.0, "min": 600.0, "max": 1000.0}
    assert obs[("clock.ip_dominant", MTNR)]["value"] == 800.0
    assert obs[("clock.ip", MCSC)]["stats"] == {"mean": 650.0, "max": 1000.0}
    assert obs[("clock.ip_dominant", MCSC)]["value"] == 800.0
    assert obs[("bandwidth.mem_read", "total")]["stats"] == {"mean": 5200.0, "p95": 6100.0}
    assert obs[("bandwidth.mem_write", "total")]["stats"] == {"mean": 3400.0}  # 3.4 GB/s
    assert obs[("cpu.ipc", "BIG")]["value"] == pytest.approx(2.0)
    assert obs[("cpu.ipc", "LIT")]["value"] == pytest.approx(0.5)
    assert obs[("cpu.cycles", "BIG")]["value"] == 1.8e9
    assert digest.warnings == []


def test_explicit_clock_row_beats_residency_derived_field(tmp_path):
    digest = _digest(
        tmp_path,
        "ip_clock_residency,ip,X,1,ms,,500\nip_clock_residency,ip,X,1,ms,,700\nip_clock_mhz,ip,X,555,MHz,mean,\n",
    )
    assert _by_id(digest)[("clock.ip", "X")]["stats"]["mean"] == 555.0


def test_explicit_ipc_wins_over_derived(tmp_path):
    digest = _digest(
        tmp_path,
        "cpu_cycles,cluster,big,100,count,sum,\ncpu_instructions,cluster,big,300,count,sum,\ncpu_ipc,cluster,big,1.5,ipc,,\n",
    )
    assert _by_id(digest)[("cpu.ipc", "big")]["value"] == 1.5


def test_units_are_normalised_to_canonical(tmp_path):
    digest = _digest(tmp_path, "ip_clock_mhz,ip,X,1.2,GHz,mean,\nmem_bw_read_mbs,dram,ch0,2,GB/s,mean,\n")
    obs = _by_id(digest)
    assert obs[("clock.ip", "X")]["stats"]["mean"] == pytest.approx(1200.0)
    assert obs[("bandwidth.mem_read", "ch0")]["stats"]["mean"] == 2000.0


def test_unmapped_names_and_unknown_metrics_are_reported_not_fatal(tmp_path):
    digest = _digest(tmp_path, "ip_clock_mhz,ip,MCSC,650,MHz,mean,\nfoo_counter,ip,MCSC,1,,,\n")
    assert any("foo_counter" in w for w in digest.warnings)
    assert any("ip:MCSC" in w for w in digest.warnings)
    assert ("clock.ip", "MCSC") in _by_id(digest)


def test_json_input_equals_csv_input(tmp_path):
    rows = [
        {"metric": "ip_clock_mhz", "scope_kind": "ip", "scope_ref": "MCSC", "value": 650, "unit": "MHz", "stat": "mean"},
        {"metric": "mem_bw_read_mbs", "scope_kind": "mif", "scope_ref": "total", "value": 100, "unit": "MB/s"},
    ]
    path = tmp_path / "pmu.json"
    path.write_text(json.dumps({"format": "scenariodb.pmu_digest", "version": 1, "samples": rows}), encoding="utf-8")
    from_json = build_pmu_digest(read_pmu_samples(path), ip_map=IP_MAP).observations
    from_csv = _digest(tmp_path, "ip_clock_mhz,ip,MCSC,650,MHz,mean,\nmem_bw_read_mbs,mif,total,100,MB/s,,\n", ip_map=IP_MAP).observations
    assert from_json == from_csv


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("ip_clock_mhz,ip,X,fast,MHz,mean,\n", "not a number"),
        ("ip_clock_mhz,ip,X,650,rpm,mean,\n", "unit 'rpm'"),
        ("ip_clock_mhz,cluster,X,650,MHz,mean,\n", "scope_kind"),
        ("ip_clock_mhz,ip,X,650,MHz,mean,\nip_clock_mhz,ip,X,660,MHz,mean,\n", "duplicate"),
        ("ip_clock_residency,ip,X,5,ms,,\n", "freq_mhz"),
        ("ip_clock_residency,ip,X,5,ms,,nan\n", "freq_mhz"),
        ("ip_clock_residency,ip,X,5,ms,,inf\n", "freq_mhz"),
        ("mem_bw_read_mbs,mif,total,-1,MB/s,mean,\n", ">= 0"),
        ("ip_clock_mhz,ip,X,0,MHz,mean,\n", "positive"),
        ("cpu_cycles,cluster,big,5,count,p95,\n", "counter stat"),
    ],
)
def test_malformed_rows_fail_with_a_row_level_message(tmp_path, body, message):
    with pytest.raises(PmuDigestError, match=message):
        _digest(tmp_path, body)


def test_missing_columns_and_empty_file_fail(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("metric,value\nip_clock_mhz,1\n", encoding="utf-8")
    with pytest.raises(PmuDigestError, match="missing columns"):
        read_pmu_samples(bad)
    empty = tmp_path / "empty.csv"
    empty.write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(PmuDigestError, match="empty"):
        read_pmu_samples(empty)


def test_all_zero_residency_is_skipped_with_warning(tmp_path):
    digest = _digest(tmp_path, "ip_clock_residency,ip,X,0,ms,,500\n")
    assert digest.observations == [] and any("all zero" in w for w in digest.warnings)


def test_module_cli_prints_observations(capsys):
    code = pmu_main([str(SAMPLE_DIR / "pmu_digest.csv"), "--ip-map", f"MTNR={MTNR}", "--ip-map", f"MCSC={MCSC}"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["samples"] == 13
    assert {o["metric_id"] for o in payload["observations"]} >= {"clock.ip", "cpu.ipc", "bandwidth.mem_write"}
    assert pmu_main([str(SAMPLE_DIR / "missing.csv")]) == 1


# --- meta / import CLI ----------------------------------------------------------
def test_pmu_only_meta_imports_into_valid_measurement_evidence(tmp_path):
    out = tmp_path / "out"
    assert meas_import(["--meta", str(SAMPLE_DIR / "meta.yaml"), "--out", str(out), "--strict"]) == 0
    (doc_path,) = (out / "03_evidence").glob("*.yaml")
    doc = yaml.safe_load(doc_path.read_text(encoding="utf-8"))
    MeasurementEvidence.model_validate(doc)
    ids = {o["metric_id"] for o in doc["metric_observations"]}
    assert {"clock.ip", "clock.ip_dominant", "bandwidth.mem_read", "cpu.cycles", "cpu.ipc"} <= ids
    assert any(a["type"] == "pmu_digest" and a["sha256"] for a in doc["artifacts"])
    report = json.loads((out / "meas_import_report.json").read_text(encoding="utf-8"))
    assert report["generated"]["pmu_observations"] == len(
        [o for o in doc["metric_observations"]]
    )


def test_invalid_pmu_digest_is_a_structured_import_error(tmp_path):
    (tmp_path / "meta.yaml").write_text(
        (SAMPLE_DIR / "meta.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "pmu_digest.csv").write_text(
        "metric,scope_kind,scope_ref,value,unit,stat,freq_mhz\nip_clock_mhz,ip,X,abc,MHz,mean,\n",
        encoding="utf-8",
    )
    assert meas_import(["--meta", str(tmp_path / "meta.yaml"), "--out", str(tmp_path / "o")]) == 1
    report = json.loads((tmp_path / "o" / "meas_import_report.json").read_text(encoding="utf-8"))
    assert any(m["code"] == "pmu_digest_invalid" for m in report["messages"])


def test_meta_requires_some_input_but_accepts_pmu_alone():
    raw = yaml.safe_load((SAMPLE_DIR / "meta.yaml").read_text(encoding="utf-8"))
    assert MeasurementImportMeta.model_validate(raw).pmu is not None
    raw.pop("pmu")
    with pytest.raises(ValueError, match="'pmu'"):
        MeasurementImportMeta.model_validate(raw)


# --- comparison alignment ------------------------------------------------------------
def _measurement_doc() -> dict:
    spec = PmuSpec(file="x", ip_map=IP_MAP)
    digest = import_pmu_digest(SAMPLE_DIR / "pmu_digest.csv", spec)
    return {
        "id": "meas-x", "kind": "evidence.measurement", "project_ref": "p", "scenario_ref": "s", "variant_ref": "v",
        "execution_context": {"sw_baseline_ref": "sw", "thermal": "room", "power_state": "d"},
        "metric_observations": digest.observations,
    }


def _prediction_doc() -> dict:
    return {
        "id": "sim-x", "kind": "evidence.simulation", "project_ref": "p", "scenario_ref": "s", "variant_ref": "v",
        "execution_context": {"sw_baseline_ref": "sw", "thermal": "room", "power_state": "d"},
        "dvfs_breakdown": [
            {"node_id": "mtnr0", "ip_ref": MTNR, "set_clock_mhz": 800.0},
            {"node_id": "mtnr1", "ip_ref": MTNR, "set_clock_mhz": 600.0},
            {"node_id": "mcsc0", "ip_ref": MCSC, "set_clock_mhz": 700.0},
        ],
        "dma_breakdown": [
            {"direction": "read", "bw_mbs": 3000.0, "node_id": "a", "port": "R0"},
            {"direction": "read", "bw_mbs": 1000.0, "node_id": "b", "port": "R0"},
            {"direction": "write", "bw_mbs": 2000.0, "node_id": "a", "port": "W0"},
            {"direction": "otf", "bw_mbs": 0.0, "node_id": "c", "port": "O"},
        ],
    }


def test_prediction_and_pmu_measurement_align_on_clock_and_memory_bw():
    result = compare_prediction_measurement(_prediction_doc(), _measurement_doc())
    rows = {(r["metric_id"], r["scope_ref"]): r for r in result["rows"]}

    clock = rows[("clock.ip", MTNR)]
    assert clock["status"] == "MATCHED"
    assert (clock["prediction"], clock["measurement"]) == (800.0, 760.0)  # max over instances vs weighted mean
    assert clock["delta"] == 40.0
    assert rows[("clock.ip", MCSC)]["delta"] == pytest.approx(50.0)
    assert rows[("clock.ip_dominant", MTNR)]["status"] == "MATCHED"

    read = rows[("bandwidth.mem_read", "total")]
    assert read["status"] == "MATCHED"
    assert (read["prediction"], read["measurement"]) == (4000.0, 5200.0)  # modelled IP DMA vs all masters
    assert rows[("bandwidth.mem_write", "total")]["delta"] == -1400.0
    # CPU counters have no prediction side yet: visible as measurement-only, not dropped.
    assert rows[("cpu.ipc", "big")]["status"] == "MEASUREMENT_ONLY"


# --- measured tier of the clock ledger --------------------------------------------------
def test_measured_clocks_from_observations_by_stat():
    obs = _measurement_doc()["metric_observations"]
    mean = measured_clocks_from_observations(obs, evidence_ref="meas-x")
    assert mean[MTNR].mhz == 760.0 and mean[MTNR].stat == "weighted_mean" and mean[MTNR].evidence_ref == "meas-x"
    dominant = measured_clocks_from_observations(obs, stat="dominant")
    assert dominant[MTNR].mhz == 800.0
    assert measured_clocks_from_observations(obs, stat="max")[MTNR].mhz == 1000.0
    assert measured_clocks_from_observations([{"metric_id": "power.total"}]) == {}


class _Db:
    def __init__(self, row):
        self.row = row

    def query(self, *_):
        return self

    def filter_by(self, **_):
        return self

    def one_or_none(self):
        return self.row


def _request(**config) -> SimulateRequest:
    return SimulateRequest.model_validate(
        {
            "scenario_id": "s", "variant_id": "v",
            "execution_context": {"silicon_rev": "EVT0", "sw_baseline_ref": "sw-x", "thermal": "room"},
            "config": config,
        }
    )


def test_service_resolves_measured_clock_ref_and_drives_the_ledger():
    row = SimpleNamespace(kind="evidence.measurement", scenario_ref="s", variant_ref="v",
                          metric_observations=_measurement_doc()["metric_observations"])
    request = _request(measured_clock_ref="meas-x", clock_basis="measured")
    _apply_measured_clocks(_Db(row), request)
    assert request.config.measured_clocks[MTNR].mhz == 760.0

    workload = IPWorkload(
        node_id="mtnr0", ip_ref=MTNR, hw_name="MTNR", width=1920, height=1080, fps=30.0,
        sim_params=IPSimParams(hw_name="MTNR", ppc=0.5, unit_power_mw_mp=10.0, vdd="VDD_CAM"),
    )
    resolver = DvfsResolver(
        {}, clock_basis="measured", measured_clocks=request.config.measured_clocks,
        configured_clocks={"MTNR": ConfiguredClock(mhz=900.0, reason_code="bsp_default")},
    )
    resolved = resolver.resolve([workload])["mtnr0"]
    ledger = resolved.clock_ledger
    assert resolved.set_clock_mhz == pytest.approx(760.0)
    assert ledger.basis_used == "measured" and ledger.measured_evidence_ref == "meas-x"
    assert ledger.gap["measured_minus_configured_mhz"] == -140.0
    assert resolver.warnings == []


def test_service_rejects_missing_or_foreign_measurement():
    with pytest.raises(NotFoundError):
        _apply_measured_clocks(_Db(None), _request(measured_clock_ref="meas-x"))
    foreign = SimpleNamespace(kind="evidence.measurement", scenario_ref="other", variant_ref="v", metric_observations=[])
    with pytest.raises(UnprocessableError, match="belongs to other/v"):
        _apply_measured_clocks(_Db(foreign), _request(measured_clock_ref="meas-x"))
    empty = SimpleNamespace(kind="evidence.measurement", scenario_ref="s", variant_ref="v", metric_observations=[])
    with pytest.raises(UnprocessableError, match="no usable clock.ip"):
        _apply_measured_clocks(_Db(empty), _request(measured_clock_ref="meas-x"))
    sim = SimpleNamespace(kind="evidence.simulation", scenario_ref="s", variant_ref="v", metric_observations=[])
    with pytest.raises(NotFoundError):
        _apply_measured_clocks(_Db(sim), _request(measured_clock_ref="meas-x"))
    request = _request()
    _apply_measured_clocks(_Db(None), request)  # no ref -> no-op
    assert request.config.measured_clocks is None
