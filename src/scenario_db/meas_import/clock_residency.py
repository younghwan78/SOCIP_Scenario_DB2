"""Clock-domain frequency residency (CPU cluster · DSU · GPU · …) — import side.

A *domain class* (``cpu``, ``gpu``; extend :data:`DOMAIN_CLASSES` for e.g. ``npu``)
names the catalog metrics its residency becomes. A *domain* is one clock inside
a class (``MID_LF0``, ``DSU``, ``GPU``).

Two bases are kept apart:

- ``wall``   time share per frequency over the whole capture (governor view;
  leakage / voltage follow this one),
- ``active`` time share per frequency while the domain is running (not idle);
  dynamic energy per cycle follows this one, because a governor often parks at
  a frequency while the CPU / GPU idles.

Neutral sample metrics (``pmu_digest`` rows, produced by ``table_adapter`` or a
neutral CSV/JSON):

=============================  ==========================================  =====================
sample metric                  observation                                 scope
=============================  ==========================================  =====================
``cpu_freq_time``              ``cpu.freq_residency`` (existing reducer)   cluster_freq
``cpu_freq_time_active``       ``cpu.freq_residency_active``               cluster_freq
``<cls>_freq_time``            ``<cls>.freq_residency``                    ``<cls>_freq``
``<cls>_freq_time_active``     ``<cls>.freq_residency_active``             ``<cls>_freq``
``<cls>_time_<state>``         ``<cls>.<state>_ratio``                     ``<cls>``
=============================  ==========================================  =====================

(``state`` = active / clock_gated / power_gated; for ``cpu`` the existing CPU
profile reducer keeps producing ``cpu.freq_residency`` and the gating ratios.)

Samples may carry a ``group`` (e.g. the PMU pass ``pass1``..``pass3`` of a
capture split to avoid counter multiplexing). Residency is summed over groups
(time-weighted), and the Jensen–Shannon divergence between the groups'
distributions becomes ``clock.residency_pass_jsd`` (scope ``clock_domain``, ref
``<cls>/<domain>``) — a capture-quality signal: the passes should have seen the
same DVFS behaviour.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

PASS_JSD_METRIC = "clock.residency_pass_jsd"
PASS_JSD_SCOPE = "clock_domain"
PASS_JSD_WARN = 0.05
STATES = ("active", "clock_gated", "power_gated")


@dataclass(frozen=True)
class DomainClass:
    name: str                 # sample / metric prefix
    label: str                # UI / report label
    freq_scope: str           # scope kind of the per-frequency residency
    domain_scope: str         # scope kind of the per-domain ratios

    @property
    def residency_metric(self) -> str:
        return f"{self.name}.freq_residency"

    @property
    def active_metric(self) -> str:
        return f"{self.name}.freq_residency_active"

    def ratio_metric(self, state: str) -> str:
        return f"{self.name}.{state}_ratio"


# Add a class here (and its metrics to models/evidence/metric_catalog.yaml) to import a new clock domain.
DOMAIN_CLASSES: dict[str, DomainClass] = {
    "cpu": DomainClass("cpu", "CPU", "cluster_freq", "cluster"),
    "gpu": DomainClass("gpu", "GPU", "gpu_freq", "gpu"),
}


def domain_class(name: str) -> DomainClass:
    try:
        return DOMAIN_CLASSES[name]
    except KeyError as exc:
        raise ValueError(f"unknown clock domain class '{name}' (known: {sorted(DOMAIN_CLASSES)})") from exc


def sample_metric(cls: str, kind: str, *, basis: str = "wall", state: str | None = None) -> str:
    """Neutral sample metric name for a class: kind ``freq`` or ``state``."""
    domain_class(cls)
    if kind == "freq":
        return f"{cls}_freq_time" + ("_active" if basis == "active" else "")
    if state not in STATES:
        raise ValueError(f"unknown residency state '{state}'")
    return f"{cls}_time_{state}"


def _parse(metric: str) -> tuple[str, str, str] | None:
    """(class, 'freq', basis) or (class, 'state', state) for a residency sample metric."""
    cls, _, rest = metric.partition("_")
    if cls not in DOMAIN_CLASSES:
        return None
    if rest == "freq_time":
        return cls, "freq", "wall"
    if rest == "freq_time_active":
        return cls, "freq", "active"
    if rest.startswith("time_") and rest[len("time_"):] in STATES:
        return cls, "state", rest[len("time_"):]
    return None


def handles(metric: str) -> bool:
    """True for residency samples this module reduces (the CPU wall / state samples stay with the CPU profile)."""
    parsed = _parse(metric)
    if parsed is None:
        return False
    cls, kind, what = parsed
    return not (cls == "cpu" and (kind == "state" or what == "wall"))


def observes(metric: str) -> bool:
    """True for every residency sample (also the ones only read for the pass divergence)."""
    return _parse(metric) is not None


def jsd(p: dict[float, float], q: dict[float, float]) -> float:
    """Jensen–Shannon divergence (base 2, 0..1) of two un-normalised distributions."""
    sp, sq = sum(p.values()), sum(q.values())
    if sp <= 0 or sq <= 0:
        return 0.0
    keys = set(p) | set(q)
    pn = {k: p.get(k, 0.0) / sp for k in keys}
    qn = {k: q.get(k, 0.0) / sq for k in keys}

    def kl(a: dict[float, float], m: dict[float, float]) -> float:
        return sum(a[k] * math.log2(a[k] / m[k]) for k in keys if a[k] > 0)

    m = {k: (pn[k] + qn[k]) / 2 for k in keys}
    return max(0.0, min(1.0, (kl(pn, m) + kl(qn, m)) / 2))


def _obs(metric_id: str, kind: str, ref: str, unit: str, value: float) -> dict:
    return {"metric_id": metric_id, "scope": {"kind": kind, "ref": ref}, "unit": unit, "value": value}


def normalise(levels: dict[float, float]) -> dict[float, float]:
    total = sum(v for v in levels.values() if v > 0)
    return {f: v / total for f, v in sorted(levels.items()) if v > 0} if total > 0 else {}


def residency_observations(
    freq: dict[tuple[str, str, str], dict[float, float]],
    states: dict[tuple[str, str], dict[str, float]] | None = None,
    groups: dict[tuple[str, str, str], dict[str, dict[float, float]]] | None = None,
    *,
    emit_cpu_wall: bool = False,
    warnings: list[str] | None = None,
) -> list[dict]:
    """Observations from accumulated time per frequency.

    ``freq``: (class, basis, domain) -> {MHz: time}; ``states``: (class, domain) -> {state: time};
    ``groups``: (class, basis, domain) -> {group: {MHz: time}} (pass divergence).
    The CPU wall residency is emitted only with ``emit_cpu_wall`` (the PMU path has its own reducer).
    """
    out: list[dict] = []
    for (cls, basis, domain), levels in sorted(freq.items()):
        dc = DOMAIN_CLASSES[cls]
        if cls == "cpu" and basis == "wall" and not emit_cpu_wall:
            continue
        metric = dc.active_metric if basis == "active" else dc.residency_metric
        for mhz, share in normalise(levels).items():
            out.append(_obs(metric, dc.freq_scope, f"{domain}@{mhz:g}", "ratio", round(share, 6)))
    for (cls, domain), times in sorted((states or {}).items()):
        if cls == "cpu":
            continue
        dc = DOMAIN_CLASSES[cls]
        total = sum(times.values())
        if total <= 0:
            continue
        for state in STATES:
            if state in times:
                out.append(_obs(dc.ratio_metric(state), dc.domain_scope, domain, "ratio", round(times[state] / total, 6)))
    # one divergence per domain: the worst pair over both bases
    worst: dict[tuple[str, str], tuple[float, str, list[str]]] = {}
    for (cls, basis, domain), by_group in sorted((groups or {}).items()):
        named = {g: v for g, v in by_group.items() if g and sum(v.values()) > 0}
        if len(named) < 2:
            continue
        names = sorted(named)
        value = max(jsd(named[a], named[b]) for i, a in enumerate(names) for b in names[i + 1:])
        if (cls, domain) not in worst or value > worst[(cls, domain)][0]:
            worst[(cls, domain)] = (value, basis, names)
    for (cls, domain), (value, basis, names) in sorted(worst.items()):
        out.append(_obs(PASS_JSD_METRIC, PASS_JSD_SCOPE, f"{cls}/{domain}", "ratio", round(value, 6)))
        if value > PASS_JSD_WARN and warnings is not None:
            warnings.append(f"{cls}/{domain}: {basis} residency differs between groups {names} (JSD {value:.3f} > "
                            f"{PASS_JSD_WARN}) — DVFS behaviour changed between passes (thermal / load)")
    return out


def reduce_samples(
    samples: Iterable[Any],
    *,
    cpu_map: dict[int, str],
    cluster_map: dict[str, str],
    warnings: list[str],
) -> list[dict]:
    """Reduce residency samples (``PmuSample``-like: metric, scope_kind, scope_ref, value, freq_mhz, group, line)."""
    freq: dict[tuple[str, str, str], dict[float, float]] = {}
    groups: dict[tuple[str, str, str], dict[str, dict[float, float]]] = {}
    states: dict[tuple[str, str], dict[str, float]] = {}
    missing: set[str] = set()
    for sample in samples:
        parsed = _parse(sample.metric)
        if parsed is None:
            continue
        cls, kind, what = parsed
        place = str(sample.scope_ref)
        if sample.scope_kind == "cpu":
            if cls != "cpu":
                raise ValueError(f"row {sample.line}: {sample.metric} needs a domain scope, not a CPU id")
            digits = "".join(ch for ch in place if ch.isdigit())
            domain = cpu_map.get(int(digits)) if digits else None
            if domain is None:
                missing.add(place)
                continue
        elif sample.scope_kind in ("cluster", DOMAIN_CLASSES[cls].domain_scope, "domain"):
            domain = cluster_map.get(place, place)
        elif not handles(sample.metric):
            continue  # e.g. a per-task CPU residency: the CPU profile reducer owns it
        else:
            raise ValueError(f"row {sample.line}: {sample.metric} needs scope cpu / cluster / {DOMAIN_CLASSES[cls].domain_scope}")
        if sample.value < 0:
            raise ValueError(f"row {sample.line}: {sample.metric} must be >= 0")
        if kind == "state":
            bucket = states.setdefault((cls, domain), {})
            bucket[what] = bucket.get(what, 0.0) + sample.value
            continue
        mhz = sample.freq_mhz
        if not mhz or not math.isfinite(mhz) or mhz <= 0:
            raise ValueError(f"row {sample.line}: {sample.metric} needs freq_mhz > 0")
        key = (cls, what, domain)
        level = freq.setdefault(key, {})
        level[mhz] = level.get(mhz, 0.0) + sample.value
        group = getattr(sample, "group", "") or ""
        g = groups.setdefault(key, {}).setdefault(group, {})
        g[mhz] = g.get(mhz, 0.0) + sample.value
    if missing:
        warnings.append(f"clock residency: CPU ids without cpu_map entry (skipped): {sorted(missing)}")
    return residency_observations(freq, states, groups, warnings=warnings)


def perfetto_observations(digest: Any) -> list[dict]:
    """Observations from ``PerfettoDigest.clock_residency`` / ``clock_ratios`` (see perfetto_digest)."""
    freq: dict[tuple[str, str, str], dict[float, float]] = {}
    for entry in getattr(digest, "clock_residency", None) or []:
        key = (entry["domain_class"], entry["basis"], entry["domain"])
        level = freq.setdefault(key, {})
        for mhz, dur in entry["bins"].items():
            level[float(mhz)] = level.get(float(mhz), 0.0) + float(dur)
    out = residency_observations(freq, emit_cpu_wall=True)
    for entry in getattr(digest, "clock_ratios", None) or []:
        dc = DOMAIN_CLASSES[entry["domain_class"]]
        out.append(_obs(dc.ratio_metric("active"), dc.domain_scope, entry["domain"], "ratio", round(entry["active_ratio"], 6)))
    return out
