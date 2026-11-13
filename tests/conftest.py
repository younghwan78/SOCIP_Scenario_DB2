from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Unit tests run through both ".venv\\Scripts\\python.exe -m pytest" and
# "uv run pytest". Make imports deterministic for the src package and the
# Streamlit dashboard package.
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DATABASE_URL", "sqlite:///test-scenariodb.db")
os.environ.setdefault("SCENARIO_DB_MUTATION_AUTH_DISABLED", "true")
# tests patch engine functions: a shared on-disk result cache would hide those patches
os.environ.setdefault("SCENARIO_DB_COMPUTE_CACHE_DIR", "off")


@pytest.fixture(autouse=True)
def _keep_main_module():
    """Put ``sys.modules["__main__"]`` back after every test.

    Streamlit's ``AppTest`` runs a page as ``__main__`` and leaves that module in place. A later test
    in the same process that starts a ``spawn`` child (process pools, the shared budget holder) would
    have the child re-run the page file as its main module and die there, so the failure depended on
    which tests an xdist worker happened to run before it.
    """
    main = sys.modules.get("__main__")
    yield
    if sys.modules.get("__main__") is not main:
        if main is None:
            sys.modules.pop("__main__", None)
        else:
            sys.modules["__main__"] = main
