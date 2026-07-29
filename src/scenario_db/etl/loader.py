"""ETL loader — YAML 디렉터리를 PostgreSQL로 임포트."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from scenario_db.etl.mappers.capability import (
    upsert_ip,
    upsert_soc,
    upsert_soc_cdgm_profile,
    upsert_soc_dvfs_table,
    upsert_sw_component,
    upsert_sw_profile,
)
from scenario_db.etl.mappers.decision import (
    upsert_gate_rule,
    upsert_issue,
    upsert_review,
    upsert_waiver,
)
from scenario_db.etl.mappers.definition import upsert_project, upsert_usecase
from scenario_db.etl.mappers.evidence import upsert_measurement, upsert_simulation
from scenario_db.etl.validate_loaded import ValidationReport, validate_loaded_db
from scenario_db.graph_checks import find_data_flow_cycle

logger = logging.getLogger(__name__)

Mapper = Callable[[dict[str, Any], str, Session], None]


@dataclass(slots=True)
class LoadIssue:
    path: str
    kind: str | None
    message: str
    code: str = "load_failed"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "path": self.path,
            "kind": self.kind,
            "message": self.message,
        }


@dataclass(slots=True)
class LoadResult:
    counts: dict[str, int] = field(default_factory=dict)
    skipped: list[LoadIssue] = field(default_factory=list)
    validation: ValidationReport = field(default_factory=ValidationReport)

    @property
    def ok(self) -> bool:
        return not self.skipped and self.validation.ok

    def error_messages(self) -> list[str]:
        messages = [issue.message for issue in self.skipped]
        messages.extend(self.validation.errors)
        return messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": self.counts,
            "skipped": [issue.to_dict() for issue in self.skipped],
            "validation": {
                "ok": self.validation.ok,
                "errors": list(self.validation.errors),
                "warnings": list(self.validation.warnings),
            },
        }


class LoaderValidationError(RuntimeError):
    def __init__(self, result: LoadResult):
        self.result = result
        messages = result.error_messages()
        super().__init__("; ".join(messages) if messages else "ETL validation failed")

# kind → mapper 함수
MAPPER_REGISTRY: dict[str, Mapper] = {
    "soc":                    upsert_soc,
    "soc.dvfs_table":         upsert_soc_dvfs_table,
    "soc.cdgm_profile":       upsert_soc_cdgm_profile,
    "ip":                     upsert_ip,
    "sw_profile":             upsert_sw_profile,
    "sw_component":           upsert_sw_component,
    "project":                upsert_project,
    "scenario.usecase":       upsert_usecase,
    "evidence.simulation":    upsert_simulation,
    "evidence.measurement":   upsert_measurement,
    "decision.gate_rule":     upsert_gate_rule,
    "decision.issue":         upsert_issue,
    "decision.waiver":        upsert_waiver,
    "decision.review":        upsert_review,
}

# FK 의존 순서
LOAD_ORDER = [
    "soc",
    "soc.dvfs_table",
    "soc.cdgm_profile",
    "ip",
    "sw_profile",
    "sw_component",
    "project",
    "scenario.usecase",
    "evidence.simulation",
    "evidence.measurement",
    "decision.gate_rule",   # rule-* 먼저 — review.auto_checks FK
    "decision.issue",
    "decision.waiver",
    "decision.review",
]


def load_yaml_dir(
    directory: Path,
    session: Session,
    *,
    scenario_project_collision_policy: str = "error",
    validate: bool = False,
    strict: bool = False,
) -> LoadResult:
    """
    디렉터리 내 모든 YAML을 kind 기준으로 적재.
    파일 단위 SAVEPOINT — 오류 파일은 skip, 나머지는 보존.
    반환: LoadResult(counts, skipped, validation)
    """
    if scenario_project_collision_policy not in {"error", "replace", "skip"}:
        raise ValueError("scenario_project_collision_policy must be one of: error, replace, skip")

    previous_policy = getattr(session, "info", {}).get("scenario_project_collision_policy")
    session.info["scenario_project_collision_policy"] = scenario_project_collision_policy

    # 파일 발견 → kind별 그룹화
    by_kind: dict[str, list[tuple[Path, dict, str]]] = defaultdict(list)
    skipped: list[LoadIssue] = []
    for path in _iter_yaml_files(directory):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("YAML parse failed %s: %s", path.name, exc)
            skipped.append(LoadIssue(str(path), None, str(exc), code="yaml_parse_failed"))
            continue
        kind = raw.get("kind") if isinstance(raw, dict) else None
        if kind and kind in MAPPER_REGISTRY:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            by_kind[kind].append((path, raw, sha256))
        elif kind:
            message = f"Unsupported YAML kind: {kind}"
            logger.warning("%s (%s)", message, path.name)
            skipped.append(
                LoadIssue(
                    str(path),
                    str(kind),
                    message,
                    code="unsupported_kind",
                )
            )
        else:
            message = (
                "YAML document root must be an object with a non-empty kind"
            )
            logger.warning("%s (%s)", message, path.name)
            skipped.append(
                LoadIssue(
                    str(path),
                    None,
                    message,
                    code="missing_kind",
                )
            )

    counts: dict[str, int] = {}
    validation = ValidationReport()

    try:
        for kind in LOAD_ORDER:
            success = 0
            for path, raw, sha256 in by_kind.get(kind, []):
                try:
                    with session.begin_nested():          # PostgreSQL SAVEPOINT
                        _validate_raw_document(kind, raw)
                        MAPPER_REGISTRY[kind](raw, sha256, session)
                    success += 1
                except Exception as exc:
                    logger.error("skip %-45s [%s] %s", path.name, kind, exc)
                    skipped.append(LoadIssue(str(path), kind, str(exc)))
            counts[kind] = success

        if validate:
            validation = validate_loaded_db(session)
        result = LoadResult(counts=counts, skipped=skipped, validation=validation)
        if strict and not result.ok:
            session.rollback()
            raise LoaderValidationError(result)
        session.commit()
    finally:
        if previous_policy is None:
            session.info.pop("scenario_project_collision_policy", None)
        else:
            session.info["scenario_project_collision_policy"] = previous_policy

    total = sum(counts.values())
    logger.info("ETL complete — %d loaded, %d skipped", total, len(skipped))
    return LoadResult(counts=counts, skipped=skipped, validation=validation)


def _iter_yaml_files(directory: Path) -> list[Path]:
    return sorted({
        path
        for pattern in ("*.yaml", "*.yml")
        for path in directory.rglob(pattern)
    })


def _validate_raw_document(kind: str, raw: dict) -> None:
    if kind != "scenario.usecase":
        return
    pipeline = raw.get("pipeline") or {}
    cycle = find_data_flow_cycle(pipeline.get("nodes") or [], pipeline.get("edges") or [])
    if cycle:
        raise ValueError(
            "scenario.usecase pipeline has a data-flow cycle: "
            f"{' -> '.join(cycle)}. Use type: control for feedback paths."
        )


def main(
    directory: str,
    *,
    scenario_project_collision_policy: str = "error",
    validate: bool = True,
    strict: bool = False,
    report_json: Path | None = None,
) -> int:
    """CLI 진입점: python -m scenario_db.etl.loader <directory>"""
    from scenario_db.db.base import make_engine
    from scenario_db.db.session import get_session

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s",
    )
    result: LoadResult
    try:
        engine = make_engine()
        with get_session(engine) as session:
            result = load_yaml_dir(
                Path(directory),
                session,
                scenario_project_collision_policy=scenario_project_collision_policy,
                validate=validate,
                strict=strict,
            )
    except LoaderValidationError as exc:
        result = exc.result
        if report_json is not None:
            _write_report(report_json, result)
        _print_result(result)
        return 1

    if report_json is not None:
        _write_report(report_json, result)
    _print_result(result)
    return 0 if result.ok or not strict else 1


def _print_result(result: LoadResult) -> None:
    print("\nETL 결과:")
    for kind, n in result.counts.items():
        if n:
            print(f"  {kind:<30} {n:>3}건")
    if result.skipped:
        print("\nSkipped:")
        for issue in result.skipped:
            print(f"  {issue.path}: {issue.message}")
    if result.validation.errors:
        print("\nValidation errors:")
        for message in result.validation.errors:
            print(f"  {message}")
    if result.validation.warnings:
        print("\nValidation warnings:")
        for message in result.validation.warnings:
            print(f"  {message}")


def _write_report(path: Path, result: LoadResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load canonical ScenarioDB YAML into PostgreSQL.")
    parser.add_argument("directory", help="Fixtures/canonical YAML directory.")
    collision = parser.add_mutually_exclusive_group()
    collision.add_argument("--replace-scenario-project-collisions", action="store_true")
    collision.add_argument("--skip-scenario-project-collisions", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Rollback and exit non-zero on skipped files or validation errors.")
    parser.add_argument("--no-validate", action="store_true", help="Skip post-load referential validation.")
    parser.add_argument("--report-json", type=Path, help="Write structured ETL report JSON.")
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    policy = "error"
    if args.replace_scenario_project_collisions:
        policy = "replace"
    elif args.skip_scenario_project_collisions:
        policy = "skip"
    raise SystemExit(
        main(
            args.directory,
            scenario_project_collision_policy=policy,
            validate=not args.no_validate,
            strict=args.strict,
            report_json=args.report_json,
        )
    )
