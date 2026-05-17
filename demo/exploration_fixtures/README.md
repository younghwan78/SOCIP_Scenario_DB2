# Exploration Fixtures

These YAML files are examples for early SoC architecture exploration before the
final IP composition is fixed. They are authoring inputs for the exploration
compiler, not production `scenario.usecase` documents.

Use them from:

- Streamlit `Exploration Workbench`
- `scripts\compile_exploration_recipe.py`
- `scripts\compile_exploration_sweep.py`
- `scripts\compile_chain_template.py`
- `scripts\compile_chain_template_sweep.py`
- `scenario_db.sim.exploration_runner`

## Choosing an Input Type

| Type | Folder | Use when |
| --- | --- | --- |
| Single Design | `recipes/` | One quick candidate is enough. The chain is short and can be described block by block. |
| Batch Exploration | `sweeps/` | One base design should be expanded over fps, format, size, compression, or IP parameters. |
| Chain Template | `templates/` | The ISP chain has many IPs, DMA ports, and buffers. Compact links/tuples make the YAML shorter. |
| Template Sweep | `template_sweeps/` | A versioned chain template should be expanded across multiple candidate combinations. |

## Recipes

| File | Coverage |
| --- | --- |
| `recipes/camera_otf_chain_fhd30.yaml` | Sensor source, OTF chain, inherited shape, borrowed role mapping. |
| `recipes/camera_crop_scale_m2m.yaml` | Crop, scale down, vOTF/M2M handoff, WDMA output. |
| `recipes/camera_multi_output_fanout.yaml` | Multiple output ports with different sizes/formats/compression. |
| `recipes/codec_display_path.yaml` | RDMA/WDMA style codec/display path with borrowed unit power metadata. |

## Sweeps

| File | Coverage |
| --- | --- |
| `sweeps/camera_fps_format_sweep.yaml` | 4-case burst expansion across fps and source format. |
| `sweeps/camera_scale_compression_sweep.yaml` | 8-case expansion across scale target and compression. |
| `sweeps/camera_pyramid_sbwc_sweep.yaml` | 32-case camera pyramid fanout sweep across L0/L1/L2/L3/G4 SBWC enable combinations using recipe syntax. |

## Chain Templates

Templates are versioned authoring inputs for complex ISP chains. They support
compact buffer tuples and compact port-level links, then compile into canonical
ScenarioDB scenario documents.

| File | Coverage |
| --- | --- |
| `templates/camera_minimal_otf_v1.yaml` | Smallest readable template: HP2 source -> CSIS -> PDP over OTF links. Good for learning the template shape. |
| `templates/camera_recording_pyramid_v1.yaml` | Versioned HP2 recording pyramid chain with CSIS/PDP/BYRP/RGBP/YUVP/MLSC/MTNR/MSNR/MCSC/DPU/CODEC and compact L0/L1/L2/L3/G4 buffers. |

## Template Sweeps

Template sweeps expand one versioned chain template across axis values. This is
the preferred authoring format when the topology is complex but the exploration
mainly changes buffer compression, size, format, or selected IP parameters.

| File | Coverage |
| --- | --- |
| `template_sweeps/camera_recording_pyramid_sbwc_template_sweep.yaml` | 4-case L0/L1 SBWC on/off sweep over the versioned camera recording pyramid template. |
| `template_sweeps/camera_recording_pyramid_full_sbwc_template_sweep.yaml` | 32-case L0/L1/L2/L3/G4 SBWC on/off sweep over the same chain. Best example for realistic burst comparison. |

## Compact Template Syntax

Buffer tuple syntax:

```yaml
buffer_columns: [x, y, width, height, format, bitwidth, compression, comp_ratio]
buffers:
  L0: [0, 0, 2400, 1350, YUV420, 10, COMP_SBWC_LOSSLESS, 0.5]
  L1: {derive_from: L0, scale: 0.5}
```

Compact port link syntax:

```yaml
links:
  - "sensor_src:COUT -> csis:CIN | OTF"
  - "mlsc:WDMA0 -> L0 | M2M"
  - "L0 -> mtnr:RDMA0 | M2M"
```

Quote labels such as `"off"` in sweep axes. Unquoted `off` can be parsed as a
YAML boolean in some parsers.

## Compile Examples

```powershell
uv run python scripts\compile_exploration_recipe.py demo\exploration_fixtures\recipes\camera_crop_scale_m2m.yaml --output .runlogs\camera_crop_scale_m2m.compiled.yaml --bundle-output .runlogs\camera_crop_scale_m2m.bundle.json

uv run python scripts\compile_exploration_sweep.py demo\exploration_fixtures\sweeps\camera_fps_format_sweep.yaml --bundle-output .runlogs\camera_fps_format_sweep.bundle.json --cases-output .runlogs\camera_fps_format_sweep.cases.json

uv run python scripts\compile_chain_template.py demo\exploration_fixtures\templates\camera_minimal_otf_v1.yaml --output .runlogs\camera_minimal_otf.compiled.yaml --bundle-output .runlogs\camera_minimal_otf.bundle.json --normalized-output .runlogs\camera_minimal_otf.normalized.yaml

uv run python scripts\compile_chain_template.py demo\exploration_fixtures\templates\camera_recording_pyramid_v1.yaml --output .runlogs\camera_recording_pyramid.compiled.yaml --bundle-output .runlogs\camera_recording_pyramid.bundle.json --normalized-output .runlogs\camera_recording_pyramid.normalized.yaml

uv run python scripts\compile_chain_template_sweep.py demo\exploration_fixtures\template_sweeps\camera_recording_pyramid_full_sbwc_template_sweep.yaml --bundle-output .runlogs\camera_recording_pyramid_full_sweep.bundle.json --cases-output .runlogs\camera_recording_pyramid_full_sweep.cases.json
```

The compiled bundles are preview/staging inputs. Persist only selected
candidates after review.
