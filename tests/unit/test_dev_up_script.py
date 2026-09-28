"""scripts/dev_up.sh (Linux counterpart of dev_up.ps1): syntax, options and parity of the DB steps."""

from __future__ import annotations

import shutil
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SH = REPO / "scripts" / "dev_up.sh"
PS1 = REPO / "scripts" / "dev_up.ps1"

pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="bash required")


def test_syntax_and_help():
    for script in (SH, REPO / "scripts" / "dev_down.sh"):
        assert subprocess.run(["bash", "-n", str(script)], capture_output=True).returncode == 0
    out = subprocess.run(["bash", str(SH), "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "--no-docker" in out.stdout
    bad = subprocess.run(["bash", str(SH), "--nope"], capture_output=True, text=True)
    assert bad.returncode == 2 and "unknown option" in bad.stderr


def test_same_db_steps_as_powershell():
    sh, ps = SH.read_text(encoding="utf-8"), PS1.read_text(encoding="utf-8")
    for step in ("alembic", "upgrade", "head", "scenario_db.etl.rename_ids", "scenario_db.etl.retire",
                 "scenario_db.etl.loader", "db_Exynos2600_SM-S947B", "scenario_db.authoring", "--prune",
                 "import_measurements.py", "sm-s957b", "db_Exynos2700_SM-S957B"):
        assert step in ps and step in sh, step
    body = sh[sh.index("set -euo pipefail"):]   # skip the header comment
    order = [body.index(s) for s in ("alembic upgrade head", "etl.rename_ids", "etl.retire",
                                   "etl.loader db_Exynos2600_SM-S947B", "authoring sync")]
    assert order == sorted(order)


@pytest.fixture
def sandbox(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("dev_up.sh", "dev_down.sh"):
        shutil.copyfile(REPO / "scripts" / name, scripts / name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(
        '#!/usr/bin/env bash\nset -eu\n'
        f'if [[ "$1 $2" == "run python" ]]; then shift 2; exec {shlex.quote(sys.executable)} "$@"; fi\n'
        'echo "$*" >> "$CALL_LOG"\n'
        'if [[ "$*" == *uvicorn* ]]; then exec sleep 60; fi\n',
        encoding="utf-8",
    )
    uv.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SCENARIO_DB_") and k != "DATABASE_URL"}
    env.update(PATH=f"{bin_dir}:{env['PATH']}", PYTHONPATH=str(REPO / "src"), CALL_LOG=str(tmp_path / "calls"))
    return tmp_path, env


@pytest.mark.parametrize("value", ['"true"', "1", "yes"])
def test_external_auth_bypass_is_rejected_before_database_changes(sandbox, value):
    root, env = sandbox
    (root / ".env").write_text(
        f'DATABASE_URL=postgresql://user:secret@localhost/db\nSCENARIO_DB_MUTATION_AUTH_DISABLED={value}\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", str(root / "scripts/dev_up.sh"), "--no-docker", "--bind", "0.0.0.0"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "authentication disabled" in result.stderr
    assert not (root / "calls").exists()
    assert "secret" not in result.stdout + result.stderr


def test_stale_pid_does_not_stop_unrelated_process_and_restart_is_tracked(sandbox):
    root, env = sandbox
    env["DATABASE_URL"] = "postgresql://user:secret@localhost/db"
    pid_dir = root / "output/dev"
    pid_dir.mkdir(parents=True)
    with subprocess.Popen(["sleep", "60"], start_new_session=True) as unrelated:
        try:
            (pid_dir / "api.pid").write_text(f"{unrelated.pid}\nstale start time\n", encoding="utf-8")
            subprocess.run(["bash", str(root / "scripts/dev_down.sh")], env=env, check=True, timeout=10)
            assert unrelated.poll() is None
            (pid_dir / "api.pid").write_text("99999999\nstale start time\n", encoding="utf-8")
            subprocess.run(
                ["bash", str(root / "scripts/dev_up.sh"), "--no-docker", "--skip-load", "--no-ui"],
                env=env, check=True, timeout=20,
            )
            lines = (pid_dir / "api.pid").read_text().splitlines()
            assert len(lines) == 2 and lines[0] != "99999999" and lines[1].strip()
        finally:
            subprocess.run(["bash", str(root / "scripts/dev_down.sh")], env=env, timeout=10)
            unrelated.terminate()
