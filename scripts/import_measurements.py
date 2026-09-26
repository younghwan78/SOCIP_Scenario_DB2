"""Import every measurement input of a DB folder into its 03_evidence (idempotent).

    python scripts/import_measurements.py db_Exynos2700_SM-S957B [--strict]

For each <db>/measurements/<name>/meta.yaml runs scenario_db.meas_import.cli and writes
<db>/03_evidence/<evidence id>.yaml. Unchanged inputs leave the file untouched; a changed
input needs a higher provenance.revision (otherwise the import reports a conflict).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

import yaml

from scenario_db.meas_import.cli import main as meas_import


def _same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(0.0015, 1e-6 * max(abs(a), abs(b)))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    metas = sorted((args.db / "measurements").glob("*/meta.yaml"))
    work = Path("output") / "meas_import" / args.db.name
    summary, failed = {}, 0
    for meta in metas:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = meas_import(["--meta", str(meta), "--out", str(work / meta.parent.name), "--strict"])
        report = json.loads(buf.getvalue() or "{}")
        emitted = sorted((work / meta.parent.name / "03_evidence").glob("*.yaml"))
        status = "error"
        if rc == 0 and emitted:
            src = emitted[0]
            dst = args.db / "03_evidence" / src.name
            new = src.read_bytes()
            old = yaml.safe_load(dst.read_text(encoding="utf-8")) if dst.exists() else None
            if old is not None and (dst.read_bytes() == new or _same(old, yaml.safe_load(new))):
                status = "unchanged"   # identical up to last-digit float rounding across platforms
            else:
                rev = lambda d: int(((d or {}).get("provenance") or {}).get("revision") or 1)  # noqa: E731
                if old is not None and rev(yaml.safe_load(new)) <= rev(old):
                    status = f"conflict: {dst.name} changed at revision {rev(old)}; bump provenance.revision"
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(new)
                    status = "updated" if old is not None else "added"
        else:
            errs = [m["message"] for m in report.get("messages", []) if m.get("level") == "error"]
            status = "error: " + "; ".join(errs[:2])
        failed += status.startswith(("error", "conflict"))
        summary[meta.parent.name] = status
        for f in emitted:
            f.unlink()
    print(json.dumps({"db": str(args.db), "inputs": len(metas), "failed": failed, "result": summary},
                     indent=2, ensure_ascii=False))
    return 1 if failed and args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
