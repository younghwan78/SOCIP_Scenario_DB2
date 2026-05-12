# Exploration Simulation Workflow

This workflow supports early SoC architecture exploration before final IP
catalog and block design are fixed.

The goal is to describe draft blocks as simple data-path components, borrow
simulation parameters from an existing mapping profile, compile the draft into
canonical ScenarioDB documents, and then run preview simulation without
persisting evidence until a candidate is confirmed.

## Concepts

### Exploration Recipe

An exploration recipe describes a single candidate pipeline.

Use it when:

- IP composition is not finalized.
- A block is only known as `RDMA/CIN -> core -> WDMA/COUT`.
- Unit power, ppc, sensor, or display metadata must be borrowed from a previous
  project.
- Size and format should inherit from sensor/source unless a block applies crop
  or scale.

The compiler emits a normal `scenario.usecase` document with one variant.

### Mapping Profile

A mapping profile maps draft roles to existing catalog data.

Borrowed values should be explicit. The compiler stores mapping provenance in
each node `sim.mapping_source` block so downstream debug trace can distinguish
native project data from borrowed exploration data.

### Exploration Sweep

An exploration sweep expands a base recipe across axes such as fps, format,
compression, crop/scale size, or per-block IP parameters.

When the generated topology is unchanged, variants are merged into one
`scenario.usecase`; otherwise separate scenario documents can be emitted.

## Recipe Example

```yaml
id: next-camera-fhd30
project_ref: proj-next
soc_ref: soc-next-draft
source:
  ip_ref: ip-sensor-rear-s5e9965
  width: 4080
  height: 2296
  fps: 30
  format: RAW_BAYER_16
  bitwidth: 12
mapping_profile:
  id: map-next-from-2600
  source_project_ref: proj-sm-s947b
  target_soc_ref: soc-next-draft
  role_mappings:
    byrp_like:
      source_ip_ref: ip-isp-s5e9965
      target_ip_ref: ip-isp-s5e9965
      source_role: byrp
      target_role: byrp
      confidence: borrowed
pipeline:
  - id: byrp0
    template: byrp_like
    inputs:
      - type: CIN
    outputs:
      - type: COUT
  - id: gdc0
    template: byrp_like
    inputs:
      - type: RDMA
    outputs:
      - type: WDMA
        port: GDC_WDMA
        format: YUV420
        compression: COMP_SBWC_LOSSLESS
    scale:
      width: 1920
      height: 1080
    output_format: YUV420
```

Compile it:

```powershell
uv run python scripts\compile_exploration_recipe.py recipe.yaml --output compiled-scenario.yaml --bundle-output import-bundle.json
```

## Sweep Example

```yaml
id: fps-format-sweep
base_recipe:
  id: next-camera-fhd
  scenario_id: uc-next-camera-fhd
  variant_id: explore
  project_ref: proj-next
  source:
    width: 1920
    height: 1080
    fps: 30
    format: RAW
  pipeline:
    - id: ip0
      template: isp
      ip_ref: ip-isp-v12
      inputs:
        - type: CIN
      outputs:
        - type: COUT
axes:
  - name: fps
    path: source.fps
    values: [30, 60]
  - name: fmt
    path: source.format
    values: [RAW, YUV]
```

Compile the sweep:

```powershell
uv run python scripts\compile_exploration_sweep.py sweep.yaml --bundle-output import-bundle.json --cases-output cases.json
```

## Shape Propagation

Exploration-compiled node configs set `sim.inherit_shape: true`.

When enabled, simulation uses the shape propagation layer:

1. Start from source sensor size/format/fps.
2. Carry shape through OTF/vOTF edges.
3. Use M2M buffer descriptor when present.
4. Apply node crop/scale/output format.
5. Fill missing DMA port width/height/format from propagated input/output.

Existing production fixtures do not opt in automatically, so current golden
simulation behavior remains stable unless a scenario explicitly uses
`inherit_shape` or `shape_propagation`.

## Recommended Usage

1. Validate the target SoC fixture contract.
2. Create or select a mapping profile from a previous project.
3. Compile a small recipe and run simulation preview.
4. Expand into a sweep for burst comparison.
5. Promote selected candidates into normal variants or save confirmed evidence.
