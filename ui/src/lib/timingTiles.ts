// Timing Budget summary tiles chosen from what the report carries (X-01).
// Camera scenarios keep the stage / clock / interval tiles; a scenario without a stage, an output interval or a
// DVFS operating point gets no tile for it, and the judging subject (job milestones, KPI targets, frame pacing,
// domain loads) takes its place. Never a red tile for something the verdict does not judge.
import { maText, type Battery } from './battery'
import type { Prov } from './provenance'
import { fmt, pct0, stageDomainsOf, stageSlack, type KpiResult, type StageDomain, type StageId, type StageRow, type TimingReport } from './timingBudget'

export interface SummaryTile { id: string; label: string; value: string; unit: string; note: string; bad: boolean; prov?: Prov; small?: boolean }

/** A stage is shown when it has a node or a SW task (audio / game have empty RT / Post stages). */
export function stagePresent(s: StageRow | undefined): boolean {
  return !!s && (s.nodes.length > 0 || s.sw_items.length > 0)
}

/** A stage domain clock with its operating point: a 0 MHz row (GPU / AUD, clocked outside the stage model) takes the
 * domain load or subsystem clock of one of its nodes. */
export interface DomainPoint { domain: string; mhz: number | null; source: 'stage' | 'domain_load' | 'subsystem' | 'none'; row: StageDomain; note: string }

export function domainPoints(r: Pick<TimingReport, 'ips' | 'stage_domains' | 'power' | 'subsystems'>, stage: StageId): DomainPoint[] {
  return stageDomainsOf(r, stage).map((d) => {
    if (d.set_mhz > 0) {
      const note = `${d.domain} 필요 ${fmt(d.required_mhz, 0)}${d.level !== null ? `→L${d.level}` : ''}${d.headroom_pct !== null ? ` 여유 ${fmt(d.headroom_pct, 0)}%` : ''}${d.set_reason === 'domain' && d.domain_leader ? ` (${d.domain_leader.toUpperCase()}가 결정)` : ''}`
      return { domain: d.domain, mhz: d.set_mhz, source: 'stage', row: d, note }
    }
    const loads = r.power.domain_loads ?? {}
    for (const n of d.nodes) {
      const l = loads[n]
      if (l && l.freq_mhz != null && l.freq_mhz > 0) {
        const how = l.model === 'util-vf-v1' ? (l.freq_by === 'fixed' ? '고정' : 'governor') : 'subsystem'
        return { domain: d.domain, mhz: l.freq_mhz, source: 'domain_load', row: d, note: `${d.domain} ${n.toUpperCase()} ${how} · util ${fmt(l.util * 100, 0)}%` }
      }
    }
    for (const [node, s] of Object.entries(r.subsystems ?? {})) {
      const dom = s.domains?.[d.domain]
      if (dom?.freq_mhz != null && dom.freq_mhz > 0) {
        return { domain: d.domain, mhz: dom.freq_mhz, source: 'subsystem', row: d, note: `${d.domain} ${node.toUpperCase()} subsystem${dom.pinned ? ' 고정' : ''}` }
      }
    }
    return { domain: d.domain, mhz: null, source: 'none', row: d, note: `${d.domain} 운영점 없음` }
  })
}

const KPI_NAME: Record<string, string> = {
  event_latency: '촬영 →', underrun: 'deadline 여유 (underrun)', latency: 'latency', peak_bw: 'peak BW', peak_power: 'peak power',
  peak_footprint: 'peak memory', event_energy: 'event energy', frame_pacing: 'frame pacing',
}
const num = (v: number | null) => (v == null ? '—' : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2))

/** Label of a KPI row in a tile: milestone for event latency, else the KPI name and its job. */
export function kpiLabel(k: Pick<KpiResult, 'kpi' | 'id' | 'job' | 'milestone' | 'metric'>): string {
  const name = KPI_NAME[k.kpi] ?? k.kpi
  if (k.kpi === 'event_latency' && k.milestone) return `${name} ${k.milestone}`
  return `${name}${k.metric ? `.${k.metric}` : ''}`
}

/** Targeted KPI rows worst first (fail before pass), at most ``limit``; the rest is counted. */
export function judgedKpis(rows: KpiResult[] | undefined, limit: number): { shown: KpiResult[]; rest: number } {
  const targeted = (rows ?? []).filter((k) => k.target != null && (k.status === 'pass' || k.status === 'fail'))
  const ordered = [...targeted.filter((k) => k.status === 'fail'), ...targeted.filter((k) => k.status !== 'fail')]
  return { shown: ordered.slice(0, limit), rest: Math.max(0, ordered.length - limit) }
}

export function summaryTiles(r: TimingReport, margin: number, battery: Battery, prov?: Prov): SummaryTile[] {
  const st = Object.fromEntries(r.stages.map((s) => [s.id, s])) as Partial<Record<StageId, StageRow>>
  const out: SummaryTile[] = []
  const rt = st.rt, nrt = st.nrt, post = st.post
  if (rt && stagePresent(rt)) {
    const readout = r.ips.find((i) => i.stage === 'rt' && i.sensor_readout_ms)?.sensor_readout_ms ?? null
    out.push({ id: 'rt', label: `RT HW / ${pct0(1 - margin)} 예산`, value: fmt(rt.hw_ms, 2), unit: `/ ${fmt(rt.budget_ms, 2)} ms`,
      note: readout ? `sensor readout ${fmt(readout, 2)} ms에 종속 · clock = readout 만족 최소 (margin 무관)` : `SW margin ${pct0(margin)} rule${Math.abs(margin - 0.25) > 1e-9 ? ' (기본 25%에서 변경)' : ''}`,
      bad: rt.hw_ms > rt.budget_ms })
  }
  if (nrt && (nrt.sw_items.length > 0 || nrt.hw_ms > 0)) {
    out.push({ id: 'nrt', label: 'NRT SW (runtime+latency)', value: fmt(nrt.sw_ms, 2), unit: 'ms', note: `HW 예산 ${fmt(nrt.budget_ms, 2)} ms`, bad: !nrt.feasible })
  }
  if (post && stagePresent(post)) {
    out.push({ id: 'post', label: r.eis.on ? 'Post SW (EIS 등)' : 'Post SW', value: fmt(post.sw_ms, 2), unit: 'ms', note: r.eis.on ? 'EIS ON' : 'EIS OFF', bad: !post.feasible })
  }
  const pts = domainPoints(r, 'nrt')
  if (pts.length) {
    const known = pts.filter((p) => p.mhz !== null)
    out.push({ id: 'clock', label: 'NRT clock · DVFS domain별', value: known.map((p) => `${p.domain} ${fmt(p.mhz, 0)}`).join(' · ') || '운영점 없음', unit: known.length ? 'MHz' : '',
      note: pts.map((p) => p.note).join(' · '),
      bad: pts.some((p) => p.source === 'stage' && p.row.rule_mhz !== null && p.row.rule_mhz > 0 && p.row.set_mhz > p.row.rule_mhz * 1.05), small: pts.length > 1 })
  }
  const slack = stageSlack(r)
  const slackStages = (['rt', 'nrt', 'post'] as const).filter((s) => (s === 'nrt' ? !!nrt && (nrt.sw_items.length > 0 || nrt.hw_ms > 0) : stagePresent(st[s])))
  if (slackStages.length) {
    const pipelined = r.stages.some((s) => s.throughput === 'pipelined')
    out.push({ id: 'slack', label: 'SW 여유 · 현재 clock', value: slackStages.map((s) => fmt(slack[s], 1)).join(' / '), unit: 'ms',
      note: `${slackStages.map((s) => (s === 'rt' ? 'RT' : s === 'nrt' ? 'NRT' : 'Post')).join(' / ')} — SW가 더 쓸 수 있는 시간${pipelined ? ' (NRT·Post = period − 최장 SW task)' : ' (NRT·Post = period − SW − HW)'}`,
      bad: slackStages.some((s) => slack[s] < 0), small: true })
  }
  const iv = r.intervals
  const streams = ([['Preview', iv.preview], ['Video', iv.video]] as const).filter(([, s]) => !!s.node)
  if (streams.length) {
    const bad = streams.some(([, s]) => s.ok === false)
    out.push({ id: 'interval', label: `${streams.map(([n]) => n).join(' / ')} 간격`, value: streams.map(([, s]) => fmt(s.max_ms, 2)).join(' / '), unit: 'ms',
      note: bad ? '목표 이탈' : `목표 ${fmt(iv.target_ms, 2)} ±${fmt(iv.tolerance * 100, 1)}% ✓`, bad })
  }
  // judging subjects other than the frame interval: event jobs, KPI targets, frame pacing
  for (const j of (r.jobs ?? []).slice(0, 1)) {
    const ms = Object.entries(j.milestones ?? {}).sort((a, b) => a[1] - b[1])
    out.push({ id: `job-${j.id}`, label: `Event job · ${j.id}`, value: fmt(j.makespan_ms, 1), unit: 'ms',
      note: [ms.map(([k, v]) => `${k} ${fmt(v, 1)}`).join(' · '), j.peak ? `peak ${fmt(j.peak.power_mw, 0)} mW / ${fmt(j.peak.window_ms, 0)} ms 창` : '', (r.jobs?.length ?? 0) > 1 ? `외 job ${(r.jobs?.length ?? 1) - 1}개` : ''].filter(Boolean).join(' · '),
      bad: false })
  }
  if (r.pacing && r.pacing.status !== 'no_gpu_time') {
    const p = r.pacing
    out.push({ id: 'pacing', label: '달성 fps · jank', value: `${fmt(p.achieved_fps ?? null, 1)} / ${fmt(p.target_fps ?? null, 0)}`, unit: 'fps',
      note: `jank ${fmt(p.jank_pct ?? null, 2)}% · fail < ${fmt(p.fail_below_fps ?? null, 1)} fps`, bad: p.status === 'fail', small: true })
  }
  const kp = judgedKpis(r.kpis, 3)
  kp.shown.forEach((k, i) => {
    const last = i === kp.shown.length - 1 && kp.rest > 0
    out.push({ id: `kpi-${i}`, label: kpiLabel(k), value: num(k.value), unit: k.unit,
      note: `목표 ${k.bound === 'min' ? '≥' : '≤'} ${num(k.target)} ${k.unit}${k.job ? ` · ${k.job}` : ''}${k.value_source === 'assumed' ? ' · 가정 목표' : ''}${k.status === 'fail' ? ' · 미달' : ''}${last ? ` · 외 KPI ${kp.rest}개 (⑤-a)` : ''}`,
      bad: k.status === 'fail' })
  })
  for (const [node, l] of Object.entries(r.power.domain_loads ?? {}).slice(0, 2)) {
    const how = l.model === 'util-vf-v1' ? (l.freq_by === 'fixed' ? '고정' : 'governor') : 'subsystem'
    out.push({ id: `load-${node}`, label: `${node.toUpperCase()} (domain load)`, value: fmt(l.mw, 1), unit: 'mW',
      note: `${l.freq_mhz != null ? `${fmt(l.freq_mhz, 0)} MHz ${how}` : '운영점 없음'} · util ${fmt(l.util * 100, 0)}%${l.value_source === 'assumed' ? ' · 가정' : ''}`, bad: !l.feasible })
  }
  const p = r.power
  out.push({ id: 'power', label: 'Power · BW', value: fmt(p.total_mw, 0), unit: `mW · ${maText(p.total_mw, battery)}@Vbat`,
    note: `CPU ${fmt(p.cpu_mw, 0)} · HW ${fmt(p.hw_mw, 0)} · BW ${fmt(p.bw_mw, 0)}${p.residency_mw != null ? ` · wake ${fmt(p.residency_mw, 0)}` : ''} · ${fmt(r.bw.total_mbs / 1000, 2)} GB/s`, bad: false, prov })
  return out
}
