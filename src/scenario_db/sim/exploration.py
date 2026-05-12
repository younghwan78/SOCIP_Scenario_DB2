from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ExplorationSource(BaseModel):
    type: Literal["sensor", "display", "buffer"] = "sensor"
    node_id: str = "sensor_src"
    ip_ref: str | None = None
    width: int
    height: int
    fps: float = 30.0
    format: str | None = "RAW_BAYER"
    bitwidth: int = 12
    compression: str = "disable"

    @model_validator(mode="after")
    def _validate_source(self) -> ExplorationSource:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("source width/height must be positive")
        if self.fps <= 0:
            raise ValueError("source fps must be positive")
        if self.bitwidth <= 0:
            raise ValueError("source bitwidth must be positive")
        return self


class ExplorationPort(BaseModel):
    port: str | None = None
    type: Literal["RDMA", "WDMA", "CIN", "COUT", "OTF_IN", "OTF_OUT"] = "CIN"
    width: int | None = None
    height: int | None = None
    format: str | None = None
    bitwidth: int | None = None
    compression: str | None = None
    comp_ratio: float | None = None
    llc_enabled: bool | None = None

    @model_validator(mode="after")
    def _validate_port(self) -> ExplorationPort:
        if self.width is not None and self.width <= 0:
            raise ValueError("port width must be positive when provided")
        if self.height is not None and self.height <= 0:
            raise ValueError("port height must be positive when provided")
        if self.bitwidth is not None and self.bitwidth <= 0:
            raise ValueError("port bitwidth must be positive when provided")
        if self.comp_ratio is not None and self.comp_ratio <= 0:
            raise ValueError("port comp_ratio must be positive when provided")
        return self


class ExplorationBlock(BaseModel):
    id: str
    template: str
    role: str | None = None
    ip_ref: str | None = None
    selected_mode: str = "Normal"
    inputs: list[ExplorationPort] = Field(default_factory=list)
    outputs: list[ExplorationPort] = Field(default_factory=list)
    crop: dict[str, int] | None = None
    scale: dict[str, int] | None = None
    output_format: str | None = None
    ip_params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_block(self) -> ExplorationBlock:
        for field_name in ("crop", "scale"):
            value = getattr(self, field_name)
            if value is None:
                continue
            width = value.get("width", value.get("w"))
            height = value.get("height", value.get("h"))
            if width is not None and int(width) <= 0:
                raise ValueError(f"{field_name}.width must be positive")
            if height is not None and int(height) <= 0:
                raise ValueError(f"{field_name}.height must be positive")
        return self


class MappingEntry(BaseModel):
    source_ip_ref: str | None = None
    target_ip_ref: str | None = None
    source_role: str | None = None
    target_role: str | None = None
    mode: str = "Normal"
    scale: float = 1.0
    confidence: str = "borrowed"
    ip_params: dict[str, Any] = Field(default_factory=dict)


class MappingProfile(BaseModel):
    id: str = "inline-mapping"
    source_project_ref: str | None = None
    target_soc_ref: str | None = None
    role_mappings: dict[str, MappingEntry] = Field(default_factory=dict)
    external_mappings: dict[str, str] = Field(default_factory=dict)


class ExplorationRecipe(BaseModel):
    id: str
    scenario_id: str | None = None
    variant_id: str = "explore-0"
    project_ref: str
    soc_ref: str | None = None
    name: str | None = None
    category: list[str] = Field(default_factory=lambda: ["exploration"])
    source: ExplorationSource
    pipeline: list[ExplorationBlock]
    mapping_profile: MappingProfile | None = None
    design_conditions: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=lambda: ["exploration"])

    @model_validator(mode="after")
    def _validate_recipe(self) -> ExplorationRecipe:
        if not self.pipeline:
            raise ValueError("pipeline must contain at least one exploration block")
        ids = [block.id for block in self.pipeline]
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            raise ValueError(f"duplicate exploration block ids: {duplicates}")
        if self.source.node_id in set(ids):
            raise ValueError(f"source node id collides with pipeline block id: {self.source.node_id}")
        return self


class ExplorationCompileResult(BaseModel):
    scenario: dict[str, Any]
    import_bundle: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    mapping_trace: list[dict[str, Any]] = Field(default_factory=list)


class SweepAxis(BaseModel):
    name: str
    path: str
    values: list[Any]

    @model_validator(mode="after")
    def _validate_axis(self) -> SweepAxis:
        if not self.name.strip():
            raise ValueError("axis name must not be empty")
        if not self.path.strip():
            raise ValueError("axis path must not be empty")
        if not self.values:
            raise ValueError("axis values must not be empty")
        return self


class ExplorationSweep(BaseModel):
    id: str
    base_recipe: ExplorationRecipe
    axes: list[SweepAxis] = Field(default_factory=list)
    merge_variants: bool = True


class ExplorationSweepResult(BaseModel):
    import_bundle: dict[str, Any]
    cases: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def compile_exploration_recipe(recipe: ExplorationRecipe) -> ExplorationCompileResult:
    """Compile an early architecture exploration recipe into scenario YAML."""

    warnings: list[str] = []
    mapping_trace: list[dict[str, Any]] = []
    scenario_id = recipe.scenario_id or f"uc-{recipe.id}"
    source_node = _source_node(recipe)
    nodes = [source_node]
    edges: list[dict[str, Any]] = []
    buffers: dict[str, dict[str, Any]] = {}
    node_configs: dict[str, Any] = {}
    previous_node = source_node["id"]
    previous_output = ExplorationPort(type="COUT", format=recipe.source.format, bitwidth=recipe.source.bitwidth, compression=recipe.source.compression)

    for block in recipe.pipeline:
        mapping = _mapping_for_block(recipe.mapping_profile, block)
        ip_ref = block.ip_ref or mapping.target_ip_ref or mapping.source_ip_ref
        if not ip_ref:
            ip_ref = f"ip-{block.template}"
            warnings.append(f"{block.id}: ip_ref is not mapped; using placeholder {ip_ref}.")
        role = block.role or mapping.target_role or mapping.source_role or block.template
        nodes.append({"id": block.id, "ip_ref": ip_ref, "role": role, "instance_index": 0})
        inputs = block.inputs or [ExplorationPort(type="CIN")]
        outputs = block.outputs or [ExplorationPort(type="COUT")]
        first_input = inputs[0]
        edge_kind = _edge_kind(previous_output, first_input)
        edge: dict[str, Any] = {"from": previous_node, "to": block.id, "type": edge_kind}
        if edge_kind in {"M2M", "vOTF"}:
            buffer_id = f"{previous_node}_{block.id}_BUF".upper()
            edge["buffer"] = buffer_id
            buffers[buffer_id] = _buffer_descriptor(previous_output, recipe.source)
        edges.append(edge)

        sim_block = _sim_block_for_block(block, inputs, outputs, mapping)
        node_configs[block.id] = {
            "selected_mode": block.selected_mode or mapping.mode,
            "sim": sim_block,
        }
        mapping_trace.append(
            {
                "node_id": block.id,
                "template": block.template,
                "ip_ref": ip_ref,
                "role": role,
                "mapping_confidence": mapping.confidence,
                "source_ip_ref": mapping.source_ip_ref,
                "source_role": mapping.source_role,
                "scale": mapping.scale,
            }
        )
        previous_node = block.id
        previous_output = outputs[0]

    design_conditions = {
        "fps": recipe.source.fps,
        "resolution_size": f"{recipe.source.width}x{recipe.source.height}",
        "format": recipe.source.format,
        **recipe.design_conditions,
    }
    if recipe.soc_ref:
        design_conditions.setdefault("soc_ref", recipe.soc_ref)

    scenario = {
        "id": scenario_id,
        "schema_version": "2.2",
        "kind": "scenario.usecase",
        "project_ref": recipe.project_ref,
        "metadata": {
            "name": recipe.name or recipe.id.replace("-", " ").title(),
            "category": list(recipe.category),
            "domain": list(recipe.category),
        },
        "pipeline": {
            "nodes": nodes,
            "edges": edges,
            "buffers": buffers,
        },
        "variants": [
            {
                "id": recipe.variant_id,
                "severity": "medium",
                "design_conditions": design_conditions,
                "node_configs": node_configs,
                "tags": recipe.tags,
            }
        ],
    }
    import_bundle = {
        "kind": "scenario.import_bundle",
        "documents": [scenario],
        "import_report": {
            "ok": True,
            "generated": {
                "scenario_usecase": 1,
                "scenario_variant": 1,
                "exploration_recipe": 1,
            },
            "messages": [
                {"level": "warning", "code": "exploration_compile_warning", "message": message}
                for message in warnings
            ],
        },
    }
    return ExplorationCompileResult(
        scenario=scenario,
        import_bundle=import_bundle,
        warnings=warnings,
        mapping_trace=mapping_trace,
    )


def compile_exploration_sweep(sweep: ExplorationSweep) -> ExplorationSweepResult:
    """Expand a recipe sweep into one or more canonical scenario documents."""

    recipes = _expand_sweep_recipes(sweep)
    compiled = [compile_exploration_recipe(recipe) for recipe in recipes]
    warnings = [warning for result in compiled for warning in result.warnings]
    if sweep.merge_variants and _pipelines_are_equal(compiled):
        scenario = deepcopy(compiled[0].scenario)
        scenario["variants"] = [deepcopy(result.scenario["variants"][0]) for result in compiled]
        documents = [scenario]
    else:
        documents = [result.scenario for result in compiled]
    import_bundle = {
        "kind": "scenario.import_bundle",
        "documents": documents,
        "import_report": {
            "ok": not warnings,
            "generated": {
                "scenario_usecase": len(documents),
                "scenario_variant": len(compiled),
                "exploration_sweep_case": len(compiled),
            },
            "messages": [
                {"level": "warning", "code": "exploration_sweep_warning", "message": message}
                for message in warnings
            ],
        },
    }
    return ExplorationSweepResult(
        import_bundle=import_bundle,
        cases=[
            {
                "case_id": recipe.variant_id,
                "scenario_id": compiled_result.scenario["id"],
                "variant_id": recipe.variant_id,
                "axis_values": _axis_values_for_case(sweep.axes, recipe),
                "mapping_trace": compiled_result.mapping_trace,
            }
            for recipe, compiled_result in zip(recipes, compiled, strict=True)
        ],
        warnings=warnings,
    )


def _source_node(recipe: ExplorationRecipe) -> dict[str, Any]:
    ip_ref = recipe.source.ip_ref
    if not ip_ref and recipe.mapping_profile:
        ip_ref = recipe.mapping_profile.external_mappings.get("default_sensor")
    return {
        "id": recipe.source.node_id,
        "ip_ref": ip_ref or "ip-exploration-sensor",
        "role": recipe.source.type,
        "instance_index": 0,
    }


def _expand_sweep_recipes(sweep: ExplorationSweep) -> list[ExplorationRecipe]:
    if not sweep.axes:
        return [sweep.base_recipe]
    raw_base = sweep.base_recipe.model_dump(mode="json", exclude_none=True)
    cases: list[tuple[dict[str, Any], list[str]]] = [(raw_base, [])]
    for axis in sweep.axes:
        expanded: list[tuple[dict[str, Any], list[str]]] = []
        for raw, suffixes in cases:
            for value in axis.values:
                item = deepcopy(raw)
                _set_path(item, axis.path, value)
                expanded.append((item, [*suffixes, f"{axis.name}-{_safe_id(value)}"]))
        cases = expanded
    recipes: list[ExplorationRecipe] = []
    base_variant = sweep.base_recipe.variant_id
    for raw, suffixes in cases:
        raw["variant_id"] = f"{base_variant}-{'-'.join(suffixes)}" if suffixes else base_variant
        recipes.append(ExplorationRecipe.model_validate(raw))
    return recipes


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = _path_parts(path)
    current: Any = target
    for part in parts[:-1]:
        if isinstance(part, int):
            current = current[part]
        else:
            current = current.setdefault(part, {})
    last = parts[-1]
    if isinstance(last, int):
        current[last] = value
    else:
        current[last] = value


def _path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for token in path.split("."):
        rest = token
        while "[" in rest and "]" in rest:
            name, tail = rest.split("[", 1)
            if name:
                parts.append(name)
            index, rest = tail.split("]", 1)
            parts.append(int(index))
        if rest:
            parts.append(rest)
    return parts


def _pipelines_are_equal(results: list[ExplorationCompileResult]) -> bool:
    if not results:
        return True
    first = results[0].scenario.get("pipeline")
    return all(result.scenario.get("pipeline") == first for result in results)


def _axis_values_for_case(axes: list[SweepAxis], recipe: ExplorationRecipe) -> dict[str, Any]:
    raw = recipe.model_dump(mode="json", exclude_none=True)
    return {axis.name: _get_path(raw, axis.path) for axis in axes}


def _get_path(source: dict[str, Any], path: str) -> Any:
    current: Any = source
    for part in _path_parts(path):
        current = current[part] if isinstance(part, int) else current.get(part)
    return current


def _safe_id(value: Any) -> str:
    text = str(value).lower().replace(".", "p")
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text).strip("-")


def _mapping_for_block(profile: MappingProfile | None, block: ExplorationBlock) -> MappingEntry:
    if profile is None:
        return MappingEntry()
    for key in (block.template, block.role or "", block.id):
        if key and key in profile.role_mappings:
            return profile.role_mappings[key]
    return MappingEntry()


def _edge_kind(output: ExplorationPort, input_: ExplorationPort) -> str:
    output_type = output.type
    input_type = input_.type
    if output_type in {"COUT", "OTF_OUT"} and input_type in {"CIN", "OTF_IN"}:
        return "OTF"
    if output_type == "COUT" and input_type == "RDMA":
        return "vOTF"
    return "M2M"


def _buffer_descriptor(port: ExplorationPort, source: ExplorationSource) -> dict[str, Any]:
    return {
        "size": [
            0,
            0,
            port.width or source.width,
            port.height or source.height,
        ],
        "format": port.format or source.format,
        "bitdepth": port.bitwidth or source.bitwidth,
        "compression": port.compression or source.compression,
    }


def _sim_block_for_block(
    block: ExplorationBlock,
    inputs: list[ExplorationPort],
    outputs: list[ExplorationPort],
    mapping: MappingEntry,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "inherit_shape": True,
        "inputs": [_port_config(port, direction="input") for port in inputs],
        "outputs": [_port_config(port, direction="output") for port in outputs],
    }
    if block.crop:
        result["crop"] = block.crop
    if block.scale:
        result["scale"] = block.scale
    if block.output_format:
        result["output_format"] = block.output_format
    ip_params = {**mapping.ip_params, **block.ip_params}
    if mapping.scale != 1.0 and ip_params.get("unit_power_mw_mp") is not None:
        ip_params["unit_power_mw_mp"] = float(ip_params["unit_power_mw_mp"]) * mapping.scale
    if ip_params:
        result["ip_params"] = ip_params
    result["mapping_source"] = {
        "confidence": mapping.confidence,
        "source_ip_ref": mapping.source_ip_ref,
        "source_role": mapping.source_role,
        "scale": mapping.scale,
    }
    return result


def _port_config(port: ExplorationPort, *, direction: str) -> dict[str, Any]:
    default_name = "RDMA" if direction == "input" else "WDMA"
    result: dict[str, Any] = {
        "port": port.port or default_name,
        "port_type": _port_type(port),
    }
    for key in ("width", "height", "format", "bitwidth", "compression", "comp_ratio", "llc_enabled"):
        value = getattr(port, key)
        if value is not None:
            result[key] = value
    return result


def _port_type(port: ExplorationPort) -> str:
    if port.type == "RDMA":
        return "DMA_READ"
    if port.type == "WDMA":
        return "DMA_WRITE"
    if port.type in {"CIN", "OTF_IN"}:
        return "OTF_IN"
    if port.type in {"COUT", "OTF_OUT"}:
        return "OTF_OUT"
    return "DMA_READ"
