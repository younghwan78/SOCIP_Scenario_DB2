"""Scenario overlays for derived projects (e.g. a new SoC with a changed pipeline).

``overlay.yaml`` (in ``projects/<child>/scenarios/<parent uc id>/``)::

    kind: authoring.scenario_overlay
    scenario_patch: {...}            # deep-merge on the base document (not variants)
    pipeline:
      remove_nodes: [msnr]           # also drops edges touching them
      add_nodes: [{id: ..., ip_ref: ..., role: ...}]
      set_nodes: {mtnr: {ip_ref: ip-mtnr-v2-...}}   # deep-merge per node (IP rebinding)
      remove_edges: [{from: a, to: b}]              # match on given keys
      add_edges: [{from: a, to: b, type: M2M, buffer: X, port_pairs: [...]}]
      add_buffers: {NAME: {...}}
      remove_buffers: [NAME]
      rename_ports: {OLD_PORT: NEW_PORT}            # edges, variant topology, active ports
    variants:
      remove: [variant ids]
      patch: {variant id: {...}}                    # deep-merge on the compact entry
      add: [{id: ..., extends: ..., ...}]
      patch_resolved:                               # bulk deep-merge AFTER `extends` expansion
      - variants: '*'            # or [ids]; exclude: [ids]
        when: {stabilization: [null, false]}        # design_conditions match (list = any of)
        when_node_enabled: eis   # / when_node_disabled: eis
        patch: {routing_switch: {$remove: {disabled_nodes: [eis]}}}
      keep: [variant ids]    # scope: only these reach the compiled output (in this order);
                             # every other variant stays a template for `extends`
    sizes: {bindings: {...}, derived: {...}}        # deep-merge on sizes.yaml
    sw_timing: {tasks: {...}}                       # deep-merge on sw_timing.yaml
    knobs: {params: {...}, knobs: {...}}            # deep-merge on knobs.yaml
    prune_missing_nodes: false   # true: drop variant refs to removed nodes (reported)
"""

from __future__ import annotations

import copy
from typing import Any

from scenario_db.authoring.patch import deep_merge
from scenario_db.authoring.errors import AuthoringError


def _rename_exact(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_rename_exact(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: _rename_exact(v, mapping) for k, v in value.items()}
    return value


def _edge_match(edge: dict, sel: dict) -> bool:
    return all(edge.get(k) == v for k, v in sel.items())


def apply_pipeline_ops(base: dict, variants: list[dict], ops: dict) -> tuple[dict, list[dict]]:
    base = copy.deepcopy(base)
    pipe = base.setdefault("pipeline", {})
    nodes = pipe.setdefault("nodes", [])
    edges = pipe.setdefault("edges", [])
    removed = set(ops.get("remove_nodes") or [])
    unknown = removed - {n["id"] for n in nodes}
    if unknown:
        raise AuthoringError(f"remove_nodes: unknown nodes {sorted(unknown)}")
    nodes[:] = [n for n in nodes if n["id"] not in removed]
    edges[:] = [e for e in edges if e.get("from") not in removed and e.get("to") not in removed]
    for node in ops.get("add_nodes") or []:
        if any(n["id"] == node["id"] for n in nodes):
            raise AuthoringError(f"add_nodes: node '{node['id']}' already exists")
        nodes.append(copy.deepcopy(node))
    for nid, patch in (ops.get("set_nodes") or {}).items():
        idx = next((i for i, n in enumerate(nodes) if n["id"] == nid), None)
        if idx is None:
            raise AuthoringError(f"set_nodes: unknown node '{nid}'")
        nodes[idx] = deep_merge(nodes[idx], patch)
    for sel in ops.get("remove_edges") or []:
        before = len(edges)
        edges[:] = [e for e in edges if not _edge_match(e, sel)]
        if len(edges) == before:
            raise AuthoringError(f"remove_edges: no edge matches {sel}")
    edges.extend(copy.deepcopy(ops.get("add_edges") or []))
    buffers = pipe.setdefault("buffers", {})
    for name in ops.get("remove_buffers") or []:
        buffers.pop(name, None)
    buffers.update(copy.deepcopy(ops.get("add_buffers") or {}))
    ports = ops.get("rename_ports") or {}
    if ports:
        pipe["edges"] = _rename_exact(pipe["edges"], ports)
        variants = [_rename_exact(v, ports) for v in variants]
    return base, variants


def apply_overlay(sources: dict, overlay: dict) -> dict:
    out = copy.deepcopy(sources)
    variants_ref = out["base"].get("variants")
    base_wo = {k: v for k, v in out["base"].items() if k != "variants"}
    base_wo = deep_merge(base_wo, overlay.get("scenario_patch") or {})
    variants = out["variants"]
    if overlay.get("pipeline"):
        base_wo, variants = apply_pipeline_ops(base_wo, variants, overlay["pipeline"])
    vops = overlay.get("variants") or {}
    remove = set(vops.get("remove") or [])
    variants = [v for v in variants if v["id"] not in remove]
    by_id = {v["id"]: i for i, v in enumerate(variants)}
    for vid, patch in (vops.get("patch") or {}).items():
        if vid not in by_id:
            raise AuthoringError(f"variants.patch: unknown variant '{vid}'")
        variants[by_id[vid]] = deep_merge(variants[by_id[vid]], patch)
    variants.extend(copy.deepcopy(vops.get("add") or []))
    if vops.get("patch_resolved"):
        out["variant_patches"] = [*(out.get("variant_patches") or []), *copy.deepcopy(vops["patch_resolved"])]
    dangling = [v["id"] for v in variants if v.get("extends") in remove]
    if dangling:
        raise AuthoringError(f"variants.remove leaves children without parent: {dangling} "
                             "(re-point them with variants.patch.<id>.extends or remove them too)")
    if vops.get("keep") is not None:
        keep = list(vops["keep"])
        unknown = [vid for vid in keep if vid not in {v["id"] for v in variants}]
        if unknown or len(set(keep)) != len(keep):
            raise AuthoringError(f"variants.keep: unknown or duplicate variant ids {unknown or keep}")
        out["keep"] = keep
    base = dict(base_wo)
    if "variants" in sources["base"]:
        base["variants"] = variants_ref
    out["base"] = base
    out["variants"] = variants
    out["sizes"] = deep_merge(out.get("sizes") or {}, overlay.get("sizes") or {})
    out["sw_timing"] = deep_merge(out.get("sw_timing") or {}, overlay.get("sw_timing") or {})
    out["knobs"] = deep_merge(out.get("knobs") or {}, overlay.get("knobs") or {})
    return out


def _variant_known_nodes(base_ids: set[str], variant: dict, by_id: dict[str, dict]) -> set[str]:
    known = set(base_ids)
    seen: set[str] = set()
    cur: dict | None = variant
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        for n in ((cur.get("topology_patch") or {}).get("add_nodes") or []):
            if isinstance(n, dict) and n.get("id"):
                known.add(n["id"])
        cur = by_id.get(cur.get("derived_from_variant") or "")
    return known


def prune_or_report_missing_nodes(doc: dict, prune: bool) -> list[str]:
    """Find variant references to nodes absent from pipeline + topology_patch.add_nodes.

    This is the impact analysis after a pipeline change (removed/renamed nodes).
    """
    base_ids = {n["id"] for n in (doc.get("pipeline") or {}).get("nodes") or []}
    variants = doc.get("variants") or []
    by_id = {v["id"]: v for v in variants}
    findings: list[str] = []
    for v in variants:
        vid = v["id"]
        node_ids = _variant_known_nodes(base_ids, v, by_id)
        cfgs = v.get("node_configs") or {}
        for n in [n for n in cfgs if n not in node_ids]:
            findings.append(f"{vid}: node_configs.{n}")
            if prune:
                del cfgs[n]
        rs = v.get("routing_switch") or {}
        dis = rs.get("disabled_nodes") or []
        missing = [n for n in dis if n not in node_ids]
        for n in missing:
            findings.append(f"{vid}: routing_switch.disabled_nodes[{n}]")
        if prune and missing:
            rs["disabled_nodes"] = [n for n in dis if n in node_ids]
        tp = v.get("topology_patch") or {}
        for key in ("add_edges", "remove_edges"):
            edges = tp.get(key) or []
            bad = [e for e in edges if e.get("from") not in node_ids or e.get("to") not in node_ids]
            for e in bad:
                findings.append(f"{vid}: topology_patch.{key}[{e.get('from')}->{e.get('to')}]")
            if prune and bad:
                tp[key] = [e for e in edges if e not in bad]
    if findings and not prune:
        raise AuthoringError(
            f"scenario '{doc.get('id')}': {len(findings)} variant reference(s) to nodes missing from the "
            "pipeline:\n  " + "\n  ".join(findings[:40])
            + ("\n  ..." if len(findings) > 40 else "")
            + "\nFix the overlay or set prune_missing_nodes: true to drop them (reported).")
    return findings
