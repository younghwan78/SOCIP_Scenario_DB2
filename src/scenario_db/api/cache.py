from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from scenario_db.api.schemas.decision import GateRuleResponse, IssueResponse
from scenario_db.db.models.decision import GateRule, Issue

if TYPE_CHECKING:
    from scenario_db.matcher.context import MatcherContext

logger = logging.getLogger(__name__)


@dataclass
class RuleCache:
    issues: list[IssueResponse] = field(default_factory=list)
    gate_rules: list[GateRuleResponse] = field(default_factory=list)
    loaded: bool = False
    load_error: str | None = None

    @classmethod
    def load(cls, session: Session) -> "RuleCache":
        """Load all Issue + GateRule rows and convert to Pydantic models (avoids DetachedInstanceError)."""
        issues = [IssueResponse.model_validate(r) for r in session.query(Issue).all()]
        gate_rules = [GateRuleResponse.model_validate(r) for r in session.query(GateRule).all()]
        return cls(issues=issues, gate_rules=gate_rules, loaded=True)

    @classmethod
    def load_with_retry(cls, session_factory, max_retries: int = 3) -> "RuleCache":
        """3회 재시도 (exponential backoff: 1s, 2s, 4s). 실패해도 빈 캐시로 서버 시작."""
        for attempt in range(max_retries):
            try:
                session = session_factory()
                try:
                    cache = cls.load(session)
                    logger.info(
                        "RuleCache loaded: %d issues, %d gate_rules",
                        len(cache.issues), len(cache.gate_rules),
                    )
                    return cache
                finally:
                    session.close()
            except Exception as exc:
                wait = 2 ** attempt
                logger.warning(
                    "RuleCache load attempt %d/%d failed: %s — retry in %ds",
                    attempt + 1, max_retries, exc, wait,
                )
                if attempt < max_retries - 1:
                    time.sleep(wait)
                else:
                    logger.error(
                        "RuleCache load failed after %d attempts — starting with empty cache",
                        max_retries,
                    )
                    return cls(loaded=False, load_error=str(exc))
        return cls(loaded=False)  # unreachable, but satisfies type checker

    def invalidate_issues(self, session: Session) -> None:
        self.issues = [IssueResponse.model_validate(r) for r in session.query(Issue).all()]
        self.loaded = True

    def invalidate_gate_rules(self, session: Session) -> None:
        self.gate_rules = [GateRuleResponse.model_validate(r) for r in session.query(GateRule).all()]
        self.loaded = True

    def invalidate_all(self, session: Session) -> None:
        refreshed = type(self).load(session)
        self.issues = refreshed.issues
        self.gate_rules = refreshed.gate_rules
        self.loaded = refreshed.loaded
        self.load_error = refreshed.load_error


# ---------------------------------------------------------------------------
# Variant matching helpers (Week 4: @lru_cache 추가 예정)
# ---------------------------------------------------------------------------

def variant_hash(
    design_conditions: dict | None,
    ip_requirements: dict | None,
    sw_requirements: dict | None,
) -> str:
    """결정론적 SHA256 해시 — Week 4 lru_cache 키로 사용."""
    payload = {
        "dc": design_conditions,
        "ip": ip_requirements,
        "sw": sw_requirements,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


# TODO Week 4: @lru_cache(maxsize=512) 추가
def match_issues_for_variant(
    ctx: "MatcherContext",  # type: ignore[name-defined]
    issues: list[IssueResponse],
    scenario_id: str | None = None,
    evaluation_errors: list[str] | None = None,
) -> list[IssueResponse]:
    """
    Issue.affects (list[{scenario_ref, match_rule}]) 를 variant context에 평가.

    affects 구조:
        [{"scenario_ref": "uc-camera-recording", "match_rule": {"all": [...], "any": [...]}}, ...]

    scenario_id가 주어지면 scenario_ref 불일치 항목은 건너뜀 ("*" 와일드카드 허용).
    잘못된 match_rule은 issue 단위로 격리한다 — 평가에 실패한 issue id는
    evaluation_errors(전달 시)에 수집되며 나머지 issue 평가는 계속된다.
    """
    from scenario_db.matcher.runner import evaluate

    matched = []
    for iss in issues:
        if not iss.affects:
            continue
        for affect in iss.affects:
            if not isinstance(affect, dict):
                continue
            # scenario_ref 필터
            ref = affect.get("scenario_ref", "*")
            if scenario_id and ref != "*" and ref != scenario_id:
                continue
            match_rule = affect.get("match_rule")
            if not match_rule:
                # match_rule 없으면 해당 scenario_ref만으로 매칭 성립
                matched.append(iss)
                break
            try:
                hit = evaluate(match_rule, ctx)
            except (KeyError, TypeError, ValueError) as exc:
                # ETL은 rule을 schema 검증 없이 적재하므로 malformed rule이
                # 들어올 수 있다. 한 issue가 전체 응답을 500으로 만들지 않게 격리.
                logger.warning("match_rule evaluation failed for issue %s: %s", iss.id, exc)
                if evaluation_errors is not None and iss.id not in evaluation_errors:
                    evaluation_errors.append(iss.id)
                continue
            if hit:
                matched.append(iss)
                break  # 한 affects 항목이라도 매칭되면 충분
    return matched
