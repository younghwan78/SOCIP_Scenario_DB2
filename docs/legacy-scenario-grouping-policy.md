# Legacy Scenario Grouping Policy

This guide defines how legacy scenario YAML files should be grouped into one
canonical `scenario.usecase` with multiple variants.

## Core Rule

Do not group scenarios only because they share one HW IP.

Group scenarios when they have the same review purpose and a sufficiently
similar top-level pipeline. Split scenarios when the user intent, KPI, owner, or
dominant HW/SW path changes.

## Recommended Hierarchy

### 1. Scenario Family

Family is a coarse product/domain bucket used for filtering and planning.

Examples:

- `camera`
- `display_video`
- `video_playback`
- `audio`
- `voice_call`

### 2. Scenario Usecase

Usecase is the canonical `scenario.usecase` unit. This is the level where a
single base pipeline should make sense.

Recommended usecases:

- `camera_preview`
- `camera_recording`
- `camera_recording_apv`
- `camera_capture`
- `gallery_display`
- `video_playback_local`
- `youtube_playback`
- `audio_mp3_playback`
- `audio_streaming`
- `voice_call`

### 3. Variant

Variant is a condition or branch under one usecase.

Good variant axes:

- Resolution: `FHD`, `UHD`, `8K`
- FPS: `30`, `60`, `120`
- Sensor and sensor mode
- Codec profile or level
- HDR mode
- Display refresh rate
- GPU/NPU solution on/off when the main usecase remains the same
- Audio branch on/off inside `camera_recording`

## Split vs Variant Decision

Use a variant when:

- The primary user flow is the same.
- KPI budget is comparable.
- Review owner is mostly the same.
- Pipeline overlap is high enough to keep the base readable.
- Differences can be expressed by:
  - `design_conditions`
  - `size_overrides`
  - `node_configs`
  - `buffer_overrides`
  - `routing_switch`
  - `topology_patch`

Split into a different `scenario.usecase` when:

- Recording uses MFC but capture uses JPEG.
- APV path has a separate HW/SW owner or separate KPI.
- Camera and gallery both use DPU but have different user flows.
- YouTube playback has network/DRM/audio/SW-stack behavior not shared by local playback.
- Audio-only scenarios do not share the video/display/camera pipeline.
- Voice call has a different latency and power review model.

## Superset And Switch Pattern

For variants within one usecase:

- Put all commonly reviewed branches into the base superset pipeline.
- Disable unused branch nodes per variant with `routing_switch.disabled_nodes`.
- Disable unused edges per variant with `routing_switch.disabled_edges`.
- Keep SW task nodes in the base if they control or enable HW branch selection.
- If a SW task is absent in a variant and that removes HW IP usage, disable both the SW task and dependent HW nodes.

Example:

```yaml
routing_switch:
  disabled_nodes:
    - t_postIRTA
    - t_mfc
  disabled_edges:
    - { from: t_byrp, to: t_postIRTA, type: M2M }
    - { from: t_postIRTA, to: t_mfc, type: M2M }
```

## Delta Patch Pattern

Use `topology_patch` when the base superset cannot represent the change cleanly.

Good cases:

- A variant adds a one-off task not useful for other variants.
- A variant inserts a different producer/consumer path.
- A variant removes an edge but keeps both endpoint nodes active.

Avoid using `topology_patch` for simple branch on/off. Prefer `routing_switch`
because it is easier to review and compare.

## Importer Policy YAML

`--scenario-group` accepts an optional policy file:

```yaml
require_same_family: true
require_same_usecase: false
min_pipeline_overlap: 0.45
max_optional_node_ratio: 0.65
error_on_violation: true
allowed_families: [camera]
allowed_usecases:
  - camera_recording
  - camera_preview
required_common_roles: [sensor, isp]
```

Field meaning:

- `require_same_family`: reject groups crossing broad families such as camera and audio.
- `require_same_usecase`: reject groups such as recording plus preview or recording plus capture.
- `min_pipeline_overlap`: minimum pairwise node overlap ratio.
- `max_optional_node_ratio`: maximum ratio of nodes that are not common to all variants.
- `error_on_violation`: error when true, warning when false.
- `allowed_families`: optional allow-list.
- `allowed_usecases`: optional allow-list.
- `required_common_roles`: roles that must exist in every scenario.

## Practical Recommendation

Start strict for internal migration:

```yaml
require_same_family: true
require_same_usecase: true
min_pipeline_overlap: 0.60
max_optional_node_ratio: 0.50
error_on_violation: true
```

Relax only when reviewers explicitly want variants under the same screen.

For camera data, the first safe grouping target is:

- One `camera_recording` usecase.
- Variants for FHD/UHD/FPS/HDR/sensor/audio/solution branch.
- Separate usecases for `camera_capture`, `camera_recording_apv` if APV has a separate path, and display/video/audio-only scenarios.
