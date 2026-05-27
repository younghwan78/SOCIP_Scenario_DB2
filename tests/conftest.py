from __future__ import annotations

import os
import sys
from pathlib import Path

# Unit tests run through both ".venv\\Scripts\\python.exe -m pytest" and
# "uv run pytest". Make imports deterministic for the src package and the
# Streamlit dashboard package.
ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DATABASE_URL", "sqlite:///test-scenariodb.db")
