"""Scenario (scenario.usecase) layer: base + compact variants + side tables.

Authoring directory for one scenario::

    <scenario_dir>/
      scenario.yaml    base document; ``variants: {$include: variants.yaml}``
      variants.yaml    compact variants: full "root" entries or
                       ``extends: <variant id>`` + deep-merge patch
      sizes.yaml       node -> size-anchor bindings (+ optional derived anchors)
      sw_timing.yaml   SW task timing table (grouped by identical values)

Compile order per variant:
    expand ``extends`` -> overlay ``patch_resolved`` -> derived anchors -> knobs -> size bindings
    -> sw_timing
"""

from __future__ import annotations

import copy
import json
import math
from collections import OrderedDict
from pathlib import Path
from typing import Any

from scenario_db.authoring import yamlio
from scenario_db.authoring.errors import AuthoringError
from scenario_db.authoring.knobs import (
    KnobError,
    apply_knobs,
    compute_anchor,
    derived_in_dependency_order,
    knob_bound_nodes,
)
from scenario_db.authoring.patch import deep_merge, make_patch

INCLUDE = "$include"
EXTENDS = "extends"
ALL = "*"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _cost(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def parse_size(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or "x" not in value:
        return None
    w, _, h = value.partition("x")
    try:
        return int(w), int(h)
    except ValueError:
        return None


def resolved_anchors(doc: dict, variant: dict) -> dict[str, str]:
    anchors = dict(((doc.get("size_profile") or {}).get("anchors") or {}))
    anchors.update(variant.get("size_overrides") or {})
    return anchors


# ---------------------------------------------------------------------------
# decompile
# ---------------------------------------------------------------------------

def _extract_sw_timing(variants: list[dict]) -> dict:
    per_task: "OrderedDict[str, OrderedDict[str, dict]]" = OrderedDict()
    present: dict[str, set[str]] = {}
    for v in variants:
        for node, cfg in list((v.get("node_configs") or {}).items()):
            if not isinstance(cfg, dict) or "sw_timing" not in cfg:
                continue
            timing = cfg.pop("sw_timing")
            if not cfg:
                del v["node_configs"][node]
            groups = per_task.setdefault(node, OrderedDict())
            k = _key(timing)
            groups.setdefault(k, {"timing": timing, "variants": []})["variants"].append(v["id"])
            present.setdefault(node, set()).add(v["id"])
    all_ids = [v["id"] for v in variants]
    tasks: dict[str, Any] = {}
    for task, groups in per_task.items():
        glist = list(groups.values())
        biggest = max(glist, key=lambda g: len(g["variants"]))
        absent = [vid for vid in all_ids if vid not in present[task]]
        out_groups = []
        for idx, g in enumerate(glist):
            entry: dict[str, Any] = {"id": f"{task}-{chr(ord('a') + idx) if idx < 26 else idx}"}
            use_all = g is biggest  # groups partition present variants
            entry["variants"] = ALL if use_all else g["variants"]
            entry["timing"] = g["timing"]
            out_groups.append(entry)
        task_entry: dict[str, Any] = {"groups": out_groups}
        if absent:
            task_entry["absent_in"] = absent
        tasks[task] = task_entry
    return {"known_variants": all_ids, "tasks": tasks}


def _extract_sizes(doc: dict, variants: list[dict], knobs: dict | None = None,
                   previous: dict | None = None) -> dict:
    """Infer node->anchor bindings. Rows a knob overwrites are skipped (and stripped);
    a binding already chosen in ``previous`` (human-reviewed sizes.yaml) wins when still valid."""
    per_node: "OrderedDict[str, list[tuple[dict, dict]]]" = OrderedDict()
    for v in variants:
        if v.get("derived_from_variant"):
            continue  # runtime-derived variants inherit sizes from their parent
        knob_nodes = knob_bound_nodes(knobs or {}, v)
        for node, cfg in (v.get("node_configs") or {}).items():
            if node in knob_nodes and isinstance(cfg, dict) and isinstance(cfg.get("sim"), dict):
                cfg["sim"].pop("width", None)
                cfg["sim"].pop("height", None)
                continue
            if isinstance(cfg, dict) and isinstance(cfg.get("sim"), dict):
                per_node.setdefault(node, []).append((v, cfg["sim"]))
    bindings: dict[str, str] = {}
    alternatives: dict[str, list[str]] = {}
    for node, rows in per_node.items():
        if not all(isinstance(s.get("width"), int) and isinstance(s.get("height"), int) for _, s in rows):
            continue
        candidates: list[str] | None = None
        for v, sim in rows:
            anchors = resolved_anchors(doc, v)
            ok = [a for a, val in anchors.items() if parse_size(val) == (sim["width"], sim["height"])]
            candidates = ok if candidates is None else [a for a in candidates if a in ok]
            if not candidates:
                break
        if candidates:
            prev = ((previous or {}).get("bindings") or {}).get(node)
            chosen = prev if prev in candidates else candidates[0]
            bindings[node] = chosen
            rest = [c for c in candidates if c != chosen]
            if rest:
                alternatives[node] = rest
    for node in bindings:
        for _, sim in per_node[node]:
            sim.pop("width", None)
            sim.pop("height", None)
    out: dict[str, Any] = {"bindings": bindings}
    if alternatives:
        out["alternatives"] = alternatives
    out["derived"] = dict((previous or {}).get("derived") or {})
    return out


def _compact_variants(variants: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i, v in enumerate(variants):
        root_cost = _cost(v)
        best: tuple[int, str, dict] | None = None
        for prev in variants[:i]:
            p = make_patch(prev, v) or {}
            p.pop("id", None)
            c = _cost(p)
            if best is None or c < best[0]:
                best = (c, prev["id"], p)
        if best is not None and best[0] < root_cost * 0.9:
            entry = {"id": v["id"], EXTENDS: best[1]}
            entry.update(best[2])
            out.append(entry)
        else:
            out.append(copy.deepcopy(v))
    return out


GENERATED_FILES = ("scenario.yaml", "variants.yaml", "sizes.yaml", "sw_timing.yaml")


def decompile_usecase(doc: dict, out_dir: Path) -> dict[str, int]:
    """Write generated sources; hand-authored files (knobs.yaml, overlay.yaml,
    sw_timing.measured.yaml) are kept, and reviewed size bindings are preserved."""
    doc = copy.deepcopy(doc)
    doc.pop("power_options", None)  # generated from the hand-authored knobs.yaml
    variants = doc.get("variants") or []
    knobs = yamlio.load(out_dir / "knobs.yaml") if (out_dir / "knobs.yaml").exists() else None
    previous = yamlio.load(out_dir / "sizes.yaml") if (out_dir / "sizes.yaml").exists() else None
    sw_timing = _extract_sw_timing(variants)
    sizes = _extract_sizes(doc, variants, knobs, previous)
    compact = _compact_variants(variants)
    base = {}
    for k, v in doc.items():
        base[k] = {INCLUDE: "variants.yaml"} if k == "variants" else v
    yamlio.dump(out_dir / "scenario.yaml", base,
                header="Base scenario (pipeline, anchors, metadata). Variants live in variants.yaml.")
    yamlio.dump(out_dir / "variants.yaml", compact,
                header="Compact variants: root entries are complete; `extends: <id>` entries are a\n"
                       "deep-merge patch over that variant (`$unset: [keys]` removes keys).\n"
                       "node sim width/height come from sizes.yaml; sw_timing from sw_timing.yaml.")
    yamlio.dump(out_dir / "sizes.yaml", sizes,
                header="Node -> size anchor bindings. Bound nodes get sim.width/height from the\n"
                       "variant's resolved anchors (size_profile.anchors + size_overrides).\n"
                       "`alternatives` lists other anchors that matched in every variant (review!).\n"
                       "`derived` anchors are computed per variant, e.g.\n"
                       "  eis_in: {from: record_out, scale: 1.15, align: 16}")
    yamlio.dump(out_dir / "sw_timing.yaml", sw_timing,
                header="SW task timing table. `variants: '*'` = every variant not listed in another\n"
                       "group and not in absent_in. Measured overrides go in the project's\n"
                       "sw_timing.measured.yaml, not here.")
    return {"variants": len(variants), "roots": sum(1 for e in compact if EXTENDS not in e)}


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

def load_scenario_sources(src_dir: Path) -> dict[str, Any]:
    base = yamlio.load(src_dir / "scenario.yaml")
    variants_ref = base.get("variants")
    variants: list[dict] = []
    if isinstance(variants_ref, dict) and INCLUDE in variants_ref:
        variants = yamlio.load(src_dir / variants_ref[INCLUDE]) or []
    elif isinstance(variants_ref, list):
        variants = variants_ref
    sizes = yamlio.load(src_dir / "sizes.yaml") if (src_dir / "sizes.yaml").exists() else {}
    sw = yamlio.load(src_dir / "sw_timing.yaml") if (src_dir / "sw_timing.yaml").exists() else {}
    knobs = yamlio.load(src_dir / "knobs.yaml") if (src_dir / "knobs.yaml").exists() else {}
    return {"base": base, "variants": variants, "sizes": sizes or {}, "sw_timing": sw or {},
            "knobs": knobs or {}}


def variant_parents(entries: list[dict]) -> dict[str, str | None]:
    return {e["id"]: e.get(EXTENDS) for e in entries}


def expand_variants(entries: list[dict]) -> list[dict]:
    by_id = {e["id"]: e for e in entries}
    if len(by_id) != len(entries):
        raise AuthoringError("duplicate variant ids in variants.yaml")
    cache: dict[str, dict] = {}

    def resolve(vid: str, stack: tuple[str, ...]) -> dict:
        if vid in cache:
            return cache[vid]
        if vid in stack:
            raise AuthoringError(f"variant extends cycle: {' -> '.join(stack + (vid,))}")
        if vid not in by_id:
            raise AuthoringError(f"variant '{stack[-1]}' extends unknown variant '{vid}'")
        entry = copy.deepcopy(by_id[vid])
        parent = entry.pop(EXTENDS, None)
        if parent is None:
            full = entry
        else:
            full = deep_merge(resolve(parent, stack + (vid,)), entry)
            full["id"] = vid
        cache[vid] = full
        return full

    return [copy.deepcopy(resolve(e["id"], ())) for e in entries]


def apply_derived_anchors(doc: dict, variant: dict, derived: dict) -> None:
    """sizes.yaml ``derived``: per-variant anchors computed from other anchors.

    Same rule keys as knob anchors (``from``, ``scale``/``scale_x``/``scale_y`` number or
    expression, ``align``/``align_x``/``align_y``, ``round: ceil|nearest``, ``clamp_to``),
    resolved in dependency order. A variant's own size_overrides entry wins unless ``force``.
    """
    for name, rule in derived_in_dependency_order(derived or {}):
        own = variant.get("size_overrides") or {}
        if name in own and not rule.get("force"):
            continue
        try:
            value = compute_anchor(rule, resolved_anchors(doc, variant), {}, name)
        except KnobError as exc:
            raise AuthoringError(f"derived anchor '{name}' in variant '{variant['id']}': {exc}") from exc
        variant.setdefault("size_overrides", {})[name] = value


def apply_size_bindings(doc: dict, variant: dict, bindings: dict[str, str]) -> None:
    if variant.get("derived_from_variant"):
        return  # runtime inheritance (ETL/API resolves sizes from the parent variant)
    anchors = resolved_anchors(doc, variant)
    for node, cfg in (variant.get("node_configs") or {}).items():
        anchor = bindings.get(node)
        if not anchor or not isinstance(cfg, dict) or not isinstance(cfg.get("sim"), dict):
            continue
        sim = cfg["sim"]
        if "width" in sim and "height" in sim:
            continue  # explicit literal wins
        wh = parse_size(anchors.get(anchor))
        if wh is None:
            raise AuthoringError(f"variant '{variant['id']}' node '{node}': anchor '{anchor}' unresolved")
        sim["width"], sim["height"] = wh


def select_variants(spec: Any, all_ids: list[str], variants: list[dict] | None = None,
                    when: dict | None = None) -> list[str]:
    ids = list(all_ids) if spec in (None, ALL) else [i for i in all_ids if i in set(spec)]
    if when and variants is not None:
        cond = {v["id"]: v.get("design_conditions") or {} for v in variants}
        ids = [i for i in ids if all(cond[i].get(k) == val for k, val in when.items())]
    return ids


def sw_timing_group_targets(table: dict, ids: list[str],
                            parents: dict[str, str | None] | None = None) -> dict[tuple[str, str], list[str]]:
    """(task, group id) -> variant ids the group applies to.

    Variants unknown to the table (added later, e.g. by an overlay) inherit the
    membership of their ``extends`` parent; unknown root variants fall into '*'.
    """
    out: dict[tuple[str, str], list[str]] = {}
    known_list = table.get("known_variants")
    known = set(known_list) if known_list is not None else set(ids)
    parents = parents or {}
    for task, spec in (table.get("tasks") or {}).items():
        absent = set(spec.get("absent_in") or [])
        member: dict[str, str | None] = {}
        star = None
        for g in spec.get("groups", []):
            if g.get("variants") == ALL:
                star = g["id"]
            else:
                for vid in g["variants"]:
                    member[vid] = g["id"]

        def group_of(vid: str, depth: int = 0) -> str | None:
            if vid in known or depth > 32:
                if vid in absent:
                    return None
                return member.get(vid, star)
            parent = parents.get(vid)
            return group_of(parent, depth + 1) if parent else star

        for g in spec.get("groups", []):
            out[(task, g["id"])] = []
        for vid in ids:
            gid = group_of(vid)
            if gid is not None:
                out[(task, gid)].append(vid)
    return out


def apply_sw_timing(variants: list[dict], table: dict, parents: dict[str, str | None] | None = None) -> None:
    by_id = {v["id"]: v for v in variants}
    groups = {(t, g["id"]): g for t, spec in (table.get("tasks") or {}).items() for g in spec.get("groups", [])}
    for (task, gid), targets in sw_timing_group_targets(table, list(by_id), parents).items():
        for vid in targets:
            cfgs = by_id[vid].setdefault("node_configs", {})
            cfgs.setdefault(task, {})["sw_timing"] = copy.deepcopy(groups[(task, gid)]["timing"])


def apply_sw_measurements(variants: list[dict], measured: dict, table: dict | None = None,
                          parents: dict[str, str | None] | None = None) -> dict[str, int]:
    """Apply ``sw_timing.measured.yaml`` entries (in order; later entries win).

    Scope: ``group`` (a sw_timing.yaml group id) and/or ``variants`` (list or '*')
    and/or ``when`` (design_conditions match). ``timing: null`` = pending slot.
    ``mode: merge`` (default) patches existing sw_timing only; ``replace`` sets it.
    """
    stats = {"applied": 0, "pending": 0}
    ids = [v["id"] for v in variants]
    by_id = {v["id"]: v for v in variants}
    group_targets = sw_timing_group_targets(table or {}, ids, parents)
    for entry in (measured or {}).get("entries") or []:
        if entry.get("timing") is None:
            stats["pending"] += 1
            continue
        task = entry["task"]
        targets = select_variants(entry.get("variants", ALL), ids, variants, entry.get("when"))
        if entry.get("group"):
            key = (task, entry["group"])
            if key not in group_targets:
                raise AuthoringError(f"sw_timing measurement: unknown group '{entry['group']}' for task '{task}'")
            scope = set(group_targets[key])
            targets = [t for t in targets if t in scope]
        mode = entry.get("mode", "merge")
        for vid in targets:
            cfg = (by_id[vid].get("node_configs") or {}).get(task)
            if mode == "merge" and not (cfg and "sw_timing" in cfg):
                continue  # only override tasks that exist in that variant
            node = by_id[vid].setdefault("node_configs", {}).setdefault(task, {})
            base = node.get("sw_timing") or {}
            node["sw_timing"] = deep_merge(base, entry["timing"]) if mode == "merge" else copy.deepcopy(entry["timing"])
        stats["applied"] += 1
    return stats


def select_scope(variants: list[dict], keep: list[str] | None) -> list[dict]:
    """Overlay ``variants.keep``: emit only these (in that order). The others were
    expanded as ``extends`` templates only; a kept runtime-derived variant must keep its parent."""
    if keep is None:
        return variants
    by_id = {v["id"]: v for v in variants}
    out = [by_id[vid] for vid in keep]
    orphans = [v["id"] for v in out if v.get("derived_from_variant") and v["derived_from_variant"] not in keep]
    if orphans:
        raise AuthoringError(f"variants.keep drops the derived_from_variant parent of {orphans}")
    return out


def _resolved_match(variant: dict, rule: dict) -> bool:
    ids = rule.get("variants", ALL)
    if ids != ALL and variant["id"] not in set(ids):
        return False
    if variant["id"] in set(rule.get("exclude") or []):
        return False
    disabled = set((variant.get("routing_switch") or {}).get("disabled_nodes") or [])
    if rule.get("when_node_enabled") and rule["when_node_enabled"] in disabled:
        return False
    if rule.get("when_node_disabled") and rule["when_node_disabled"] not in disabled:
        return False
    conds = variant.get("design_conditions") or {}
    for key, want in (rule.get("when") or {}).items():
        have = conds.get(key)
        if (have not in want) if isinstance(want, list) else (have != want):
            return False
    return True


def apply_resolved_patches(variants: list[dict], rules: list[dict]) -> dict[str, list[str]]:
    """Overlay ``variants.patch_resolved``: deep-merge on fully expanded variants (so
    ``$remove`` / ``$items`` see inherited lists). A rule that selects nothing is an error."""
    hits: dict[str, list[str]] = {}
    known = {v["id"] for v in variants}
    for i, rule in enumerate(rules or []):
        if "patch" not in rule:
            raise AuthoringError(f"patch_resolved[{i}]: 'patch' is required")
        ids = rule.get("variants", ALL)
        unknown = [] if ids == ALL else [x for x in ids if x not in known]
        if unknown:
            raise AuthoringError(f"patch_resolved[{i}]: unknown variants {unknown}")
        selected = []
        for v in variants:
            if _resolved_match(v, rule):
                patched = deep_merge(v, rule["patch"])
                patched["id"] = v["id"]
                v.clear()
                v.update(patched)
                selected.append(v["id"])
        if not selected and not rule.get("allow_empty"):
            raise AuthoringError(f"patch_resolved[{i}] selects no variant: {rule.get('note') or rule}")
        hits[rule.get("note") or f"#{i}"] = selected
    return hits


def compile_usecase(sources: dict[str, Any]) -> dict:
    base = copy.deepcopy(sources["base"])
    variants = expand_variants(sources["variants"])
    keep = sources.get("keep")
    scope = [v for v in variants if keep is None or v["id"] in set(keep)]  # templates stay untouched
    apply_resolved_patches(scope, sources.get("variant_patches") or [])
    sizes = sources.get("sizes") or {}
    base_anchors = dict(((base.get("size_profile") or {}).get("anchors") or {}))
    for v in variants:
        # derived first: knob anchors (e.g. bcrop pyramid) are computed from them and win
        apply_derived_anchors(base, v, sizes.get("derived") or {})
        apply_knobs(base_anchors, v, sources.get("knobs") or {})
        apply_size_bindings(base, v, sizes.get("bindings") or {})
    apply_sw_timing(variants, sources.get("sw_timing") or {}, variant_parents(sources["variants"]))
    variants = select_scope(variants, sources.get("keep"))
    doc = {}
    for k, val in base.items():
        if k == "variants":
            options = power_options_doc(sources.get("knobs") or {})
            if options:
                doc["power_options"] = options
        doc[k] = variants if k == "variants" else val
    if "variants" not in doc and variants:
        doc["variants"] = variants
    return doc


POWER_OPTION_KEYS = ("params", "param_rules", "knobs")


def power_options_doc(knobs: dict) -> dict | None:
    """knobs.yaml -> ``power_options`` of the compiled usecase (runtime knob spec).

    Combination exploration re-applies knob values on top of a formal variant at run
    time, so the DB needs the definitions, not only the variants that select them.
    """
    if not (knobs or {}).get("knobs"):
        return None
    return {k: copy.deepcopy(knobs[k]) for k in POWER_OPTION_KEYS if knobs.get(k)}
