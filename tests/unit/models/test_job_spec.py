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
