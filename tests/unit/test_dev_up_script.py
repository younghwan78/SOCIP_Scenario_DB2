"""scripts/dev_up.sh (Linux counterpart of dev_up.ps1): syntax, options and parity of the DB steps."""

from __future__ import annotations

import shutil
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
