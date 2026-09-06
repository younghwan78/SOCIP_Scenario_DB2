// Mirrors timing_chart.format_ms so tooltips match the Plotly hover text.
export function numeric(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

export function formatMs(value: unknown): string {
  const num = numeric(value)
  if (num === null) return '-'
  let text = num.toFixed(3)
  if (text.includes('.')) {
    text = text.replace(/0+$/, '').replace(/\.$/, '')
  }
  return `${text} ms`
}
