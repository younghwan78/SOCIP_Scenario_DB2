import { Fragment, type ReactNode } from 'react'
import { LANE_LABEL, type BufferRow, type DmaChannel, type IpModel, type Port } from '../lib/model'
import type { StageTiming } from '../lib/cadence'
import { memoryText } from '../lib/graph'
import { groupPorts } from './IpInternalView'

const f2 = (x: number) => (x >= 10 ? x.toFixed(1) : x.toFixed(2))
const portInfo = (p?: Port) => (p ? [p.size, p.format, p.bit ? `${p.bit}b` : '', p.comp && p.comp !== 'COMP_OFF' ? p.comp.replace('COMP_', '') : ''].filter(Boolean).join(' ') : '')

function Channels({ title, list, ports, color, total, expanded = false }: { title: string; list: DmaChannel[]; ports: Port[]; color: string; total: number | null; expanded?: boolean }) {
  const used = list.filter((c) => c.status === 'used')
  const off = list.filter((c) => c.status === 'off')
  if (!used.length && !off.length && !total) return null
  return (
    <div className="tt-sec">
      <b>{title} · 사용 {used.length}{total !== null ? ` / ${total}` : ''}</b>
      {(() => {
        const names = new Set(used.map((c) => c.name))
        const g = groupPorts(ports.filter((p) => names.has(p.port) && p.via !== 'OTF'))
        const rest = used.filter((c) => !ports.some((p) => p.port === c.name && p.via !== 'OTF'))
        const rows = [...g.map((p) => ({ k: p.port, name: p.port, buf: p.buffer, info: portInfo(p) || (p.peer ?? '') })), ...rest.map((c) => ({ k: c.name, name: c.name, buf: c.buffer, info: c.peer ?? '' }))]
        const shown = expanded ? rows : rows.slice(0, 10)
        return <>{shown.map((r) => <div key={r.k} className="tt-port"><span className="d" style={{ background: color }} />
          <span>{r.name}{r.buf ? <span className="faint"> · {r.buf}</span> : null}</span><span className="m">{r.info}</span></div>)}
          {!expanded && rows.length > 10 && <div className="faint" style={{ fontSize: 10.5 }}>+{rows.length - 10} more (고정하면 전체)</div>}</>
      })()}
      {off.map((c) => <div key={c.name} className="tt-port tt-off"><span className="d" style={{ border: `1px dashed ${color}` }} /><span>{c.name} · off</span><span className="m">{c.buffer ?? ''}</span></div>)}
    </div>
  )
}

export function IpTooltip({ ip, timing, expanded = false }: { ip: IpModel; timing?: StageTiming; expanded?: boolean }): ReactNode {
  const otf = ip.ports.filter((p) => p.via === 'OTF')
  const ctrl = ip.ports.filter((p) => p.via === 'ctrl')
  const unused = ip.channels.filter((c) => c.status === 'unused' && c.kind === 'DMA')
  const outs = ip.outSizes.filter((o) => o !== ip.inSize)
  return (
    <div>
      <h4>{ip.label} <span className="sub">{LANE_LABEL[ip.lane]} · {ip.ipRef.replace(/^ip-/, '')}</span></h4>
      <div className="tt-sec tt-kv">
        {ip.type !== 'sw' && <><span>In (처리)</span><span className="mono">{ip.inSize || '—'}</span>
          <span>Out</span><span className="mono">{outs.join(' / ') || (otf.some((p) => p.dir === 'out') ? 'OTF' : '—')}</span></>}
        {ip.ops.length > 0 && <><span>Ops</span><span>{ip.ops.join(' · ')}</span></>}
        {(ip.mode || ip.modes?.length) && <><span>Mode</span><span className="mono">{ip.mode ?? '—'}{!expanded && (ip.modes?.length ?? 0) > 0 ? <span className="faint"> (catalog {ip.modes!.length}개)</span> : null}</span></>}
        {timing && <><span>Timing</span><span className="mono">+{f2(timing.offset)} ms · {f2(timing.dur)} ms ({f2(timing.durMin)}–{f2(timing.durMax)}, n{timing.n})</span></>}
        {ip.sw && <><span>SW time</span><span className="mono">{ip.sw.mean} ms ({ip.sw.min}–{ip.sw.max}) · {ip.sw.source}</span></>}
        {otf.length > 0 && <><span>OTF</span><span className="mono">{otf.map((p) => `${p.dir === 'in' ? '←' : '→'} ${p.peer}`).join('  ')}</span></>}
        {ctrl.length > 0 && <><span>SW trigger</span><span>{ctrl.map((p) => `${p.dir === 'in' ? '←' : '→'} ${p.peer}`).join('  ')}</span></>}
        {(expanded ? ip.flags : ip.flags.slice(0, 4)).map(([k, v]) => <Fragment key={k}><span>{k}</span><span className="mono">{v}</span></Fragment>)}
        {!expanded && ip.flags.length > 4 && <><span /><span className="faint">+{ip.flags.length - 4} config</span></>}
      </div>
      {expanded && (ip.modes?.length ?? 0) > 0 && <div className="tt-sec"><b>Operating modes · {ip.modes!.length}</b>
        <div className="tt-chips">{ip.modes!.map((m) => <span key={m} className={m === ip.mode ? 'on' : ''}>{m}</span>)}</div></div>}
      <Channels title="RDMA" list={ip.channels.filter((c) => c.kind === 'DMA' && c.dir === 'in')} ports={ip.ports} color="#2563EB" total={ip.rdma.total} expanded={expanded} />
      <Channels title="WDMA" list={ip.channels.filter((c) => c.kind === 'DMA' && c.dir === 'out')} ports={ip.ports} color="#F97316" total={ip.wdma.total} expanded={expanded} />
      {unused.length > 0 && <div className="tt-sec"><b>미사용 DMA · {unused.length}</b>
        <div className="tt-chips">{(expanded ? unused : unused.slice(0, 14)).map((c) => <span key={c.name} title={c.purpose}>{c.name}</span>)}{!expanded && unused.length > 14 && <span>+{unused.length - 14}</span>}</div></div>}
      {ip.type !== 'sw' && ip.rdma.total === null && <div className="tt-sec faint" style={{ fontSize: 11 }}>IP catalog에 DMA 목록이 없어 사용 채널만 표시</div>}
      <div className="faint" style={{ fontSize: 10.5, marginTop: 6 }}>클릭 = 선택 · 하단 상세 / IP 내부에서 전체 port{expanded ? '' : ' · 고정하면 전체 목록'}</div>
    </div>
  )
}

export function BufferTooltip({ b }: { b: BufferRow }): ReactNode {
  return (
    <div>
      <h4>{b.name} <span className="sub">{b.kind}{b.enabled ? '' : ' · off'}</span></h4>
      <div className="tt-sec tt-kv">
        <span>Producer</span><span>{b.producer} <span className="mono faint">{b.wPorts.join(', ')}</span></span>
        <span>Consumer</span><span>{b.consumers.join(', ') || '—'} <span className="mono faint">{b.rPorts.join(', ')}</span></span>
        <span>Size / fmt</span><span className="mono">{memoryText({ width: b.width, height: b.height, format: b.format, bitdepth: b.bit, compression: b.comp }) || '미정'}</span>
        <span>MB / frame</span><span className="mono">{b.mbFrame?.toFixed(2) ?? '—'}</span>
        <span>W / R MB/s</span><span className="mono">{b.wMBs ?? '—'} / {b.rMBs ?? '—'}{b.fps ? ` @${b.fps}fps` : ''}</span>
      </div>
      {b.note && <div className="tt-sec faint" style={{ fontSize: 11 }}>{b.note}</div>}
    </div>
  )
}
