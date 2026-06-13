from __future__ import annotations

from scenario_db.meas_import.meta import PerfettoSpec
from scenario_db.meas_import.perfetto_digest import (
    SQL_FRAME_COUNT,
    SQL_FREQ_RESIDENCY,
    SQL_THREAD_SLICES,
    avg_freq_mhz,
    extract_digest,
    extract_freq_residency,
    extract_sw_task_timing,
)

NS = 1_000_000  # 1 ms in ns


class FakeTraceProcessor:
    """Returns canned rows per SQL statement so digest shaping is testable."""

    def __init__(self, freq_rows=None, slice_rows=None, frame_count=None):
        self._freq_rows = freq_rows or []
        self._slice_rows = slice_rows or []
        self._frame_count = frame_count
        self.queries: list[str] = []

    def query(self, sql: str):
        self.queries.append(sql)
        if sql == SQL_FREQ_RESIDENCY:
            return self._freq_rows
        if sql == SQL_THREAD_SLICES:
            return self._slice_rows
        if sql.startswith("SELECT COUNT(*) AS frame_count"):
            return [{"frame_count": self._frame_count}]
        raise AssertionError(f"unexpected SQL: {sql}")


def test_extract_freq_residency_normalises_per_cluster():
    rows = [
        {"cpu": 7, "freq_khz": 2600000, "dur_ns": 30 * NS},
        {"cpu": 7, "freq_khz": 1700000, "dur_ns": 70 * NS},
        {"cpu": 0, "freq_khz": 1500000, "dur_ns": 100 * NS},
    ]
    out = extract_freq_residency(rows, {7: "BIG", 0: "LIT"})
    big = {b["freq_mhz"]: b["ratio"] for b in out["BIG"]}
    assert big[2600.0] == 0.3
    assert big[1700.0] == 0.7
    # ordered by descending residency
    assert out["BIG"][0]["freq_mhz"] == 1700.0
    assert out["LIT"][0]["ratio"] == 1.0


def test_extract_freq_residency_ignores_unmapped_cpu():
    rows = [{"cpu": 99, "freq_khz": 1000000, "dur_ns": 50 * NS}]
    assert extract_freq_residency(rows, {0: "LIT"}) == {}


def test_avg_freq_weighted():
    bins = [
        {"freq_mhz": 2000.0, "ratio": 0.5, "time_ms": 1.0},
        {"freq_mhz": 1000.0, "ratio": 0.5, "time_ms": 1.0},
    ]
    assert avg_freq_mhz(bins) == 1500.0
    assert avg_freq_mhz([]) is None


def test_extract_sw_task_timing_matches_and_rolls_up():
    spec = PerfettoSpec(
        trace="x.pb",
        task_mapping=[
            {
                "task": "eis_warp",
                "cluster": "BIG",
                "match": {"process": "vendor.camera.provider", "thread_re": "VDIS.*"},
            },
            {
                "task": "encoder",
                "match": {"slice_re": "encode"},
            },
        ],
    )
    slice_rows = [
        {"slice_name": "warp", "dur_ns": 6 * NS, "thread_name": "VDISCore", "process_name": "vendor.camera.provider"},
        {"slice_name": "warp", "dur_ns": 10 * NS, "thread_name": "VDISCore", "process_name": "vendor.camera.provider"},
        {"slice_name": "encodeFrame", "dur_ns": 2 * NS, "thread_name": "Enc", "process_name": "mediaserver"},
        {"slice_name": "other", "dur_ns": 99 * NS, "thread_name": "X", "process_name": "system_server"},
    ]
    timings = extract_sw_task_timing(slice_rows, spec, frame_count=2)
    eis = next(t for t in timings if t["task"] == "eis_warp")
    assert eis["cluster"] == "BIG"
    assert eis["mean_ms"] == 8.0
    assert eis["max_ms"] == 10.0
    assert eis["samples"] == 2
    assert eis["count_per_frame"] == 1.0
    enc = next(t for t in timings if t["task"] == "encoder")
    assert enc["samples"] == 1


def test_extract_sw_task_timing_no_match_yields_bare_entry():
    spec = PerfettoSpec(
        trace="x.pb",
        task_mapping=[{"task": "ghost", "match": {"thread": "nope"}}],
    )
    timings = extract_sw_task_timing([], spec, frame_count=None)
    assert timings == [{"task": "ghost"}]


def test_extract_digest_end_to_end_with_fake():
    spec = PerfettoSpec(
        trace="x.pb",
        cpu_to_cluster={7: "BIG", 0: "LIT"},
        frame_slice_name="Camera::ProcessFrame",
        task_mapping=[{"task": "eis_warp", "match": {"thread_re": "VDIS.*"}}],
    )
    tp = FakeTraceProcessor(
        freq_rows=[
            {"cpu": 7, "freq_khz": 2000000, "dur_ns": 100 * NS},
            {"cpu": 0, "freq_khz": 1000000, "dur_ns": 100 * NS},
        ],
        slice_rows=[
            {"slice_name": "warp", "dur_ns": 5 * NS, "thread_name": "VDISCore", "process_name": "p"},
        ],
        frame_count=10,
    )
    digest = extract_digest(tp, spec)
    assert digest.frame_count == 10
    assert digest.cluster_avg_freq["BIG"] == 2000.0
    assert digest.freq_residency["LIT"][0]["ratio"] == 1.0
    assert digest.sw_task_timing[0]["task"] == "eis_warp"
    assert digest.sw_task_timing[0]["count_per_frame"] == 0.1


def test_extract_digest_frame_count_override_skips_count_query():
    spec = PerfettoSpec(trace="x.pb", frame_count=42, task_mapping=[{"task": "t", "match": {"thread": "z"}}])
    tp = FakeTraceProcessor(slice_rows=[])
    digest = extract_digest(tp, spec)
    assert digest.frame_count == 42
    assert not any(q.startswith("SELECT COUNT(*)") for q in tp.queries)
