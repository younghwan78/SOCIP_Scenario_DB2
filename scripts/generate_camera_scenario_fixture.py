"""Generate a deterministic synthetic 15-second UHD30 EIS Perfetto bundle."""

from pathlib import Path
import argparse

import yaml

from scenario_db.meas_import.camera_scenario_trace import main as summarize_main

# task, slice prefix, track, kind, stage, canonical node, start ms, duration ms.
# These are illustrative wall times, not Exynos2600 measurement or OTF budgets.
TASKS = [
    ("sensor_readout", "SENSOR_READOUT", "SENSOR / SENSOR", "hw", "sensor", "sensor_rear", 0, 11.8),
    ("csis", "CSI_RECEIVE", "RT / CSI", "hw", "rt", "csis", .1, 11.8),
    ("pdp", "!PDP_PROCESS", "RT / PDP", "hw", "rt", "pdp", .2, 11.8),
    ("byrp", "!BYRP_PROCESS", "RT / BYRP", "hw", "rt", "byrp", .3, 11.8),
    ("rgbp", "!RGBP_PROCESS", "RT / RGBP", "hw", "rt", "rgbp", .4, 11.8),
    ("yuvsc", "!YUVSC_PROCESS", "RT / YUVSC", "hw", "rt", "yuvsc", .5, 11.8),
    ("mlsc", "!MLSC_PROCESS", "RT / MLSC", "hw", "rt", "mlsc", .6, 11.8),
    ("crta_3a", "~CRTA_3A", "SW / ICPU", "sw", "sw_m2m", None, 12.7, .3),
    ("post_crta", "POST_CRTA", "SW / HAL_RT", "sw", "sw_m2m", "post_crta", 13.2, .2),
    ("pre_me_rta", "~PRE_LME_IRTA", "SW / HAL_RT", "sw", "sw_m2m", "pre_me_rta", 13.5, 4),
    ("lme", "LME_PROCESS", "M2M / LME", "hw", "sw_m2m", "lme", 17.7, .6),
    ("post_irta", "POST_IRTA", "SW / HAL_RT", "sw", "sw_m2m", "post_irta", 18.4, .2),
    ("mtnr", "MTNR_PROCESS", "NRT / MTNR", "hw", "nrt", "mtnr", 18.8, 8),
    ("msnr", "MSNR_PROCESS", "NRT / MSNR", "hw", "nrt", "msnr", 18.8, 8),
    ("yuvp", "YUVP_PROCESS", "NRT / YUVP", "hw", "nrt", "yuvp", 18.8, 8),
    ("mcsc", "MCSC_PROCESS", "NRT / MCSC", "hw", "nrt", "mcsc", 18.8, 8),
    ("eis", "~EIS", "SW / HAL_RT", "sw", "eis", "eis", 27.2, 3.2),
    ("gdc_m", "~GDC_WARP_PREVIEW", "M2M / GDC_M", "hw", "gdc", "gdc_m", 30.6, 2.3),
    ("gdc_o", "~GDC_WARP_VIDEO", "M2M / GDC_O", "hw", "gdc", "gdc_o", 30.6, 8.6),
]


def generate(directory: Path):
    from perfetto.protos.perfetto.trace import perfetto_trace_pb2 as proto

    directory.mkdir(parents=True, exist_ok=True)
    chain = [t[0] for t in TASKS]
    edges = []
    for index, (source, target) in enumerate(zip(chain, chain[1:])):
        if target == "gdc_o":
            source = "eis"  # Independent preview/video branches, not serial warps.
        otf = index < 6 or (source in {"mtnr", "msnr", "yuvp"})
        edges.append(dict(edge_id=f"{source}_{target}", source_task_id=source,
                          target_task_id=target, source_anchor="start" if otf else "end",
                          dependency_kind="start_to_start" if otf else "finish_to_start"))
    trace = proto.Trace()
    names = ["Scenario"]
    groups = {
        "SW": ["HAL_RT", "ICPU", "CAM_DRIVER"],
        "SENSOR": ["SENSOR"],
        "RT": ["CSI", "PDP", "BYRP", "RGBP", "YUVSC", "MLSC"],
        "NRT": ["MTNR", "MSNR", "YUVP", "MCSC"],
        "M2M": ["LME", "GDC_M", "GDC_O", "VPS"],
    }
    for group, children in groups.items():
        names.append(f"Scenario / {group}")
        names.extend(f"Scenario / {group} / {child}" for child in children)
    ids = {name: index + 1 for index, name in enumerate(names)}
    for name, uuid in ids.items():
        desc = trace.packet.add().track_descriptor
        desc.uuid, desc.name = uuid, name
        desc.child_ordering = proto.TrackDescriptor.EXPLICIT
        desc.sibling_order_rank = uuid
        if name != "Scenario":
            desc.parent_uuid = ids[name.rsplit(" / ", 1)[0]]
    events = []
    tasks = []
    for task, prefix, track, kind, stage, node, start, duration in TASKS:
        tasks.append(dict(
            task_id=task, label=prefix, kind=kind, stage=stage,
            node_refs=[node] if node else [], observation_only=node is None,
            timing_scope="exclusive_sw" if kind == "sw" else "hw_execution",
            trace_slice_name=prefix, trace_track_name=f"Scenario / {track}",
        ))
        for frame in range(450):
            offset = frame * 1_000_000_000 // 30
            begin = offset + round(start * 1e6)
            # Deterministic +/- 2% variation gives distinct min/mean/max.
            dur = round(duration * (1 + (frame % 5 - 2) * .01) * 1e6)
            events.extend([
                (begin, 1, ids[f"Scenario / {track}"], f"{prefix} f{frame:04d}"),
                (begin + dur, 2, ids[f"Scenario / {track}"], ""),
            ])
    # Extra data exercises forward-compatible filtering.
    events.extend([(0, 1, ids["Scenario / SW / CAM_DRIVER"], "UNRELATED_DRIVER_WORK"),
                   (50_000, 2, ids["Scenario / SW / CAM_DRIVER"], ""),
                   (0, 3, ids["Scenario"], "SYNTHETIC_CAPTURE_BEGIN"),
                   (15_000_000_000, 3, ids["Scenario"], "SYNTHETIC_CAPTURE_END")])
    task_by_prefix = {t[1]: t[0] for t in TASKS}
    for ts, event_type, track_id, name in sorted(events):
        if ts > 15_000_000_000:
            continue  # Keep the final video warp open at the capture boundary.
        packet = trace.packet.add()
        packet.timestamp = ts
        packet.trusted_packet_sequence_id = 1
        packet.track_event.type = event_type
        packet.track_event.track_uuid = track_id
        if name:
            packet.track_event.name = name
        packet.track_event.categories.append("Scenario")
        if event_type == 1 and " f" in name:
            prefix, frame = name.rsplit(" f", 1)
            task_id = task_by_prefix[prefix]
            for edge_index, edge in enumerate(edges):
                # One ID per edge per frame prevents branch serialization and
                # accidental links between consecutive frames.
                flow_id = int(frame) * len(edges) + edge_index + 1
                if edge["source_task_id"] == task_id:
                    packet.track_event.flow_ids.append(flow_id)
                if edge["target_task_id"] == task_id:
                    packet.track_event.terminating_flow_ids.append(flow_id)
    path = directory / "uhd30-eis-15s.pftrace"
    path.write_bytes(trace.SerializeToString())
    template = dict(
        format_version="camera-profile-v1", id="meas-synthetic-uhd30-eis-15s-r3",
        project_ref="proj-sm-s947b", scenario_ref="uc-camera-recording",
        variant_ref="cam-rec-r1-uhd30-vdis", measured_at="2026-09-21T00:00:00+09:00",
        execution_context=dict(silicon_rev="EVT1", sw_baseline_ref="sw-vendor-v1.2.3", thermal="room"),
        generator_version="synthetic-scenario-trace-3",
        measurement_scope="SYNTHETIC fixture: 15 seconds, UHD30 EIS, 450 frame starts, final video warp incomplete; not silicon measurement",
        workload=dict(resolution="UHD", fps=30, stabilization="SWVDIS"),
        execution_path=dict(id="uhd30-eis-lme", description="Synthetic UHD30 EIS with LME and preview/video GDC",
                            enabled_task_ids=chain),
        pipeline_model=dict(tasks=tasks, edges=edges), statistics={},
        notes="CRTA_3A is observation-only: no standalone canonical ICPU node. User-provided typical durations: sensor valid 11.8 ms, IRTA 4 ms (mapped to PRE_LME_IRTA), EIS 3.2 ms, NRT 8 ms, preview GDC 2.3 ms, video GDC 8.6 ms. RT duration follows sensor valid time as a fixture assumption. Other durations, start offsets, LME naming and +/-2% variation are synthetic assumptions. Explicit synthetic per-frame flows connect SENSOR through both GDC branches. NRT OTF slices share start/end timestamps for the integrated interrupt.",
    )
    mapping = directory / "mapping-template.md"
    mapping.write_text("# Synthetic UHD30 mapping template\n\n```yaml camera-profile-v1\n"
                       + yaml.safe_dump(template, sort_keys=False) + "```\n", encoding="utf-8")
    summarize_main(["--trace", str(path), "--template", str(mapping),
                    "--out", str(directory / ".scenario-statistics-r3.md")])
    (directory / ".scenario-statistics-r3.md").replace(directory / "scenario-statistics.md")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("examples/measurement-import/camera/uhd30-eis"))
    generate(parser.parse_args().out)
