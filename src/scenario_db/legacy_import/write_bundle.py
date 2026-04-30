from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scenario_db.legacy_import.read_legacy import read_yaml


WRITE_BUNDLE_KIND = "scenario.import_bundle"
SUPPORTED_DOCUMENT_KINDS = {"soc", "ip", "project", "scenario.usecase"}
DOCUMENT_KIND_ORDER = {
    "soc": 0,
    "ip": 1,
    "project": 2,
    "scenario.usecase": 3,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a Write API scenario.import_bundle payload from generated canonical YAML.",
    )
    parser.add_argument("--generated", type=Path, required=True, help="Generated canonical YAML directory.")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON payload path.")
    parser.add_argument("--actor", default="legacy-importer", help="Write API actor field.")
    parser.add_argument("--note", default="Stage legacy importer output", help="Write API note field.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if unsupported canonical documents are found.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload, issues = build_import_bundle_request(
        args.generated,
        actor=args.actor,
        note=args.note,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    if issues:
        print(json.dumps({"ok": False, "issues": issues, "out": str(args.out)}, indent=2, ensure_ascii=True))
    else:
        print(json.dumps({"ok": True, "issues": [], "out": str(args.out)}, indent=2, ensure_ascii=True))
    return 1 if args.strict and issues else 0


def build_import_bundle_request(
    generated_dir: Path,
    *,
    actor: str = "legacy-importer",
    note: str = "Stage legacy importer output",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Build the exact request body for POST /api/v1/write/staging."""
    generated_dir = generated_dir.resolve()
    if not generated_dir.is_dir():
        raise FileNotFoundError(f"Generated canonical YAML directory not found: {generated_dir}")

    documents, issues = collect_canonical_documents(generated_dir)
    import_report = load_import_report(generated_dir, issues)
    payload = {
        "kind": WRITE_BUNDLE_KIND,
        "actor": actor,
        "note": note,
        "payload": {
            "import_report": import_report,
            "documents": documents,
        },
    }
    return payload, issues


def collect_canonical_documents(generated_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    documents: list[dict[str, Any]] = []
    issues: list[dict[str, str]] = []
    for path in sorted(_iter_yaml_files(generated_dir)):
        try:
            raw = read_yaml(path)
        except Exception as exc:  # pragma: no cover - defensive filesystem guard.
            issues.append(_issue("bundle_yaml_unreadable", f"Cannot read YAML: {exc}", path))
            continue
        if not isinstance(raw, dict):
            issues.append(_issue("bundle_yaml_not_object", "YAML root is not an object.", path))
            continue
        kind = raw.get("kind")
        if kind not in SUPPORTED_DOCUMENT_KINDS:
            issues.append(_issue("bundle_document_kind_unsupported", f"Unsupported canonical document kind: {kind}", path))
            continue
        documents.append(raw)
    documents.sort(key=lambda doc: (DOCUMENT_KIND_ORDER.get(str(doc.get("kind")), 99), str(doc.get("id"))))
    return documents, issues


def load_import_report(generated_dir: Path, issues: list[dict[str, str]]) -> dict[str, Any]:
    report_path = generated_dir / "import_report.json"
    if not report_path.exists():
        issues.append(_issue("bundle_import_report_missing", "import_report.json was not found.", report_path))
        return {
            "ok": False,
            "generated": {},
            "messages": [
                {
                    "level": "error",
                    "code": "bundle_import_report_missing",
                    "message": "import_report.json was not found.",
                    "source": str(report_path),
                }
            ],
        }
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        issues.append(_issue("bundle_import_report_invalid_json", f"import_report.json is invalid JSON: {exc}", report_path))
        return {
            "ok": False,
            "generated": {},
            "messages": [
                {
                    "level": "error",
                    "code": "bundle_import_report_invalid_json",
                    "message": f"import_report.json is invalid JSON: {exc}",
                    "source": str(report_path),
                }
            ],
        }
    if not isinstance(report, dict):
        issues.append(_issue("bundle_import_report_not_object", "import_report.json root is not an object.", report_path))
        return {"ok": False, "generated": {}, "messages": []}
    messages = list(report.get("messages") or [])
    for issue in issues:
        messages.append(
            {
                "level": "error",
                "code": issue["code"],
                "message": issue["message"],
                "source": issue["source"],
            }
        )
    report["messages"] = messages
    if issues:
        report["ok"] = False
    return report


def _iter_yaml_files(generated_dir: Path) -> list[Path]:
    return [
        path
        for pattern in ("*.yaml", "*.yml")
        for path in generated_dir.rglob(pattern)
        if path.name != "import_report.json"
    ]


def _issue(code: str, message: str, path: Path) -> dict[str, str]:
    return {"code": code, "message": message, "source": str(path)}


if __name__ == "__main__":
    raise SystemExit(main())
