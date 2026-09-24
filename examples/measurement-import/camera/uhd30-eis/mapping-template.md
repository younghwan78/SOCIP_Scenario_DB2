# Synthetic UHD30 mapping template

```yaml camera-profile-v1
format_version: camera-profile-v1
id: meas-synthetic-uhd30-eis-15s-r3
project_ref: proj-sm-s947b
scenario_ref: uc-camera-recording
variant_ref: cam-rec-r1-uhd30-vdis
measured_at: '2026-09-21T00:00:00+09:00'
execution_context:
  silicon_rev: EVT1
  sw_baseline_ref: sw-vendor-v1.2.3
  thermal: room
generator_version: synthetic-scenario-trace-3
measurement_scope: 'SYNTHETIC fixture: 15 seconds, UHD30 EIS, 450 frame starts, final
  video warp incomplete; not silicon measurement'
workload:
  resolution: UHD
  fps: 30
  stabilization: SWVDIS
execution_path:
  id: uhd30-eis-lme
  description: Synthetic UHD30 EIS with LME and preview/video GDC
  enabled_task_ids:
  - sensor_readout
  - csis
  - pdp
  - byrp
  - rgbp
  - yuvsc
  - mlsc
  - crta_3a
  - post_crta
  - pre_me_rta
  - lme
  - post_irta
  - mtnr
  - msnr
  - yuvp
  - mcsc
  - eis
  - gdc_m
  - gdc_o
pipeline_model:
  tasks:
  - task_id: sensor_readout
    label: SENSOR_READOUT
    kind: hw
    stage: sensor
    node_refs:
    - sensor_rear
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: SENSOR_READOUT
    trace_track_name: Scenario / SENSOR / SENSOR
  - task_id: csis
    label: CSI_RECEIVE
    kind: hw
    stage: rt
    node_refs:
    - csis
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: CSI_RECEIVE
    trace_track_name: Scenario / RT / CSI
  - task_id: pdp
    label: '!PDP_PROCESS'
    kind: hw
    stage: rt
    node_refs:
    - pdp
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: '!PDP_PROCESS'
    trace_track_name: Scenario / RT / PDP
  - task_id: byrp
    label: '!BYRP_PROCESS'
    kind: hw
    stage: rt
    node_refs:
    - byrp
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: '!BYRP_PROCESS'
    trace_track_name: Scenario / RT / BYRP
  - task_id: rgbp
    label: '!RGBP_PROCESS'
    kind: hw
    stage: rt
    node_refs:
    - rgbp
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: '!RGBP_PROCESS'
    trace_track_name: Scenario / RT / RGBP
  - task_id: yuvsc
    label: '!YUVSC_PROCESS'
    kind: hw
    stage: rt
    node_refs:
    - yuvsc
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: '!YUVSC_PROCESS'
    trace_track_name: Scenario / RT / YUVSC
  - task_id: mlsc
    label: '!MLSC_PROCESS'
    kind: hw
    stage: rt
    node_refs:
    - mlsc
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: '!MLSC_PROCESS'
    trace_track_name: Scenario / RT / MLSC
  - task_id: crta_3a
    label: ~CRTA_3A
    kind: sw
    stage: sw_m2m
    node_refs: []
    observation_only: true
    timing_scope: exclusive_sw
    trace_slice_name: ~CRTA_3A
    trace_track_name: Scenario / SW / ICPU
  - task_id: post_crta
    label: POST_CRTA
    kind: sw
    stage: sw_m2m
    node_refs:
    - post_crta
    observation_only: false
    timing_scope: exclusive_sw
    trace_slice_name: POST_CRTA
    trace_track_name: Scenario / SW / HAL_RT
  - task_id: pre_me_rta
    label: ~PRE_LME_IRTA
    kind: sw
    stage: sw_m2m
    node_refs:
    - pre_me_rta
    observation_only: false
    timing_scope: exclusive_sw
    trace_slice_name: ~PRE_LME_IRTA
    trace_track_name: Scenario / SW / HAL_RT
  - task_id: lme
    label: LME_PROCESS
    kind: hw
    stage: sw_m2m
    node_refs:
    - lme
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: LME_PROCESS
    trace_track_name: Scenario / M2M / LME
  - task_id: post_irta
    label: POST_IRTA
    kind: sw
    stage: sw_m2m
    node_refs:
    - post_irta
    observation_only: false
    timing_scope: exclusive_sw
    trace_slice_name: POST_IRTA
    trace_track_name: Scenario / SW / HAL_RT
  - task_id: mtnr
    label: MTNR_PROCESS
    kind: hw
    stage: nrt
    node_refs:
    - mtnr
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: MTNR_PROCESS
    trace_track_name: Scenario / NRT / MTNR
  - task_id: msnr
    label: MSNR_PROCESS
    kind: hw
    stage: nrt
    node_refs:
    - msnr
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: MSNR_PROCESS
    trace_track_name: Scenario / NRT / MSNR
  - task_id: yuvp
    label: YUVP_PROCESS
    kind: hw
    stage: nrt
    node_refs:
    - yuvp
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: YUVP_PROCESS
    trace_track_name: Scenario / NRT / YUVP
  - task_id: mcsc
    label: MCSC_PROCESS
    kind: hw
    stage: nrt
    node_refs:
    - mcsc
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: MCSC_PROCESS
    trace_track_name: Scenario / NRT / MCSC
  - task_id: eis
    label: ~EIS
    kind: sw
    stage: eis
    node_refs:
    - eis
    observation_only: false
    timing_scope: exclusive_sw
    trace_slice_name: ~EIS
    trace_track_name: Scenario / SW / HAL_RT
  - task_id: gdc_m
    label: ~GDC_WARP_PREVIEW
    kind: hw
    stage: gdc
    node_refs:
    - gdc_m
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: ~GDC_WARP_PREVIEW
    trace_track_name: Scenario / M2M / GDC_M
  - task_id: gdc_o
    label: ~GDC_WARP_VIDEO
    kind: hw
    stage: gdc
    node_refs:
    - gdc_o
    observation_only: false
    timing_scope: hw_execution
    trace_slice_name: ~GDC_WARP_VIDEO
    trace_track_name: Scenario / M2M / GDC_O
  edges:
  - edge_id: sensor_readout_csis
    source_task_id: sensor_readout
    target_task_id: csis
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: csis_pdp
    source_task_id: csis
    target_task_id: pdp
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: pdp_byrp
    source_task_id: pdp
    target_task_id: byrp
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: byrp_rgbp
    source_task_id: byrp
    target_task_id: rgbp
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: rgbp_yuvsc
    source_task_id: rgbp
    target_task_id: yuvsc
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: yuvsc_mlsc
    source_task_id: yuvsc
    target_task_id: mlsc
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: mlsc_crta_3a
    source_task_id: mlsc
    target_task_id: crta_3a
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: crta_3a_post_crta
    source_task_id: crta_3a
    target_task_id: post_crta
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: post_crta_pre_me_rta
    source_task_id: post_crta
    target_task_id: pre_me_rta
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: pre_me_rta_lme
    source_task_id: pre_me_rta
    target_task_id: lme
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: lme_post_irta
    source_task_id: lme
    target_task_id: post_irta
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: post_irta_mtnr
    source_task_id: post_irta
    target_task_id: mtnr
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: mtnr_msnr
    source_task_id: mtnr
    target_task_id: msnr
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: msnr_yuvp
    source_task_id: msnr
    target_task_id: yuvp
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: yuvp_mcsc
    source_task_id: yuvp
    target_task_id: mcsc
    source_anchor: start
    dependency_kind: start_to_start
  - edge_id: mcsc_eis
    source_task_id: mcsc
    target_task_id: eis
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: eis_gdc_m
    source_task_id: eis
    target_task_id: gdc_m
    source_anchor: end
    dependency_kind: finish_to_start
  - edge_id: eis_gdc_o
    source_task_id: eis
    target_task_id: gdc_o
    source_anchor: end
    dependency_kind: finish_to_start
statistics: {}
notes: 'CRTA_3A is observation-only: no standalone canonical ICPU node. User-provided
  typical durations: sensor valid 11.8 ms, IRTA 4 ms (mapped to PRE_LME_IRTA), EIS
  3.2 ms, NRT 8 ms, preview GDC 2.3 ms, video GDC 8.6 ms. RT duration follows sensor
  valid time as a fixture assumption. Other durations, start offsets, LME naming and
  +/-2% variation are synthetic assumptions. Explicit synthetic per-frame flows connect
  SENSOR through both GDC branches. NRT OTF slices share start/end timestamps for
  the integrated interrupt.'
```
