"""R-3 event job definitions: structure and static checks (no engine yet)."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from scenario_db.authoring.scenario import power_options_doc
from scenario_db.models.definition.job import JobSpec, expression_names
from scenario_db.models.definition.usecase import Pipeline, Usecase

NODES = [{"id": n, "ip_ref": f"ip-{n.replace('_', '-')}"} for n in ("sensor_rear", "csis", "byrp", "rgbp", "mtnr", "post_proc")]
JOB = {
    "id": "still_shot",
    "trigger": {"kind": "event", "at_ms": 200},
    "phases": ["precapture", "acquire", "process", "encode"],
    "buffers": {"cap_yuv": {"format": "YUV420", "bitdepth": 10, "count": 3}, "acc": {"format": "YUV420"},
                "jpeg": {"mb": "file_mb"}},
    "stages": [
        {"id": "aeaf", "phase": "precapture", "kind": "fixed", "nodes": ["csis"], "work": {"duration_ms": 50}},
        {"id": "readout", "phase": "acquire", "kind": "sensor", "nodes": ["sensor_rear"], "holds": ["csis"],
         "mode": {"param": "capture_sensor_mode"}, "frames": "grab_frames",
         "work": {"switch_in_ms": "switch_ms", "switch_out_ms": "switch_ms"}, "after": ["aeaf"],
         "when": {"acquire": "mode_switch"}},
        {"id": "reproc", "phase": "process", "nodes": ["byrp", "rgbp"], "frames": "zsl_frames",
         "reads": ["ZSL_RING_BUF"], "writes": ["cap_yuv"], "chunk": {"by": "frame"}, "after": ["aeaf", "readout"],
         "clock": {"CAM": "capture_cam_mhz"}},
        {"id": "merge", "phase": "process", "nodes": ["mtnr"], "frames": "zsl_frames", "writes": ["acc"],
         "after": [{"stage": "reproc", "per": "frame"}], "when": {"shooting_mode": ["mf", "night"]}},
        {"id": "enc", "phase": "encode", "kind": "sw", "nodes": ["post_proc"], "writes": ["jpeg"],
         "work": {"runtime_ms": "encode_ms * 1.0", "cluster": "big"}, "after": ["merge", "reproc"]},
    ],
    "milestones": {"saved": "enc"},
    "kpis": ["event_latency", "event_energy", "peak_footprint"],
}
PARAMS = {"capture_sensor_mode": "binning_4x4", "grab_frames": 1, "switch_ms": 0, "zsl_frames": 1,
          "capture_cam_mhz": 533, "encode_ms": 35, "file_mb": 4}


def _pipeline(job=None, **extra):
    return {"nodes": NODES, "edges": [], "buffers": {"ZSL_RING_BUF": {"format": "BAYER"}},
            "jobs": [job or deepcopy(JOB)], **extra}


def _usecase(pipeline, params=PARAMS):
    return {"id": "uc-x", "schema_version": "2.2", "kind": "scenario.usecase", "project_ref": "proj-x",
            "metadata": {"name": "x"}, "pipeline": pipeline, "power_options": {"params": params} if params else None}


def test_a_valid_job_passes_and_dumps_nothing_when_absent():
    Usecase.model_validate(_usecase(_pipeline()))
    plain = Pipeline.model_validate({"nodes": NODES})
    assert "jobs" not in plain.model_dump(exclude_none=True)   # undeclared scenarios keep their stored JSON


def _job(**patch):
    job = deepcopy(JOB)
    job.update(patch)
    return job


@pytest.mark.parametrize("mutate,message", [
    (lambda j: j["stages"].append(deepcopy(j["stages"][0])), "duplicate stage ids"),
    (lambda j: j["stages"][2]["after"].append("nope"), "after unknown stages"),
    (lambda j: j["stages"][0].update(after=["enc"]), "stage cycle"),
    (lambda j: j["stages"][2].update(writes=["undeclared"]), "undeclared job buffers"),
    (lambda j: j["milestones"].update(x="nope"), "milestone x"),
    (lambda j: j["stages"][2].update(chunk={"by": "stripe"}), "per-frame after needs frame chunks"),
    (lambda j: j["stages"][4].pop("work"), "needs work"),
    (lambda j: j["stages"][1].pop("mode"), "needs the sensor mode"),
    (lambda j: j["stages"][2].update(work={"runtime_ms": 1}), "takes no work block"),
    (lambda j: j["stages"][2].update(phase="later"), "not in phases"),
])
def test_job_structure_errors(mutate, message):
    job = deepcopy(JOB)
    mutate(job)
    with pytest.raises(ValidationError, match=message):
        JobSpec.model_validate(job)


@pytest.mark.parametrize("mutate,message", [
    (lambda p: p["jobs"][0]["stages"][2]["nodes"].append("ghost"), "node 'ghost' not found"),
    (lambda p: p["jobs"][0]["stages"][2].update(reads=["cap_yuv"]), "not pipeline"),
    (lambda p: p["jobs"][0]["buffers"].update(ZSL_RING_BUF={}), "shadow pipeline buffers"),
    (lambda p: p["jobs"].append(deepcopy(p["jobs"][0])), "duplicate job ids"),
])
def test_pipeline_level_job_errors(mutate, message):
    pipeline = _pipeline()
    mutate(pipeline)
    with pytest.raises(ValidationError, match=message):
        Pipeline.model_validate(pipeline)


def test_job_parameters_must_be_declared_knob_params():
    with pytest.raises(ValidationError, match=r"unknown parameters \['zsl_frames'\]"):
        Usecase.model_validate(_usecase(_pipeline(), params={k: v for k, v in PARAMS.items() if k != "zsl_frames"}))
    with pytest.raises(ValidationError, match="unknown parameter 'capture_sensor_mode'"):
        Usecase.model_validate(_usecase(_pipeline(),
                                        params={k: v for k, v in PARAMS.items() if k != "capture_sensor_mode"}))


def test_job_numbers_are_restricted_expressions():
    pipeline = _pipeline()
    pipeline["jobs"][0]["stages"][4]["work"]["runtime_ms"] = "__import__('os')"
    with pytest.raises(ValidationError, match="unsupported expression"):
        Usecase.model_validate(_usecase(pipeline))


def test_expression_names():
    assert expression_names(3, "x") == set()
    assert expression_names("a * 2 + -b / c", "x") == {"a", "b", "c"}
    for bad in (True, "", "a ** 2", "f(a)"):
        with pytest.raises(ValueError):
            expression_names(bad, "x")


def test_params_without_knobs_are_exported():
    assert power_options_doc({}) is None
    assert power_options_doc({"params": {"zsl_frames": 1}}) == {"params": {"zsl_frames": 1}}
    assert power_options_doc({"knobs": {"k": {}}, "params": {}}) == {"knobs": {"k": {}}}


@pytest.mark.parametrize("mutate,message", [
    (lambda j: j["stages"][2].update(frames=float("nan")), "not a finite number"),
    (lambda j: j["stages"][0]["work"].update(duration_ms=float("inf")), "not a finite number"),
    (lambda j: j["stages"][2].update(frames=True), "is not a number"),
    (lambda j: j["buffers"]["cap_yuv"].update(count=False), "is not a number"),
    (lambda j: j["stages"][2].update(ip_params={"ppc": "f(2)"}), "unsupported expression"),
    (lambda j: j["stages"][2].update(ip_params={"ppc": True}), "is not a number"),
    (lambda j: j["stages"][2].update(ip_params={"gain": 1}), r"ip_params \['gain'\]"),
    (lambda j: j["stages"][2].update(clock={"CAM": "1e999"}), "not a finite number"),
])
def test_numbers_are_finite_and_not_booleans(mutate, message):
    pipeline = _pipeline()
    mutate(pipeline["jobs"][0])
    with pytest.raises(ValidationError, match=message):
        Usecase.model_validate(_usecase(pipeline))


def test_ip_params_names_must_be_declared_params():
    pipeline = _pipeline()
    pipeline["jobs"][0]["stages"][2]["ip_params"] = {"ppc": "missing_ppc * 2", "unit_power_mw_mp": 4.3}
    with pytest.raises(ValidationError, match=r"ip_params.ppc: unknown parameters \['missing_ppc'\]"):
        Usecase.model_validate(_usecase(pipeline))
    pipeline["jobs"][0]["stages"][2]["ip_params"] = {"ppc": "zsl_frames * 8"}
    Usecase.model_validate(_usecase(pipeline))


def test_trigger_start_takes_a_parameter_and_rejects_booleans_and_negatives():
    pipeline = _pipeline()
    pipeline["jobs"][0]["trigger"]["at_ms"] = "trigger_delay_ms"
    Usecase.model_validate(_usecase(pipeline, params={**PARAMS, "trigger_delay_ms": 200}))
    with pytest.raises(ValidationError, match=r"trigger.at_ms: unknown parameters \['trigger_delay_ms'\]"):
        Usecase.model_validate(_usecase(pipeline))
    for bad, message in ((True, "is not a number"), (-1, "must be >= 0"), (float("inf"), "not a finite number")):
        pipeline["jobs"][0]["trigger"]["at_ms"] = bad
        with pytest.raises(ValidationError, match=message):
            Usecase.model_validate(_usecase(pipeline))


def test_a_pipeline_patch_must_not_leave_job_references_dangling():
    from scenario_db.write.service import _patched_pipeline, _validate_candidate_jobs

    pipeline = _pipeline()
    ok = _validate_candidate_jobs(pipeline, {n["id"] for n in NODES}, set(pipeline["buffers"]))
    assert ok == []
    candidate = _patched_pipeline(pipeline, {"remove_nodes": ["mtnr"], "remove_buffers": ["ZSL_RING_BUF"]})
    issues = _validate_candidate_jobs(candidate, {n["id"] for n in candidate["nodes"]}, set(candidate["buffers"]))
    messages = " | ".join(i.message for i in issues)
    assert {i.code for i in issues} == {"job_reference_invalid"}
    assert "node 'mtnr' not found" in messages and "reads ['ZSL_RING_BUF']" in messages


@pytest.mark.parametrize("mutate,message", [
    (lambda j: j["trigger"].update(kind="burst", count=1.5), "trigger.count 1.5 must be an integer >= 1"),
    (lambda j: j["trigger"].update(max_in_flight=-1), "max_in_flight -1.0 must be an integer >= 1"),
    (lambda j: j["trigger"].update(interval_ms=-10), "interval_ms -10.0 must be > 0"),
    (lambda j: j["trigger"].update(at_ms=-1), "at_ms -1.0 must be >= 0"),
    (lambda j: j["stages"][2].update(frames=0), "frames 0.0 must be an integer >= 1"),
    (lambda j: j["stages"][0]["work"].update(duration_ms=-5), "duration_ms -5.0 must be >= 0"),
    (lambda j: j["stages"][2].update(clock={"CAM": 0}), "clock.CAM 0.0 must be > 0"),
    (lambda j: j["stages"][2].update(ip_params={"ppc": 0}), "ip_params.ppc 0.0 must be > 0"),
    (lambda j: j["buffers"]["cap_yuv"].update(count=0), "buffers.cap_yuv.count 0.0 must be an integer >= 1"),
    (lambda j: j["buffers"]["jpeg"].update(mb=-4), "buffers.jpeg.mb -4.0 must be > 0"),
    (lambda j: j["stages"][4].update(chunk={"by": "stripe", "max_line_px": 64, "overlap_px": 64}),
     "max_line_px must exceed overlap_px"),
])
def test_number_literals_are_range_checked(mutate, message):
    job = deepcopy(JOB)
    mutate(job)
    with pytest.raises(ValidationError, match=message):
        JobSpec.model_validate(job)


def test_selector_nodes_must_exist():
    for where in ("job", "stage"):
        pipeline = _pipeline()
        target = pipeline["jobs"][0] if where == "job" else pipeline["jobs"][0]["stages"][2]
        target["when_node_enabled"] = "ghost"
        with pytest.raises(ValidationError, match="when_node_enabled 'ghost' not found"):
            Pipeline.model_validate(pipeline)



def test_buffer_consumers_count_in_the_cycle_check():
    job = deepcopy(JOB)
    # aeaf writes a buffer to readout, and aeaf runs after readout: each waits for the other
    job["buffers"]["pre"] = {"mb": 1, "to": ["readout"]}
    job["stages"][0].update(writes=["pre"], after=["readout"])
    job["stages"][1]["after"] = []
    with pytest.raises(ValidationError, match="stage cycle"):
        JobSpec.model_validate(job)


def test_a_per_frame_consumer_has_no_more_frames_than_its_producer():
    job = deepcopy(JOB)
    job["stages"][2]["frames"] = 1
    job["stages"][3]["frames"] = 2
    with pytest.raises(ValidationError, match="has 2 frames per-frame after reproc with 1"):
        JobSpec.model_validate(job)
    job["stages"][3]["frames"] = 1
    JobSpec.model_validate(job)


def test_conditional_params_from_param_rules_are_declared():
    pipeline = _pipeline()
    pipeline["jobs"][0]["stages"][3]["frames"] = "night_frames"
    uc = _usecase(pipeline)
    with pytest.raises(ValidationError, match=r"unknown parameters \['night_frames'\]"):
        Usecase.model_validate(uc)
    uc["power_options"]["param_rules"] = [{"when": {"shooting_mode": "night"}, "set": {"night_frames": 8}}]
    Usecase.model_validate(uc)


def test_an_explicit_dvfs_sn_must_name_a_table():
    job = deepcopy(JOB)
    job["stages"][2]["clock"] = {"dvfs_sn": None}
    with pytest.raises(ValidationError, match="clock.dvfs_sn needs"):
        JobSpec.model_validate(job)


def test_reimport_keeps_explicit_nulls_of_a_when_selector():
    from scenario_db.write.service import _compact_doc

    doc = {"pipeline": {"jobs": [{"id": "j", "when": {"shooting_mode": None}, "label": None,
                                  "stages": [{"id": "a", "when": {"hdr": None, "fps": 30}}]}]}}
    out = _compact_doc(doc)
    assert out["pipeline"]["jobs"][0]["when"] == {"shooting_mode": None}
    assert out["pipeline"]["jobs"][0]["stages"][0]["when"] == {"hdr": None, "fps": 30}
    assert "label" not in out["pipeline"]["jobs"][0]

