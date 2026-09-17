"""Compare matching RT/NRT stage boundaries without replacing model HW time."""

from collections import defaultdict


def compare_camera_stages(measurement: dict, prediction: dict) -> dict:
    for key in ("project_ref", "scenario_ref", "variant_ref"):
        if not measurement.get(key) or measurement[key] != prediction.get(key):
            raise ValueError("stage comparison requires identical project/scenario/variant")
    if (
        prediction.get("kind") != "evidence.simulation"
        or measurement.get("kind") != "evidence.measurement"
    ):
        raise ValueError("stage comparison requires simulation and measurement")
    model = measurement.get("pipeline_model") or {}
    if not model:
        raise ValueError("camera semantic graph required")
    # Legacy measured replay may replace HW duration. Such a result is not independent validation.
    if (prediction.get("run") or prediction.get("run_info") or {}).get("timing_profile"):
        raise ValueError("HW model validation cannot use measured timing replay")
    tasks = {t["task_id"]: t for t in model.get("tasks", [])}
    by_frame = defaultdict(list)
    for event in prediction.get("timeline_events") or []:
        if event.get("frame_index") is None:
            continue
        by_frame[event.get("frame_index")].append(event)
    rows = []
    for stat in measurement.get("stage_timing") or []:
        task = tasks[stat["task_id"]]
        refs = set(task["node_refs"])
        spans = []
        for events in by_frame.values():
            selected = [e for e in events if (e.get("node_id") or e.get("task_id")) in refs]
            if {e.get("node_id") or e.get("task_id") for e in selected} == refs:
                spans.append(
                    max(e["end_ms"] for e in selected) - min(e["start_ms"] for e in selected)
                )
        predicted = sum(spans) / len(spans) if spans else None
        measured = stat["mean_ms"]
        rows.append(
            dict(
                task_id=stat["task_id"],
                measured_mean_ms=measured,
                predicted_mean_ms=predicted,
                predicted_frames=len(spans),
                delta_ms=predicted - measured if predicted is not None else None,
                relative_error_pct=100 * (predicted - measured) / measured
                if predicted is not None and measured
                else None,
                status="diagnostic_only"
                if predicted is not None
                else "missing_prediction_boundary",
            )
        )
    return dict(
        rows=rows,
        validated=False,
        notes=[
            "Matching node boundary spans, not the sum of per-IP durations.",
            "Verify capture clocks, workload, model revision and scheduling conditions before accepting model accuracy.",
            "Independent per-task min/max values do not describe an observed worst frame.",
        ],
    )
