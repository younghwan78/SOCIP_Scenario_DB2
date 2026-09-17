# Synthetic camera profiling example

Not internal silicon data. Replace identifiers, conditions and statistics. Unlisted tasks are outside this curated summary, not disabled.

```yaml camera-profile-v1
format_version: camera-profile-v1
id: meas-camera-semantic-example-r1
project_ref: proj-sm-s947b
scenario_ref: uc-camera-recording
variant_ref: cam-rec-r1-fhd30-vdis
measured_at: '2026-09-17T10:00:00+09:00'
execution_context:
  silicon_rev: EVT1
  sw_baseline_ref: sw-vendor-v1.2.3
  thermal: room
generator_version: synthetic-example-1
measurement_scope: Synthetic steady-state illustration; not silicon measurement
workload:
  fps: 30
execution_path:
  id: fhd30-vdis
  description: Selected RT/SW stages of the FHD30 VDIS path
  enabled_task_ids:
  - rt_chain
  - post_crta
  - eis
pipeline_model:
  tasks:
  - task_id: rt_chain
    label: RT chain
    kind: group
    stage: rt
    node_refs:
    - csis
    - pdp
    - byrp
    - rgbp
    timing_scope: inclusive_stage
    includes_task_ids:
    - csis
    - pdp
    - byrp
    - rgbp
  - task_id: post_crta
    label: Post CRTA
    kind: sw
    stage: sw_m2m
    node_refs:
    - post_crta
    timing_scope: exclusive_sw
  - task_id: eis
    label: EIS
    kind: sw
    stage: eis
    node_refs:
    - eis
    timing_scope: exclusive_sw
  edges:
  - edge_id: rt_post
    source_task_id: rt_chain
    target_task_id: post_crta
statistics:
  sw_task_timing:
  - task: post_crta
    min_ms: 0.1
    avg_ms: 0.2
    max_ms: 0.3
    samples: 600
  - task: eis
    min_ms: 1
    avg_ms: 2
    max_ms: 3
    samples: 600
  sw_event_latency:
  - edge_id: rt_post
    min_ms: 0.01
    avg_ms: 0.03
    max_ms: 0.08
    samples: 600
  stage_timing:
  - task_id: rt_chain
    min_ms: 3
    avg_ms: 3.2
    max_ms: 3.5
    samples: 600
```
