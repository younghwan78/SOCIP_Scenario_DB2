"""
Matcher Runner 성능 벤치마크.

측정 항목:
  - n_variants: [20, 100, 500, 1000]
  - n_issues:   [1, 10, 50, 200]
  - complexity: simple (eq only) | complex (all+any+nested)
  - 통계: p50 / p95 / p99 (1000회 반복)

출력: docs/perf/week1_benchmark.md
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scenario_db.matcher.context import MatcherContext
from scenario_db.matcher.runner import evaluate

# ---------------------------------------------------------------------------
# 룰 팩토리
# ---------------------------------------------------------------------------

SIMPLE_RULE = {
    "field": "axis.resolution",
    "op": "eq",
    "value": "UHD",
}

COMPLEX_RULE = {
    "all": [
        {"field": "axis.resolution", "op": "in", "value": ["UHD", "4K"]},
        {"field": "axis.fps", "op": "gte", "value": 60},
        {
            "any": [
                {"field": "sw_feature.LLC_per_ip_partition", "op": "eq", "value": "disabled"},
                {"field": "ip.ISP.count", "op": "gt", "value": 1},
            ]
        },
        {"field": "axis.hdr", "op": "matches", "value": r"^HDR"},
    ]
}


def _make_contexts(n: int) -> list[MatcherContext]:
    ctxs = []
    for i in range(n):
        ctxs.append(
            MatcherContext(
                design_conditions={
                    "resolution": "UHD" if i % 2 == 0 else "FHD",
                    "fps": 60 if i % 3 == 0 else 30,
                    "hdr": "HDR10" if i % 4 == 0 else "SDR",
                },
                ip_requirements={"ISP": {"count": (i % 3) + 1}},
                sw_requirements={
                    "feature_flags": {
                        "LLC_per_ip_partition": "disabled" if i % 5 == 0 else "enabled",
                    }
                },
            )
        )
    return ctxs


def _make_issues(n: int, complexity: str) -> list[dict]:
    rule = SIMPLE_RULE if complexity == "simple" else COMPLEX_RULE
    return [{"id": f"iss-{i:04d}", "affects": rule} for i in range(n)]


# ---------------------------------------------------------------------------
# 벤치마크 실행
# ---------------------------------------------------------------------------

class IssueStub:
    def __init__(self, issue_id: str, affects: dict):
        self.id = issue_id
        self.affects = affects


def bench_match(contexts: list[MatcherContext], issues: list[IssueStub], repeats: int = 1000) -> dict:
    """전체 contexts × issues 매칭을 repeats회 실행하여 통계 계산."""
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for ctx in contexts:
            for iss in issues:
                if iss.affects:
                    evaluate(iss.affects, ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        samples.append(elapsed_ms)

    return {
        "p50": round(statistics.median(samples), 3),
        "p95": round(sorted(samples)[int(len(samples) * 0.95)], 3),
        "p99": round(sorted(samples)[int(len(samples) * 0.99)], 3),
        "throughput_vps": round(
            len(contexts) * repeats / (sum(samples) / 1000), 0
        ),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    N_VARIANTS = [20, 100, 500, 1000]
    N_ISSUES = [1, 10, 50, 200]
    COMPLEXITIES = ["simple", "complex"]
    REPEATS = 200  # 전체 실행 시간 고려

    rows: list[dict] = []

    for complexity in COMPLEXITIES:
        for n_v in N_VARIANTS:
            ctxs = _make_contexts(n_v)
            for n_i in N_ISSUES:
                issues = [IssueStub(f"iss-{i}", SIMPLE_RULE if complexity == "simple" else COMPLEX_RULE)
                          for i in range(n_i)]
                stats = bench_match(ctxs, issues, repeats=REPEATS)
                row = {
                    "n_variants": n_v,
                    "n_issues": n_i,
                    "complexity": complexity,
                    **stats,
                }
                rows.append(row)
                print(
                    f"  [{complexity:7s}] v={n_v:4d} i={n_i:3d} | "
                    f"p50={stats['p50']:7.3f}ms p95={stats['p95']:7.3f}ms "
                    f"p99={stats['p99']:7.3f}ms tput={stats['throughput_vps']:.0f} v/s"
                )

    # Markdown 출력
    out_path = Path(__file__).parent.parent / "docs" / "perf" / "week1_benchmark.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "# Matcher Runner Benchmark — Week 1\n\n"
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        "| n_variants | n_issues | complexity | p50_ms | p95_ms | p99_ms | throughput (v/s) |\n"
        "|-----------|---------|-----------|--------|--------|--------|------------------|\n"
    )
    md_rows = "".join(
        f"| {r['n_variants']:>9} | {r['n_issues']:>8} | {r['complexity']:>10} | "
        f"{r['p50']:>6.3f} | {r['p95']:>6.3f} | {r['p99']:>6.3f} | "
        f"{r['throughput_vps']:>16.0f} |\n"
        for r in rows
    )
    out_path.write_text(header + md_rows, encoding="utf-8")
    print(f"\nBenchmark results written to: {out_path}")


if __name__ == "__main__":
    main()
