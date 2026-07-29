from __future__ import annotations

from types import SimpleNamespace

import pytest

from scenario_db.reporting import cli
from scenario_db.reporting.reconciliation import ReconciliationFinding


class _Query:
    def filter(self, *args):
        return self

    def all(self):
        return [
            SimpleNamespace(
                artifacts=[
                    {
                        "artifact_id": "generation:simulation_report",
                        "path": "prefix/generation/report.html",
                    }
                ]
            )
        ]


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def query(self, model):
        return _Query()


def test_reconciliation_cli_reports_findings_and_disposes_engine(
    monkeypatch,
    capsys,
):
    engine = SimpleNamespace(dispose=lambda: None)
    disposed: list[bool] = []
    engine.dispose = lambda: disposed.append(True)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(database_url="sqlite://", report_dir="reports"),
    )
    monkeypatch.setattr(cli, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(cli, "Session", lambda engine_arg: _Session())

    def _reconcile(root, records, **kwargs):
        captured["root"] = root
        captured["records"] = records
        captured["kwargs"] = kwargs
        return [
            ReconciliationFinding(
                kind="missing_file",
                path="prefix/generation/report.html",
                detail="missing",
            )
        ]

    monkeypatch.setattr(cli, "reconcile_artifacts", _reconcile)

    exit_code = cli.main(["--stale-after-seconds", "30"])

    assert exit_code == 1
    assert captured["root"] == "reports"
    assert len(captured["records"]) == 1
    assert disposed == [True]
    assert '"kind": "missing_file"' in capsys.readouterr().out


def test_reconciliation_cli_rejects_negative_stale_age():
    with pytest.raises(SystemExit, match="must be non-negative"):
        cli.main(["--stale-after-seconds", "-1"])
