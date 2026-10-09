from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scenario_db.api.services import cpu
from scenario_db.exceptions import UnprocessableError


@pytest.mark.parametrize("scenario,variant", [("other", "v"), ("s", "other"), ("s", None)])
def test_explicit_profile_rejects_unrelated_evidence(monkeypatch, scenario, variant):
    row = SimpleNamespace(kind="evidence.measurement", scenario_ref=scenario, variant_ref=variant)
    monkeypatch.setattr(cpu, "get_evidence", lambda db, ref: row)
    with pytest.raises(UnprocessableError, match="does not belong"):
        cpu.resolve_cpu_profile(MagicMock(), "s", "v", "measurement")


@pytest.mark.parametrize("variant", ["v", None])
def test_explicit_profile_accepts_matching_scope(monkeypatch, variant):
    row = SimpleNamespace(id="measurement", kind="evidence.measurement", scenario_ref="s", variant_ref=variant)
    profile = SimpleNamespace(tasks=["task"])
    monkeypatch.setattr(cpu, "get_evidence", lambda db, ref: row)
    monkeypatch.setattr(cpu, "cpu_profile_from_evidence", lambda row, **kw: profile)
    assert cpu.resolve_cpu_profile(MagicMock(), "s", variant, "measurement") == (profile, "measurement")
