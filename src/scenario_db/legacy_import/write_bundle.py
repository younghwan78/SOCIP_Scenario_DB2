from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scenario_db.legacy_import.read_legacy import read_yaml


WRITE_BUNDLE_KIND = "scenario.import_bundle"
SUPPORTED_DOCUMENT_KINDS = {
    "soc",
    "soc.dvfs_table",
    "soc.cdgm_profile",
    "ip",
    "sw_profile",
    "project",
    "scenario.usecase",
}
DOCUMENT_KIND_ORDER = {
    "soc": 0,
    "soc.dvfs_table": 1,
    "soc.cdgm_profile": 2,
    "ip": 3,
    "sw_profile": 4,
    "project": 5,
    "scenario.usecase": 6,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a Write API scenario.import_bundle payload from generated canonical YAML.",
    )
    parser.add_argument("--generated", type=Path, help="Generated canonical YAML directory.")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON payload path.")
    parser.add_argument("--actor", default="legacy-importer", help="Write API actor field.")
    parser.add_argument("--note", default="Stage legacy importer output", help="Write API note field.")
    parser.add_argument("--soc-ref", help="Build a single soc.dvfs_table bundle for this SoC.")
    parser.add_argument("--dvfs-version", type=int, help="SoC-scoped DVFS table version.")
    parser.add_argument("--evt-hint", help="EVT revision hint stored as DVFS table metadata.")
    parser.add_argument("--domains-json", type=Path, help="JSON file containing the DVFS domains object.")
    parser.add_argument("--guide-name", help="DVFS guide name, e.g. camera_dvfs_guide.")
    parser.add_argument("--source-revision", help="Source guide revision.")
    parser.add_argument("--source-path", help="Source file path or URI.")
    parser.add_argument("--source-note", help="Source note.")
    parser.add_argument("--source-project-ref", help="Project ref when the table is project-scoped.")
    parser.add_argument("--domain-schema-hash", help="Hash for the voltage-domain schema used by this table.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if unsupported canonical documents are found.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.soc_ref or args.dvfs_version is not None or args.domains_json:
        if not args.soc_ref or args.dvfs_version is None or not args.domains_json:
            parser.error("--soc-ref, --dvfs-version, and --domains-json are required for DVFS table mode")
        payload = build_soc_dvfs_table_bundle_request(
            soc_ref=args.soc_ref,
            dvfs_version=args.dvfs_version,
            domains=_read_json_object(args.domains_json),
            actor=args.actor,
            note=args.note,
            evt_hint=args.evt_hint,
            guide_name=args.guide_name,
            source_revision=args.source_revision,
            source_path=args.source_path,
            source_note=args.source_note,
            source_project_ref=args.source_project_ref,
            domain_schema_hash=args.domain_schema_hash,
        )
        issues: list[dict[str, str]] = []
    else:
        if args.generated is None:
            parser.error("--generated is required unless DVFS table mode is used")
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


def build_soc_dvfs_table_bundle_request(
    *,
    soc_ref: str,
    dvfs_version: int,
    domains: dict[str, Any],
    actor: str | None = None,
    note: str | None = None,
    table_id: str | None = None,
    schema_version: str = "2.3",
    evt_hint: str | None = None,
    guide_name: str | None = None,
    source_revision: str | None = None,
    source_path: str | None = None,
    source_note: str | None = None,
    source_project_ref: str | None = None,
    domain_schema_hash: str | None = None,
) -> dict[str, Any]:
    if dvfs_version < 0:
        raise ValueError("dvfs_version must be non-negative")
    document: dict[str, Any] = {
        "id": table_id or f"dvfs-{soc_ref}-v{dvfs_version}",
        "schema_version": schema_version,
        "kind": "soc.dvfs_table",
        "soc_ref": soc_ref,
        "dvfs_version": dvfs_version,
        "domains": domains,
        "compatibility_scope": "soc",
    }
    if evt_hint:
        document["evt_hint"] = evt_hint
    source = _clean_dict(
        {
            "guide_name": guide_name,
            "source_revision": source_revision,
            "path": source_path,
            "note": source_note,
        }
    )
    if source:
        document["source"] = source
    if source_project_ref:
        document["source_project_ref"] = source_project_ref
        document["compatibility_scope"] = "project"
    if domain_schema_hash:
        document["domain_schema_hash"] = domain_schema_hash

    return {
        "kind": WRITE_BUNDLE_KIND,
        "actor": actor,
        "note": note,
        "payload": {
            "import_report": {
                "ok": True,
                "generated": {"soc.dvfs_table": 1},
                "messages": [],
            },
            "documents": [document],
        },
    }


def build_soc_cdgm_profile_bundle_request(
    document: dict[str, Any],
    *,
    actor: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if document.get("kind") != "soc.cdgm_profile":
        raise ValueError("CDGM profile import requires a soc.cdgm_profile document.")
    return {
        "kind": WRITE_BUNDLE_KIND,
        "actor": actor,
        "note": note,
        "payload": {
            "import_report": {
                "ok": True,
                "generated": {"soc.cdgm_profile": 1},
                "messages": [],
            },
            "documents": [document],
        },
    }


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


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _clean_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "")}


if __name__ == "__main__":
    raise SystemExit(main())
