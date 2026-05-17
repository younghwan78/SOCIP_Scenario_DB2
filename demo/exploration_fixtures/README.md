# Exploration Fixtures

These YAML files are examples for early SoC architecture exploration before the
final IP composition is fixed.

They are not canonical ScenarioDB `scenario.usecase` documents. They are inputs
for:

- `scripts\compile_exploration_recipe.py`
- `scripts\compile_exploration_sweep.py`
- `scripts\compile_chain_template.py`
- `scenario_db.sim.exploration_runner.run_exploration_sweep_preview`

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
| `sweeps/camera_fps_format_sweep.yaml` | Burst expansion across fps and source format. |
| `sweeps/camera_pyramid_sbwc_sweep.yaml` | 32-case camera pyramid fanout sweep across L0/L1/L2/L3/G4 SBWC enable combinations. |
| `sweeps/camera_scale_compression_sweep.yaml` | Burst expansion across scale target and compression. |

## Chain Templates

Templates are versioned authoring inputs for complex ISP chains. They support
compact buffer tuples and compact port-level links, then compile into canonical
ScenarioDB scenario documents.

| File | Coverage |
| --- | --- |
| `templates/camera_recording_pyramid_v1.yaml` | Versioned HP2 recording pyramid chain with CSIS/PDP/BYRP/RGBP/YUVP/MLSC/MTNR/MSNR/MCSC/DPU/CODEC and compact L0/L1/L2/L3/G4 buffers. |

## Compile Examples

```powershell
uv run python scripts\compile_exploration_recipe.py demo\exploration_fixtures\recipes\camera_crop_scale_m2m.yaml --output .runlogs\camera_crop_scale_m2m.compiled.yaml --bundle-output .runlogs\camera_crop_scale_m2m.bundle.json

uv run python scripts\compile_exploration_sweep.py demo\exploration_fixtures\sweeps\camera_fps_format_sweep.yaml --bundle-output .runlogs\camera_fps_format_sweep.bundle.json --cases-output .runlogs\camera_fps_format_sweep.cases.json

uv run python scripts\compile_chain_template.py demo\exploration_fixtures\templates\camera_recording_pyramid_v1.yaml --output .runlogs\camera_recording_pyramid.compiled.yaml --bundle-output .runlogs\camera_recording_pyramid.bundle.json --normalized-output .runlogs\camera_recording_pyramid.normalized.yaml
```

The compiled bundles are preview/staging inputs. Persist only selected
candidates after review.
