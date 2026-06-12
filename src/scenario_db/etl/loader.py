"""ETL loader — YAML 디렉터리를 PostgreSQL로 임포트."""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from pathlib import Path

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
from scenario_db.graph_checks import find_data_flow_cycle

logger = logging.getLogger(__name__)

# kind → mapper 함수
MAPPER_REGISTRY: dict[str, callable] = {
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
) -> dict[str, int]:
    """
    디렉터리 내 모든 YAML을 kind 기준으로 적재.
    파일 단위 SAVEPOINT — 오류 파일은 skip, 나머지는 보존.
    반환: {kind: 성공 건수}
    """
    if scenario_project_collision_policy not in {"error", "replace", "skip"}:
        raise ValueError("scenario_project_collision_policy must be one of: error, replace, skip")

    previous_policy = getattr(session, "info", {}).get("scenario_project_collision_policy")
    session.info["scenario_project_collision_policy"] = scenario_project_collision_policy

    # 파일 발견 → kind별 그룹화
    by_kind: dict[str, list[tuple[Path, dict, str]]] = defaultdict(list)
    for path in sorted(directory.rglob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("YAML parse failed %s: %s", path.name, exc)
            continue
        kind = raw.get("kind") if isinstance(raw, dict) else None
        if kind and kind in MAPPER_REGISTRY:
            sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            by_kind[kind].append((path, raw, sha256))
        elif kind:
            logger.debug("no mapper for kind=%s (%s)", kind, path.name)

    counts: dict[str, int] = {}
    skipped: list[str] = []

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
                    skipped.append(f"{path.name}: {exc}")
            counts[kind] = success

        session.commit()
    finally:
        if previous_policy is None:
            session.info.pop("scenario_project_collision_policy", None)
        else:
            session.info["scenario_project_collision_policy"] = previous_policy

    total = sum(counts.values())
    logger.info("ETL complete — %d loaded, %d skipped", total, len(skipped))
    return counts


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


def main(directory: str, *, scenario_project_collision_policy: str = "error") -> None:
    """CLI 진입점: python -m scenario_db.etl.loader <directory>"""
    import os
    from scenario_db.db.base import make_engine
    from scenario_db.db.session import get_session

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(message)s",
    )
    engine = make_engine(os.environ["DATABASE_URL"])
    with get_session(engine) as session:
        counts = load_yaml_dir(
            Path(directory),
            session,
            scenario_project_collision_policy=scenario_project_collision_policy,
        )

    print("\nETL 결과:")
    for kind, n in counts.items():
        if n:
            print(f"  {kind:<30} {n:>3}건")


if __name__ == "__main__":
    import sys
    if len(sys.argv) not in {2, 3}:
        print("Usage: python -m scenario_db.etl.loader <fixtures_directory> [--replace-scenario-project-collisions|--skip-scenario-project-collisions]")
        sys.exit(1)
    policy = "error"
    if len(sys.argv) == 3:
        if sys.argv[2] == "--replace-scenario-project-collisions":
            policy = "replace"
        elif sys.argv[2] == "--skip-scenario-project-collisions":
            policy = "skip"
        else:
            print(f"Unknown option: {sys.argv[2]}")
            sys.exit(1)
    main(sys.argv[1], scenario_project_collision_policy=policy)
