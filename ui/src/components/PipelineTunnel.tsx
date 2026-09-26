import { useEffect, useRef } from 'react'
import { DOMAIN_LABEL, DOMAINS, type Domain, type Stage } from '../lib/tunnel'

const COL: Record<Stage['k'], string> = { rt: '#2BB3A3', m2m: '#E6A23C', mem: '#6C8EBF', sw: '#D4A93A', post: '#9C8CE0', out: '#4C8DF6' }
const BAYER = ['#E0584B', '#5BC26B', '#5BC26B', '#4F86E8']
const TAU = Math.PI * 2

/** Canvas 2D perspective fly-through of a generic multimedia pipeline (no WebGL / no library). */
export function PipelineTunnel({ domain, paused, speed = 0.176 }: { domain: Domain; paused: boolean; speed?: number }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  useEffect(() => {
    const cv = ref.current
    const g = cv?.getContext('2d')
    if (!cv || !g) return
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
    let reduce = motion.matches, dirty = true
    const motionChanged = () => { reduce = motion.matches; dirty = true }
    motion.addEventListener('change', motionChanged)
    const ST = DOMAINS[domain]
    const GAP = 460, N = ST.length, LOOP = GAP * N, F = 560, R = 250, VIEW = 3600
    let W = 1200, H = 800, cx = 0, cy = 0
    const resize = () => {
      dirty = true
      // Measure the container, not the canvas: if the stylesheet is missing the canvas would
      // otherwise size itself from its own backing store and grow without bound.
      const r = (cv.parentElement ?? cv).getBoundingClientRect()
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      W = Math.min(4096, Math.max(320, r.width)); H = Math.min(4096, Math.max(240, r.height))
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr)
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
      cx = W * 0.62; cy = H * 0.48
    }
    resize()
    const ro = new ResizeObserver(resize); ro.observe(cv.parentElement ?? cv)
    const A = Math.min(220, W * 0.18)
    // Same curvature and particle density for every domain: the camera loop (15 stages) is the reference,
    // shorter loops get proportionally fewer path cycles / particles so the flight feels equally fast.
    const REF = GAP * 15
    const cx1 = Math.max(1, Math.round((2 * LOOP) / REF)), cy1 = Math.max(1, Math.round((3 * LOOP) / REF))
    const path = (z: number) => ({ x: A * Math.sin(TAU * cx1 * z / LOOP), y: A * 0.5 * Math.sin(TAU * cy1 * z / LOOP + 1.3) })
    const stageAt = (z: number) => Math.floor((((z % LOOP) + LOOP) % LOOP) / GAP)
    const P = Array.from({ length: Math.max(96, Math.round((320 * LOOP) / REF)) }, (_, i) => ({ z: Math.random() * LOOP, a: Math.random() * TAU, r: 30 + Math.random() * 150, s: 0.25 + Math.random() * 0.35, q: i % 4 }))
    let cam = 0, last = performance.now(), raf = 0
    const rel = (z: number) => ((((z - cam) % LOOP) + LOOP) % LOOP)
    const pr = (x: number, y: number, d: number) => { const c = path(cam); return { x: cx + (x - c.x) * F / d, y: cy + (y - c.y) * F / d, k: F / d } }
    const fade = (d: number) => Math.max(0, Math.min(1, (d - 40) / 260)) * Math.max(0, Math.min(1, (VIEW - d) / 1400))
    const drawGate = (st: Stage, d: number, label: boolean) => {
      const p0 = path(cam + d), c = pr(p0.x, p0.y, d), a = fade(d), r = R * c.k, col = COL[st.k]
      g.globalAlpha = a; g.strokeStyle = col; g.lineWidth = Math.max(1, 5 * c.k)
      if (st.k === 'rt' || st.k === 'out') {
        g.beginPath(); g.arc(c.x, c.y, r, 0, TAU); g.stroke()
        g.globalAlpha = a * 0.25; g.lineWidth = Math.max(2, 18 * c.k); g.stroke()
        if (st.k === 'out') { g.globalAlpha = a; g.lineWidth = Math.max(1, 3 * c.k); g.beginPath(); g.arc(c.x, c.y, r * 0.86, 0, TAU); g.stroke() }
      } else if (st.k === 'm2m') {
        const s = r * 0.9
        g.beginPath(); g.rect(c.x - s, c.y - s * 0.72, 2 * s, 1.44 * s); g.stroke()
        g.globalAlpha = a * 0.25; g.lineWidth = Math.max(2, 16 * c.k); g.stroke()
      } else if (st.k === 'post') {
        g.beginPath()
        for (let k = 0; k < 6; k++) { const x = c.x + r * Math.cos(TAU * k / 6 + 0.52), y = c.y + r * Math.sin(TAU * k / 6 + 0.52); if (k) g.lineTo(x, y); else g.moveTo(x, y) }
        g.closePath(); g.stroke(); g.globalAlpha = a * 0.25; g.lineWidth = Math.max(2, 16 * c.k); g.stroke()
      } else if (st.k === 'sw') {
        g.setLineDash([12 * c.k, 10 * c.k]); g.beginPath(); g.arc(c.x, c.y, r * 0.95, 0, TAU); g.stroke(); g.setLineDash([])
      } else {
        for (let m = 0; m < 4; m++) {
          const dm = d + m * 26; if (dm > VIEW) continue
          const q0 = path(cam + dm), q = pr(q0.x, q0.y, dm), w = R * 1.1 * q.k, h = R * 0.62 * q.k
          g.globalAlpha = a * (0.22 - m * 0.04); g.fillStyle = col; g.fillRect(q.x - w, q.y - h, 2 * w, 2 * h)
          g.globalAlpha = a * 0.7; g.lineWidth = Math.max(1, 2 * q.k); g.strokeRect(q.x - w, q.y - h, 2 * w, 2 * h)
        }
      }
      // Labels only on the two nearest gates — far labels pile up at the vanishing point.
      if (!label) { g.globalAlpha = 1; return }
      const fs = Math.max(12, Math.min(34, 26 * c.k * 2.2))
      g.globalAlpha = a; g.textAlign = 'center'; g.fillStyle = '#F2F6F7'
      g.font = `600 ${fs.toFixed(0)}px ui-monospace, 'IBM Plex Mono', Consolas, monospace`
      const ly = c.y - (st.k === 'mem' ? R * 0.62 * c.k : st.k === 'm2m' ? r * 0.65 : r) - fs * 0.6
      g.fillText(st.n, c.x, ly)
      if (fs > 13) { g.font = `400 ${(fs * 0.5).toFixed(0)}px system-ui, sans-serif`; g.fillStyle = col; g.fillText(st.s, c.x, ly + fs * 0.62) }
      g.globalAlpha = 1
    }
    const draw = () => {
      g.fillStyle = '#0B1116'; g.fillRect(0, 0, W, H)
      const vg = g.createRadialGradient(cx, cy, 20, cx, cy, Math.max(W, H) * 0.6)
      vg.addColorStop(0, 'rgba(43,179,163,0.10)'); vg.addColorStop(1, 'rgba(11,17,22,0)')
      g.fillStyle = vg; g.fillRect(0, 0, W, H)
      g.lineWidth = 1
      for (let j = 0; j < 14; j++) {
        const th = TAU * j / 14
        g.beginPath()
        let first = true
        for (let d = VIEW; d > 30; d -= 90) {
          const p0 = path(cam + d), p = pr(p0.x + 330 * Math.cos(th), p0.y + 330 * Math.sin(th), d)
          if (first) { g.moveTo(p.x, p.y); first = false } else g.lineTo(p.x, p.y)
        }
        g.strokeStyle = 'rgba(127,214,200,0.07)'; g.stroke()
      }
      for (let d = VIEW - (cam % 160); d > 60; d -= 160) {
        const p0 = path(cam + d), p = pr(p0.x, p0.y, d)
        g.beginPath(); g.arc(p.x, p.y, 330 * p.k, 0, TAU)
        g.strokeStyle = `rgba(127,214,200,${(0.05 * fade(d)).toFixed(3)})`; g.stroke()
      }
      const gates = ST.map((st, i) => ({ st, d: rel(i * GAP + GAP * 0.55) })).filter((o) => o.d > 30 && o.d < VIEW).sort((a, b) => b.d - a.d)
      const parts = P.map((p) => ({ p, d: rel(p.z) })).filter((o) => o.d > 30 && o.d < VIEW).sort((a, b) => b.d - a.d)
      const labelled = new Set(gates.slice(-2).map((o) => o.st))
      let gi = 0
      for (const { p, d } of parts) {
        while (gi < gates.length && gates[gi].d > d) { drawGate(gates[gi].st, gates[gi].d, labelled.has(gates[gi].st)); gi++ }
        const p0 = path(p.z), q = pr(p0.x + p.r * Math.cos(p.a), p0.y + p.r * Math.sin(p.a), d)
        const pc = ST[stageAt(p.z)].c
        const sz = Math.max(1, Math.min(9, 7 * q.k))
        g.globalAlpha = fade(d) * 0.9; g.fillStyle = pc === 'raw' ? BAYER[p.q] : pc; g.fillRect(q.x - sz / 2, q.y - sz / 2, sz, sz)
      }
      while (gi < gates.length) { drawGate(gates[gi].st, gates[gi].d, labelled.has(gates[gi].st)); gi++ }
      g.globalAlpha = 1
      const next = ST.map((st, i) => ({ st, d: rel(i * GAP + GAP * 0.55) })).filter((o) => o.d > 40).sort((a, b) => a.d - b.d)[0]
      if (next && W > 900) { // narrower: the HUD would cover the intro card
        const x = W - 320, y = 64 // top-right under the controls; bottom is the stats row
        g.fillStyle = 'rgba(11,17,22,0.72)'; g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 1
        g.beginPath(); if (g.roundRect) g.roundRect(x, y, 300, 122, 12); else g.rect(x, y, 300, 122); g.fill(); g.stroke()
        g.textAlign = 'left'
        g.fillStyle = '#9FB0B6'; g.font = '12px system-ui, sans-serif'; g.fillText(`다음 stage · ${DOMAIN_LABEL[domain]}`, x + 16, y + 24, 268)
        g.fillStyle = COL[next.st.k]; g.font = "600 22px ui-monospace, 'IBM Plex Mono', Consolas, monospace"; g.fillText(next.st.n, x + 16, y + 54, 268)
        g.fillStyle = '#E8EEF0'; g.font = '13px system-ui, sans-serif'; g.fillText(`${next.st.s} · ${next.st.i}`, x + 16, y + 78, 268)
        g.fillStyle = '#7C8C92'; g.font = '12px system-ui, sans-serif'; g.fillText(`IP 매핑 예: ${next.st.e} (DB scenario 기준)`, x + 16, y + 100, 268)
      }
    }
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop)
      const dt = Math.min(50, now - last); last = now
      const animate = !pausedRef.current && !reduce && !document.hidden
      if (animate) {
        cam = (cam + dt * speed * 3) % LOOP
        for (const p of P) { p.z = (p.z + dt * speed * 3 * (1 + p.s)) % LOOP; p.a += dt * 0.0002 }
      }
      if (!document.hidden && (animate || dirty)) { draw(); dirty = false }
    }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); motion.removeEventListener('change', motionChanged) }
  }, [domain, speed])

  return <canvas ref={ref} className="tunnel-canvas" role="img"
    aria-label={`${DOMAIN_LABEL[domain]} pipeline을 따라 날아가는 애니메이션: ${DOMAINS[domain].map((s) => s.n).join(', ')}`} />
}
