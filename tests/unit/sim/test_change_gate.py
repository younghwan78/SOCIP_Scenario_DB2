"""The change gate groups differences and fails on any E2700 change (scripts/check_change_gate.py)."""

from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from check_change_gate import E2700_FIXTURE, REPO, _e2700_cases, report, summarize  # noqa: E402


def _write(root: Path, sub: str, case: str, data: dict) -> None:
    (root / sub).mkdir(parents=True, exist_ok=True)
    (root / sub / f"{case}.json").write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _pair(tmp_path, e2600_b=None, e2700_b=None):
    a, b = tmp_path / "a", tmp_path / "b"
    base = {"input_hash": "h", "input_sections": {"pipeline": "p"}, "result": {"power": 1.0}}
    _write(a, "e2600", "v1", base)
    _write(b, "e2600", "v1", e2600_b or base)
    _write(a, "e2700", "w1", {"dma": [[1, 2]]})
    _write(b, "e2700", "w1", e2700_b or {"dma": [[1, 2]]})
    return a, b


def test_identical_dumps_pass(tmp_path, capsys):
    groups = summarize(*_pair(tmp_path))
    assert groups == {"e2600_results": {}, "e2600_input_hash": {}, "e2700": {}}
    assert report(groups, strict=True, docs_problems=[]) == 0
    assert "GATE OK" in capsys.readouterr().out


def test_e2600_differences_are_split_and_reported_not_failed(tmp_path, capsys):
    changed = {"input_hash": "h2", "input_sections": {"pipeline": "p2"}, "result": {"power": 1.5}}
    groups = summarize(*_pair(tmp_path, e2600_b=changed))
    assert groups["e2600_input_hash"] == {"v1": ["input_hash", "input_sections"]}
    assert groups["e2600_results"] == {"v1": ["result.power"]}
    assert report(groups, strict=False) == 0
    assert report(groups, strict=True) == 1


def test_any_e2700_difference_fails(tmp_path):
    groups = summarize(*_pair(tmp_path, e2700_b={"dma": [[1, 3]]}))
    assert groups["e2700"] == {"w1": ["dma"]}
    assert report(groups, strict=False) == 1


def test_a_missing_case_and_an_encoding_change_count(tmp_path):
    a, b = _pair(tmp_path)
    (b / "e2700" / "w1.json").write_text(json.dumps({"dma": [[1, 2]]}, indent=4), encoding="utf-8")
    _write(a, "e2600", "v2", {"x": 1})
    groups = summarize(a, b)
    assert groups["e2700"] == {"w1": ["<encoding>"]}
    assert groups["e2600_results"] == {"v2": ["missing from b"]}


def test_a_type_change_is_a_difference(tmp_path):
    groups = summarize(*_pair(tmp_path, e2700_b={"dma": [[1, 2.0]]}))
    assert groups["e2700"] == {"w1": ["dma"]}


def test_e2700_documents_fail_the_gate(tmp_path):
    groups = summarize(*_pair(tmp_path))
    assert report(groups, strict=False, docs_problems=["02_definition/x.yaml: changed"]) == 1


def test_every_e2700_variant_is_dumped():
    cases = _e2700_cases(REPO)
    scenarios = {s for s, _ in cases}
    assert scenarios == {p.stem for p in (REPO / E2700_FIXTURE / "02_definition").glob("uc-*.yaml")}
    assert len(cases) == len({v for _, v in cases}) >= 16
