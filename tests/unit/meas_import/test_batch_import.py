"""Batch import must consume only the evidence produced by the current invocation."""
import json
import shutil
import sys
from pathlib import Path

import yaml

from scripts import import_measurements


def test_batch_import_ignores_output_left_by_interrupted_run(tmp_path, monkeypatch, capsys):
    root = Path(__file__).resolve().parents[3]
    db = tmp_path / 'db'
    source = root / 'db_Exynos2700_SM-S957B/measurements/cam-rec-r1-uhd30-vdis'
    meta_dir = db / 'measurements/capture'
    shutil.copytree(source, meta_dir)
    stale = tmp_path / 'output/meas_import/db/capture/03_evidence/aaa-stale.yaml'
    stale.parent.mkdir(parents=True)
    stale.write_text('id: aaa-stale\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['import_measurements', str(db), '--strict'])
    assert import_measurements.main() == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary['result']['capture'] == 'added'
    expected = yaml.safe_load((meta_dir / 'meta.yaml').read_text(encoding='utf-8'))['id']
    assert [p.stem for p in (db / '03_evidence').glob('*.yaml')] == [expected]
    assert import_measurements.main() == 0
    assert json.loads(capsys.readouterr().out)['result']['capture'] == 'unchanged'
