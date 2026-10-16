import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


@pytest.fixture
def generator(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts'))
    return importlib.import_module('generate_rear_recording_evidence')


@pytest.mark.parametrize('doc', [
    {'resolution_result': {'overall_feasibility': 'infeasible'}},
    {'calculation_trace': {'rear_gapfill_verification': {'accepted': False}}},
])
def test_rerun_does_not_generate_measurement_for_persisted_failure(generator, monkeypatch, doc):
    monkeypatch.setattr(sys, 'argv', ['generate'])
    monkeypatch.setattr(generator, 'read', lambda _: {'variants': [{'id': 'v'}]})
    monkeypatch.setattr(generator, 'load_catalog', lambda: {})
    monkeypatch.setattr(generator, 'existing_evidence', lambda: {'v': {'simulation'}})
    monkeypatch.setattr(generator, 'graph_from_fixture', lambda *args: SimpleNamespace(
        variant=SimpleNamespace(design_conditions={'sensor_place': 'rear'})))
    monkeypatch.setattr(generator, 'find_sim', lambda _: doc)
    monkeypatch.setattr(generator, 'synth_measurement', lambda *args: pytest.fail('failed sim must not generate measurement'))
    assert generator.main() == 0


def test_generation_error_returns_failure(generator, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['generate'])
    monkeypatch.setattr(generator, 'read', lambda _: {'variants': [{'id': 'v'}]})
    monkeypatch.setattr(generator, 'load_catalog', lambda: {})
    monkeypatch.setattr(generator, 'existing_evidence', lambda: {})
    monkeypatch.setattr(generator, 'graph_from_fixture', lambda *args: SimpleNamespace(
        variant=SimpleNamespace(design_conditions={'sensor_place': 'rear'})))
    def fail(_):
        raise ValueError('bad input')
    monkeypatch.setattr(generator, 'find_sim', fail)
    assert generator.main() == 1


def test_committed_synthetic_measurements_have_provenance_and_valid_totals(generator):
    paths = list(generator.EVIDENCE.glob('meas-synth-*-20260925.yaml'))
    assert len(paths) == 33
    for path in paths:
        doc = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.CSafeLoader)
        generator.MeasurementEvidence.model_validate(doc)
        assert doc['provenance']['device_id'] == 'SYNTHETIC'
        assert doc['provenance']['collection_method'] == 'synthetic_fixture'
        assert doc['project_ref'] == 'proj-sm-s947b' and doc['scenario_ref'] == generator.SCENARIO
        assert doc['kpi']['total_power_mw']['mean'] == pytest.approx(sum(r['power_mw'] for r in doc['vdd_power'].values()), abs=.002)
        assert len(doc['derived_from']) == 2
        frames = doc['kpi']['frame_latency_ms']['n']
        assert frames == round(doc['kpi']['fps_effective'] / .999) * 90
        assert all(t['samples'] == frames for t in doc.get('sw_task_timing', []))
        for source in doc['derived_from']:
            assert (generator.EVIDENCE / f'{source}.yaml').exists()


def test_find_sim_uses_timestamp_not_file_name(generator, monkeypatch, tmp_path):
    monkeypatch.setattr(generator, 'EVIDENCE', tmp_path)
    for name, year in [('sim-z', 2024), ('sim-a', 2026)]:
        (tmp_path / f'{name}.yaml').write_text(yaml.safe_dump({
            'id': name, 'kind': 'evidence.simulation', 'scenario_ref': generator.SCENARIO,
            'variant_ref': 'v', 'run_info': {'timestamp': f'{year}-01-01T00:00:00Z'},
        }), encoding='utf-8')
    assert generator.find_sim('v')['id'] == 'sim-a'


def test_all_variant_gapfill_covers_every_recording_variant(generator):
    raw = generator.read(generator.FIXTURE / '02_definition' / f'{generator.SCENARIO}.yaml')
    have = generator.existing_evidence()
    missing = [v['id'] for v in raw['variants'] if 'measurement' not in have.get(v['id'], set())]
    assert missing == []
    paths = list(generator.EVIDENCE.glob('meas-synth-*-20261016.yaml'))
    assert len(paths) == 40
    for path in paths:
        doc = yaml.load(path.read_text(encoding='utf-8'), Loader=yaml.CSafeLoader)
        generator.MeasurementEvidence.model_validate(doc)
        assert doc['provenance']['device_id'] == 'SYNTHETIC'
        assert doc['provenance']['collection_method'] == 'synthetic_fixture'
        assert doc['kpi']['total_power_mw']['mean'] == pytest.approx(sum(r['power_mw'] for r in doc['vdd_power'].values()), abs=.002)
        for source in doc['derived_from']:
            assert (generator.EVIDENCE / f'{source}.yaml').exists()
        drops = [e for e in doc['timeline_events'] if e['type'] == 'frame_drop']
        sim = generator.read(generator.EVIDENCE / f"{doc['derived_from'][1]}.yaml")
        # an infeasible model is captured as a reduced cadence, a feasible one at target fps
        assert bool(drops) == (generator.simulation_failed(sim) and doc['kpi']['fps_effective'] < 0.99 * doc['kpi']['frame_latency_ms']['n'] / 90)


def test_infeasible_simulation_scales_cadence_and_ip_bw_power(generator, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['generate'])
    ref = generator.read(generator.EVIDENCE / f'{generator.REF_MEAS}.yaml')
    ref_sim = generator.read(generator.EVIDENCE / f'{generator.REF_SIM}.yaml')
    sim = generator.read(generator.EVIDENCE / 'sim-rear-cam-rec-r1-fhd960-ssm-mean-20260925.yaml')
    raw = generator.read(generator.FIXTURE / '02_definition' / f'{generator.SCENARIO}.yaml')
    generator.load_catalog.cache = generator.load_catalog()
    graph = generator.graph_from_fixture(raw, 'cam-rec-r1-fhd960-ssm', generator.load_catalog.cache)
    full = generator.synth_measurement(raw, 'cam-rec-r1-fhd960-ssm', graph, sim, ref, ref_sim)
    capped = generator.synth_measurement(raw, 'cam-rec-r1-fhd960-ssm', graph, sim, ref, ref_sim, infeasible=True)
    assert capped['kpi']['fps_effective'] == pytest.approx(120 * .999, abs=.01)
    assert capped['kpi']['total_power_mw']['mean'] < full['kpi']['total_power_mw']['mean'] / 3
    assert any(e['type'] == 'frame_drop' for e in capped['timeline_events'])
