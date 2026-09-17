from pathlib import Path
import json
from urllib.error import HTTPError
import pytest
from scenario_db.meas_import import camera_api
from scenario_db.meas_import.camera import main, parse_markdown, assemble_camera

EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "examples/measurement-import/camera/scenario-statistics.md"
)


def test_commit_cli_previews_then_commits_without_output(monkeypatch, capsys):
    calls = []
    monkeypatch.setenv("SCENARIODB_API_KEY_ID", "writer")
    monkeypatch.setenv("SCENARIODB_API_KEY", "unit-test-secret")

    def post(url, payload, headers):
        calls.append((url, payload, headers))
        if url.endswith("/preview"):
            return {"sha256": "a" * 64}
        return {
            "id": payload["evidence"]["id"],
            "sha256": payload["expected_hash"],
            "status": "created",
        }

    monkeypatch.setattr(camera_api, "_post_json", post)
    assert (
        main(
            ["--markdown", str(EXAMPLE), "--commit", "--api-base", "http://localhost:18000/api/v1/"]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["persisted"] and result["status"] == "created"
    assert len(calls) == 2 and calls[0][0].endswith("/preview") and calls[1][0].endswith("/commit")
    assert calls[1][1]["expected_hash"] == "a" * 64
    assert calls[0][2]["X-ScenarioDB-API-Key"] == "unit-test-secret"


def test_export_only_never_calls_api(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        camera_api, "_post_json", lambda *a: pytest.fail("export must not call API")
    )
    out = tmp_path / "capture.yaml"
    assert main(["--markdown", str(EXAMPLE), "--out", str(out)]) == 0
    assert not json.loads(capsys.readouterr().out)["persisted"] and out.exists()


@pytest.mark.parametrize("failure", ["preview", "hash", "commit", "credentials"])
def test_failed_commit_is_nonzero_and_never_reports_success(monkeypatch, capsys, tmp_path, failure):
    monkeypatch.delenv("SCENARIODB_API_KEY_ID", raising=False)
    monkeypatch.delenv("SCENARIODB_API_KEY", raising=False)
    if failure == "credentials":
        monkeypatch.setenv("SCENARIODB_API_KEY_ID", "writer")
    calls = []

    def post(url, payload, headers):
        calls.append(url)
        if failure == "preview" or url.endswith("/commit"):
            raise RuntimeError("request failed")
        return {"sha256": "invalid" if failure == "hash" else "a" * 64}

    monkeypatch.setattr(camera_api, "_post_json", post)
    out = tmp_path / "capture.yaml"
    assert main(["--markdown", str(EXAMPLE), "--out", str(out), "--commit"]) == 1
    printed = capsys.readouterr()
    assert printed.out == "" and printed.err and out.exists()
    assert len(calls) == ({"preview": 1, "hash": 1, "commit": 2, "credentials": 0}[failure])


def test_http_failure_redacts_server_body(monkeypatch):
    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError("http://localhost", 403, "secret", {}, None)

    monkeypatch.setattr(camera_api, "build_opener", lambda *a: Opener())
    with pytest.raises(RuntimeError, match="HTTP 403") as exc:
        camera_api._post_json("http://localhost", {}, {})
    assert "secret" not in str(exc.value)


def test_output_required_without_commit():
    with pytest.raises(SystemExit) as exc:
        main(["--markdown", str(EXAMPLE)])
    assert exc.value.code == 2


def test_commit_rejects_url_credentials_before_sending(monkeypatch):
    monkeypatch.setattr(camera_api, "_post_json", lambda *a: pytest.fail("must not call"))
    evidence = assemble_camera(parse_markdown(EXAMPLE.read_text(encoding="utf-8")))
    with pytest.raises(ValueError):
        camera_api.commit_via_api(evidence, "http://user:secret@localhost/api/v1")
