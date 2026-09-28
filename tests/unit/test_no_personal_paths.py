"""Shared sources must not carry personal workstation paths or personal e-mail addresses.

Kernel/DT source references are stored relative to the source-tree root
(``exynos/...``) with a sha256, never as an absolute WSL/Windows home path.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCOPE = ("authoring", "db_Exynos2600_SM-S947B", "db_Exynos2700_SM-S957B", "docs", "src", "scripts",
         "pyproject.toml", "README.md")
PATTERNS = {
    "WSL path": re.compile(r"wsl\.localhost|\\\\wsl\$|/mnt/wsl", re.I),
    "Linux home path": re.compile(r"(?<![\w.])/home/[a-z_][\w-]*/(?!\.)", re.I),
    "Windows user profile": re.compile(r"[A-Z]:[\\/]+Users[\\/]+\w+", re.I),
    "personal e-mail": re.compile(r"[\w.+-]+@(gmail|naver|daum|hanmail|outlook|hotmail|yahoo)\.(com|net)", re.I),
}


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--", *SCOPE], cwd=REPO, capture_output=True, text=True, check=True)
    return [REPO / p for p in out.stdout.splitlines()]


def test_no_personal_paths_or_emails():
    hits = []
    for path in _tracked():
        if path.suffix.lower() in {".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".db", ".pb", ".perfetto-trace"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.relative_to(REPO)}:{line}: {label}: {m.group(0)}")
    assert not hits, "\n".join(hits[:30])
