"""Measurement update flow: same evidence id is replaced only with a higher provenance.revision."""
from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scenario_db.etl.mappers.evidence import upsert_measurement
from scenario_db.meas_import.cli import main as meas_import

REPO = Path(__file__).resolve().parents[3]
DB_2700 = REPO / "db_Exynos2700_SM-S957B"
SAMPLE = DB_2700 / "measurements" / "cam-rec-r1-uhd30-vdis"


def _same(a, b) -> bool:
    """Equal up to last-digit float rounding (platform-dependent summation)."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) <= max(0.0015, 1e-6 * max(abs(a), abs(b)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _import(meta: Path, out: Path) -> int:
    return meas_import(["--meta", str(meta), "--out", str(out), "--strict"])


def test_exynos2700_dummy_inputs_import_and_cover_power_bw_timing(tmp_path: Path):
    metas = sorted((DB_2700 / "measurements").glob("*/meta.yaml"))
    assert len(metas) == 16
    for meta in metas:
        m = yaml.safe_load(meta.read_text(encoding="utf-8"))
        assert m["provenance"]["device_id"] == "DUMMY" and m["project_ref"] == "proj-sm-s957b"
        assert m["execution_context"]["sw_baseline_ref"] == "sw-vendor-v1.2.3-s5e9975"   # 2700's own SW profile
        out = tmp_path / meta.parent.name
        assert _import(meta, out) == 0, meta
        (doc_path,) = (out / "03_evidence").glob("*.yaml")
        doc = yaml.safe_load(doc_path.read_text(encoding="utf-8"))
        assert doc["kpi"]["total_power_mw"]["n"] == 3 and doc["vdd_power"]
        assert doc["sw_task_timing"]
        assert any(o["metric_id"] == "bandwidth.total" for o in doc["metric_observations"])
        committed = DB_2700 / "03_evidence" / doc_path.name
        assert _same(yaml.safe_load(committed.read_text(encoding="utf-8")), doc), "03_evidence is stale: run import"


def test_changed_input_needs_a_revision_bump(tmp_path: Path):
    src = tmp_path / "m"
    shutil.copytree(SAMPLE, src)
    out = tmp_path / "out"
    assert _import(src / "meta.yaml", out) == 0
    csv = src / "rail_power_by_run.csv"
    lines = csv.read_text(encoding="utf-8").splitlines()
    head, rest = lines[1].rsplit(",", 1)
    lines[1] = f"{head},{float(rest) + 10:.4f}"
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert _import(src / "meta.yaml", out) == 1                       # conflict at revision 1
    meta = src / "meta.yaml"
    rev = yaml.safe_load(meta.read_text(encoding="utf-8"))["provenance"]["revision"]
    meta.write_text(meta.read_text(encoding="utf-8").replace(f"revision: {rev}", f"revision: {rev + 1}"),
                    encoding="utf-8")
    assert _import(meta, out) == 0
    (doc_path,) = (out / "03_evidence").glob("*.yaml")
    assert yaml.safe_load(doc_path.read_text(encoding="utf-8"))["provenance"]["revision"] == rev + 1


class _Session:
    def __init__(self, row):
        self.row = row

    def get(self, _model, _id):
        return self.row

    def add(self, row):
        self.row = row


def _doc(revision: int) -> dict:
    (path,) = (DB_2700 / "03_evidence").glob("meas-dummy-*-cam-rec-r1-uhd30-vdis-evt0.yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["provenance"]["revision"] = revision
    return doc


def test_db_replaces_fingerprinted_measurement_only_with_higher_revision():
    stored = SimpleNamespace(yaml_sha256="a" * 64, provenance=_doc(1)["provenance"])
    assert stored.provenance.get("import_fingerprint")          # SW timing present -> fingerprinted
    with pytest.raises(ValueError, match="bump provenance.revision"):
        upsert_measurement(_doc(1), "b" * 64, _Session(stored))
    session = _Session(SimpleNamespace(yaml_sha256="a" * 64, provenance=_doc(1)["provenance"]))
    upsert_measurement(_doc(2), "c" * 64, session)
    assert session.row.provenance["revision"] == 2 and session.row.yaml_sha256 == "c" * 64
