// CPU what-if: the RT chain the wait (response) model uses — the SW order of each Timing Budget stage, read from the
// variant's pipeline graph. A next project with another chain (members, order, parallel branches, other stage)
// shows its own order here without a code change; the scheduling class of each member comes from task_policy.
import { fmt } from '../lib/timingBudget'
import { schedText, type TaskSched, type TimingCoupling } from '../lib/rebalance'
import { Card } from './TimingCharts'

/** Members in pipeline order (fewest predecessors first); `total` = every pair ordered, i.e. one serial chain. */
export function chainOrder(order: [string, string][]): { tasks: string[]; total: boolean } {
  const tasks = [...new Set(order.flat())]
  const before = (t: string) => order.filter(([, b]) => b === t).length
  tasks.sort((a, b) => before(a) - before(b) || a.localeCompare(b))
  return { tasks, total: order.length === (tasks.length * (tasks.length - 1)) / 2 }
}

export function RtChainCard({ coupling, sched, rtPlacement }: {
  coupling?: TimingCoupling; sched: Record<string, TaskSched | undefined>; rtPlacement?: 'eas' | 'cpupri'
}) {
  const stages = (coupling?.stages ?? []).filter((s) => s.order?.length)
  if (!coupling || !stages.length) return null
  const cls = (t: string) => schedText(sched[t]) ?? 'nice 0 (미지정)'
  return (
    <Card id="cpu-rt-chain" title="RT chain · 대기 계산 기준" defaultWide minHeight={80}
      note={`${coupling.scenario_id} / ${coupling.variant_id} pipeline의 stage별 SW 순서 · 표시는 측정 배치 기준, 후보마다 chain 길이로 다시 판정 · RT 배치 ${rtPlacement === 'cpupri' ? 'cpupri (RT가 없는 CPU 먼저)' : 'EAS (CFS와 같음)'}`}
      help={<>같은 frame에서 pipeline이 순서를 정한 task (앞 task가 끝나야 뒤 task가 시작)는 같은 CPU에 있어도 서로 기다리지 않습니다.
        stage chain(같은 frame 순서로 이어진 SW와 HW의 최장 경로 — 직렬 HW는 모두 더함)이 frame 주기보다 길면 다음 frame의 같은 task와 겹칠 수 있으므로 이 순서를 쓰지 않고 모두 대기에 넣습니다 (보수적).
        순서는 variant의 pipeline에서 읽으므로 다음 과제의 RT chain 구조가 바뀌면 자동으로 바뀝니다. 스케줄링 클래스는 scheduler.task_policy 값입니다.</>}>
      <div style={{ display: 'grid', gap: 4, fontSize: 12.5 }}>
        {stages.map((s) => {
          const c = chainOrder(s.order!)
          const chain = s.chain_ms ?? s.sw_ms + s.hw_ms + s.overhead_ms    // the server's chain (serial HW included)
          return <div key={s.stage} className="toolbar" style={{ gap: 8, flexWrap: 'wrap' }}>
            <b className="mono">{s.stage.toUpperCase()}</b>
            <span className="mono">{c.total ? c.tasks.map((t) => `${t} (${cls(t)})`).join(' → ')
              : s.order!.map(([a, b]) => `${a} → ${b}`).join(' · ')}</span>
            {!c.total && <span className="badge" title="순서가 정해지지 않은 task 쌍은 동시에 돌 수 있어 서로 대기에 포함">병렬 분기 있음</span>}
            {s.serial
              ? <span className="badge v-ok" title="stage chain이 한 frame 안에 끝나므로 이 순서의 task는 동시에 돌지 않음">순서 고정 · 서로 대기 없음</span>
              : <span className="badge v-warn" title="stage chain이 frame 주기보다 길어 다음 frame의 task와 겹칠 수 있음">chain {fmt(chain, 1)} ms &gt; frame {fmt(coupling.period_ms, 1)} ms · 대기에 포함</span>}
          </div>
        })}
      </div>
    </Card>
  )
}
